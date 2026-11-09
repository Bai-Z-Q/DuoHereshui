# -*- coding: utf-8 -*-
"""
模块 2：Leader-Worker 编排器

主诊 Agent（Leader）只负责路由、调度与最终表达；四类 Worker 各自独立上下文：
    Triage  分诊：症状识别、紧急度、渐进式问诊
    Memory  记忆：档案、历史摘要、语义记忆
    Retrieval 检索：药品库 + 知识库 + 引用
    Safety  安全：规则护栏（双层校验的第二层）
另有 Trace Recorder 贯穿全链路，形成可审计的调用链。

工作流状态机：
    screen → triage → memory → retrieval → generate → guardrail → archive
高危节点（急症）直接短路到 emergency 分支；信息不足则进入 clarify 分支。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..utils.nlp import NLPProcessor
from .guardrails import (
    DISCLAIMER,
    GuardrailContext,
    GuardrailIssue,
    assess_risk,
    build_fallback_answer,
    build_regeneration_instruction,
    emergency_answer,
    ensure_disclaimer,
    guard_output,
    max_risk,
    risk_meta,
    screen_input,
)
from .memory import MemoryService, format_memory_for_prompt
from .prompts import build_system_prompt
from .retrieval import RetrievalResult, RetrievalService
from .router import RouteDecision, choose_route
from .trace import TraceRecorder
from .triage import build_clarifying_answer, screen_context, triage

TOOL_LABELS = {
    "search_drugs": "正在检索药品库…",
    "get_drug_detail": "正在读取药品说明书…",
    "recommend_drugs_by_symptom": "正在匹配非处方药…",
    "list_otc_drugs": "正在读取 OTC 清单…",
    "get_my_current_medications": "正在核对你的在用药物…",
    "check_drug_safety": "正在做用药安全校验…",
    "search_knowledge": "正在检索健康知识库…",
}

SOURCE_LABELS = {
    "drug_label": "药品说明书",
    "drug_db": "药品库",
    "guideline": "健康科普",
    "article": "健康资料",
}


def _stage(stage: str, label: str, status: str = "done") -> Dict:
    return {"type": "stage", "stage": stage, "label": label, "status": status}


def _public_citations(citations: List[Dict]) -> List[Dict]:
    return [
        {
            "ref": item.get("ref"),
            "chunk_id": item.get("chunk_id") or item.get("source_id"),
            "source_type": item.get("source_type"),
            "source_id": item.get("source_id"),
            "title": item.get("title"),
            "section": item.get("section"),
            "snippet": item.get("snippet"),
            "updated_at": item.get("updated_at"),
        }
        for item in citations[:6]
    ]


def _append_citations(answer: str, citations: List[Dict]) -> str:
    """在免责声明之前插入参考来源列表"""
    answer = (answer or "").rstrip()
    if not citations:
        return answer

    lines = ["", "参考来源："]
    for item in citations[:4]:
        source = SOURCE_LABELS.get(item.get("source_type", ""), "资料")
        updated = item.get("updated_at")
        updated_text = f"，更新于 {str(updated)[:10]}" if updated else ""
        lines.append(f"[S{item.get('ref')}] {item.get('title')}·{item.get('section')}（{source}{updated_text}）")
    block = "\n".join(lines)

    disclaimer_pos = answer.find("⚠️ 以上建议仅供参考")
    if disclaimer_pos >= 0:
        head = answer[:disclaimer_pos].rstrip()
        tail = answer[disclaimer_pos:]
        return head + block + "\n\n" + tail
    return answer + block


class MedicalOrchestrator:
    """Leader-Worker 医疗咨询编排器"""

    def __init__(self, agent: Any):
        self.agent = agent

    # ------------------------------------------------------------ 主流程
    async def stream(
        self,
        db: Session,
        user_message: str,
        history: Optional[List[Dict]] = None,
        profile: Optional[Dict] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        answer_to: Optional[str] = None,
    ) -> AsyncIterator[Dict]:
        started = time.perf_counter()
        trace = TraceRecorder(
            db=db, user_id=user_id, session_id=session_id, user_input=user_message
        )
        history = history or []
        profile = profile or {}
        # 追问短回答（"今天刚开始"）需结合上一轮症状做安全筛查
        screen = screen_input(screen_context(user_message, history))
        # 选项回答 / 追问短回答都标记为 triage_answer，绕开「短文本→药品名」误判
        followup_answer = bool(answer_to) or NLPProcessor.is_triage_answer_only(user_message)
        intent = "triage_answer" if followup_answer else NLPProcessor.detect_intent(user_message)
        trace.intent = intent
        route = choose_route(
            intent,
            user_message,
            screen,
            history_len=len(history),
            default_model=getattr(self.agent, "model", None),
        )
        trace.route = route.route
        trace.model = route.model

        try:
            yield _stage("screen", "安全检查")
            trace.add_step(
                "guardrail",
                "input_screen",
                detail={"level": screen.level, "matched": screen.matched},
            )

            # ---------------- 高危节点：急症硬拦截 ----------------
            if screen.is_emergency:
                answer = emergency_answer(screen, profile)
                trace.risk_level = "critical"
                trace.add_step(
                    "orchestrator",
                    "route_emergency",
                    detail={"matched": screen.matched, "categories": screen.categories},
                )
                trace_id = trace.finish(
                    answer,
                    status="blocked",
                    guardrail={"blocked": True, "code": "emergency", "matched": screen.matched},
                )
                meta = risk_meta("critical")
                yield {
                    "type": "risk",
                    "level": "critical",
                    "label": meta["label"],
                    "advice": meta["advice"],
                    "reasons": screen.reasons[:4],
                }
                async for chunk in self._chunk_text(answer):
                    yield {"type": "token", "text": chunk}
                yield self._done_event(
                    trace_id, route, "critical", True, session_id, started, intent
                )
                return

            # ---------------- 分诊 Worker ----------------
            triage_result = triage(
                user_message, history, profile, screen, answer_to=answer_to
            )
            trace.add_step(
                "triage",
                "assess",
                detail={
                    "symptoms": triage_result.symptoms,
                    "urgency": triage_result.urgency,
                    "needs_info": triage_result.needs_info,
                    "department": triage_result.department,
                    "dimension": triage_result.dimension,
                    "missing": triage_result.missing,
                },
            )
            yield _stage("triage", "分诊判断")

            # 渐进式问诊：只问一个关键问题
            if settings.AGENT_TRIAGE_ENABLED and triage_result.needs_info:
                answer = build_clarifying_answer(triage_result)
                risk_level = assess_risk(screen, profile, [])
                trace.risk_level = risk_level
                trace.add_step("triage", "clarify", detail={"question": triage_result.question})
                trace_id = trace.finish(
                    answer,
                    status="ok",
                    guardrail={"blocked": False, "code": "clarify"},
                )
                meta = risk_meta(risk_level)
                yield {
                    "type": "risk",
                    "level": risk_level,
                    "label": meta["label"],
                    "advice": meta["advice"],
                    "reasons": screen.reasons[:3],
                }
                yield {
                    "type": "options",
                    "items": [
                        {"text": opt, "answer_to": triage_result.dimension}
                        for opt in triage_result.options
                    ],
                }
                async for chunk in self._chunk_text(answer):
                    yield {"type": "token", "text": chunk}
                yield self._done_event(
                    trace_id, route, risk_level, False, session_id, started, intent
                )
                return

            # ---------------- 记忆 Worker ----------------
            memory_ctx: Dict = {}
            if settings.AGENT_MEMORY_ENABLED and user_id:
                memory_ctx = (
                    self._safe(
                        trace,
                        "memory",
                        "load_context",
                        lambda: MemoryService.context(
                            db,
                            user_id,
                            session_id,
                            triage_result.context_text or user_message,
                        ),
                        {},
                    )
                    or {}
                )
                yield _stage("memory", "加载健康记忆")

            merged_profile = self._merge_profile(profile, memory_ctx.get("profile") or {})

            # ---------------- 检索 Worker ----------------
            # 追问答案场景用分诊合并后的上下文检索（症状+回答），
            # 避免拿"今天刚开始"这种纯回答文本去查药品库/知识库；
            # 若追问答案没有任何症状上下文（孤立选项文本），跳过检索，不产生无关引用。
            if intent == "triage_answer" and not triage_result.symptoms:
                retrieval_query = ""
            else:
                base_text = triage_result.context_text or user_message
                retrieval_query = " ".join([*triage_result.symptoms, base_text]).strip()
            retrieval = (
                self._safe(
                    trace,
                    "retrieval",
                    "hybrid_search",
                    lambda: RetrievalService.retrieve(db, retrieval_query),
                    RetrievalResult(query=retrieval_query),
                )
                or RetrievalResult(query=retrieval_query)
            )
            trace.add_step(
                "retrieval",
                "result",
                detail={
                    "citations": len(retrieval.citations),
                    "matched_drugs": retrieval.matched_drugs,
                },
            )
            yield _stage("retrieval", "检索资料与说明书")

            # ---------------- 生成 ----------------
            memory_text = (
                format_memory_for_prompt(memory_ctx)
                if memory_ctx
                else self._format_basic_profile(merged_profile)
            )
            profile_hint = ""
            if not merged_profile.get("allergies") and not merged_profile.get("age"):
                profile_hint = "用户档案不完整：可提醒补充过敏史与年龄，但不要反复追问，也不要假设病史。"

            system_prompt = build_system_prompt(
                memory_text=memory_text,
                retrieval_text=retrieval.context_text,
                triage_note=triage_result.note,
                profile_hint=profile_hint,
            )
            messages: List[Dict] = [{"role": "system", "content": system_prompt}]
            if history:
                messages.extend(history[-settings.AGENT_HISTORY_TURNS :])
            messages.append({"role": "user", "content": user_message})

            answer = ""
            fallback_text = ""
            try:
                fallback_text = (
                    self.agent._fallback(
                        db,
                        user_message,
                        answer_to=answer_to,
                        symptom_hint=triage_result.symptoms,
                        context_text=triage_result.context_text,
                    )
                    or {}
                ).get("message") or ""
            except Exception:  # noqa: BLE001
                fallback_text = ""

            if not self.agent.enabled or not getattr(self.agent, "client", None):
                trace.add_step("leader", "rule_fallback", detail={"reason": "未配置 LLM"})
                answer = fallback_text
                yield _stage("generation", "本地规则模式")
            else:
                yield _stage("generation", "生成建议", "running")
                async for event in self._generate(
                    db, messages, route, trace, user_id, fallback_text=fallback_text
                ):
                    if event["type"] == "status":
                        yield {"type": "status", "text": event["text"]}
                    elif event["type"] == "answer":
                        answer = event["text"]
                yield _stage("generation", "生成建议")

            if not answer.strip():
                answer = "抱歉，我暂时没能生成合适的回答。可以换个问法，或直接描述症状与持续时间。"

            # ---------------- 安全 Worker（输出护栏） ----------------
            yield _stage("guardrail", "安全复核", "running")
            ctx = GuardrailContext(
                user_text=user_message,
                profile=merged_profile,
                otc_drug_names=retrieval.otc_drug_names,
                rx_drug_names=retrieval.rx_drug_names,
                citations=retrieval.citations,
                screen=screen,
            )
            guard = guard_output(answer, ctx)
            initial_blocked = guard.blocked
            initial_issues = list(guard.issues)

            if guard.blocked and self.agent.enabled:
                for _attempt in range(max(0, settings.AGENT_GUARDRAIL_MAX_RETRIES)):
                    yield {"type": "status", "text": "检测到表述风险，正在按医疗边界重写…"}
                    regenerated = await self._regenerate(messages, answer, guard.issues, route)
                    if not regenerated:
                        break
                    reguard = guard_output(regenerated, ctx)
                    answer, guard = reguard.answer, reguard
                    trace.add_step(
                        "guardrail",
                        "regenerate",
                        detail={"blocked": reguard.blocked, "issues": [i.code for i in reguard.issues]},
                    )
                    if not reguard.blocked:
                        break

            if guard.blocked:
                answer = build_fallback_answer(ctx, guard.issues)
                guard = guard_output(answer, ctx)
                trace.add_step(
                    "guardrail",
                    "blocked_fallback",
                    detail={"issues": [i.code for i in guard.issues]},
                )

            interaction_severity = self._interaction_severity(trace.tool_calls)
            risk_level = assess_risk(screen, merged_profile, guard.issues, interaction_severity)
            trace.risk_level = risk_level

            final_answer = _append_citations(guard.answer, retrieval.citations)
            final_answer, _ = ensure_disclaimer(final_answer)
            guardrail_payload = guard.to_dict()
            guardrail_payload.update(
                {
                    "initial_blocked": initial_blocked,
                    "rewritten": initial_blocked and not guard.blocked,
                    "initial_issues": [issue.to_dict() for issue in initial_issues],
                }
            )
            trace.add_step("guardrail", "output_check", detail=guardrail_payload)
            yield _stage("guardrail", "安全复核")

            # ---------------- 记忆写入：待确认建议 ----------------
            suggestions: List[Dict] = []
            if settings.AGENT_MEMORY_ENABLED and user_id:
                suggestions = (
                    self._safe(
                        trace,
                        "memory",
                        "extract_facts",
                        lambda: MemoryService.suggest_from_message(
                            db, user_id, session_id, user_message
                        ),
                        [],
                    )
                    or []
                )

            trace_id = trace.finish(
                final_answer,
                status="blocked" if (initial_blocked or guard.blocked) else "ok",
                citations=retrieval.citations,
                guardrail=guardrail_payload,
            )

            # ---------------- 输出事件 ----------------
            meta = risk_meta(risk_level)
            reasons = list(screen.reasons)
            reasons.extend(issue.message for issue in guard.issues if issue.severity in ("high", "medium"))
            if guard.blocked:
                reasons.append("原回答触发医疗安全规则，已替换为安全表述")
            yield {
                "type": "risk",
                "level": risk_level,
                "label": meta["label"],
                "advice": meta["advice"],
                "reasons": list(dict.fromkeys(reasons))[:5],
            }

            if retrieval.citations:
                yield {"type": "citations", "items": _public_citations(retrieval.citations)}

            if suggestions:
                yield {"type": "memory_suggestions", "items": suggestions}

            async for chunk in self._chunk_text(final_answer):
                yield {"type": "token", "text": chunk}

            yield self._done_event(
                trace_id, route, risk_level, initial_blocked or guard.blocked, session_id, started, intent
            )
        except Exception as exc:  # noqa: BLE001  编排异常降级为安全回答
            answer = (
                "抱歉，这次咨询处理出现了异常，请稍后重试。\n"
                "如果症状紧急（胸痛、呼吸困难、意识改变、严重过敏、大量出血），"
                "请立即拨打 120 或前往急诊。\n\n" + DISCLAIMER
            )
            trace.fail(answer, str(exc))
            yield {"type": "error", "text": f"处理异常：{str(exc)[:200]}"}
            async for chunk in self._chunk_text(answer):
                yield {"type": "token", "text": chunk}
            yield self._done_event(
                trace.trace_id, route, "high", True, session_id, started, intent
            )

    # ------------------------------------------------------------ 生成
    async def _generate(
        self,
        db: Session,
        messages: List[Dict],
        route: RouteDecision,
        trace: TraceRecorder,
        user_id: Optional[str],
        fallback_text: str = "",
    ) -> AsyncIterator[Dict]:
        rounds = max(1, settings.AGENT_MAX_TOOL_ROUNDS)

        def degraded_answer(reason: str) -> str:
            if fallback_text:
                return fallback_text
            return (
                "抱歉，模型服务暂时不可用，请稍后重试。"
                "（可在右上角「模型配置」检查 Key 是否有效。）"
            )

        for round_index in range(rounds):
            start = time.perf_counter()
            try:
                response = await asyncio.to_thread(
                    self._completion, messages, route, getattr(self.agent, "tools", None)
                )
            except Exception as exc:  # noqa: BLE001
                trace.add_step(
                    "leader",
                    f"completion_{round_index + 1}",
                    status="error",
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    detail={"error": str(exc)[:200]},
                )
                yield {"type": "answer", "text": degraded_answer(str(exc))}
                return

            message = response.choices[0].message
            trace.add_step(
                "leader",
                f"completion_{round_index + 1}",
                latency_ms=int((time.perf_counter() - start) * 1000),
                detail={
                    "tool_calls": [call.function.name for call in (message.tool_calls or [])],
                    "has_content": bool(message.content),
                },
            )

            if not message.tool_calls:
                yield {"type": "answer", "text": message.content or degraded_answer("空回答")}
                return

            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield {"type": "status", "text": TOOL_LABELS.get(name, "正在查询…")}
                tool_start = time.perf_counter()
                try:
                    result = self.agent._dispatch_tool(db, name, args, user_id=user_id)
                except Exception as exc:  # noqa: BLE001
                    result = f"工具执行失败：{str(exc)[:160]}"
                latency = int((time.perf_counter() - tool_start) * 1000)
                trace.add_tool_call(name, args, result, latency)
                trace.add_step(
                    "tools",
                    name,
                    latency_ms=latency,
                    detail={"args": args, "result_preview": (result or "")[:240]},
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )

        # 工具轮次用尽：最后不带工具再生成一次
        try:
            response = await asyncio.to_thread(self._completion, messages, route, None)
            yield {"type": "answer", "text": response.choices[0].message.content or degraded_answer("空回答")}
        except Exception as exc:  # noqa: BLE001
            trace.add_step("leader", "final_completion", status="error", detail={"error": str(exc)[:200]})
            yield {"type": "answer", "text": degraded_answer(str(exc))}

    async def _regenerate(
        self,
        messages: List[Dict],
        answer: str,
        issues: List[GuardrailIssue],
        route: RouteDecision,
    ) -> Optional[str]:
        instruction = build_regeneration_instruction(issues)
        regen_messages = list(messages) + [
            {"role": "assistant", "content": answer},
            {"role": "user", "content": instruction},
        ]
        try:
            response = await asyncio.to_thread(self._completion, regen_messages, route, None)
            return (response.choices[0].message.content or "").strip() or None
        except Exception as exc:  # noqa: BLE001
            print(f"[orchestrator] 重生成失败: {exc}")
            return None

    def _completion(
        self,
        messages: List[Dict],
        route: RouteDecision,
        tools: Optional[List[Dict]] = None,
    ):
        kwargs: Dict[str, Any] = {
            "model": route.model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": route.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return self.agent.client.chat.completions.create(**kwargs)

    # ------------------------------------------------------------ 辅助
    @staticmethod
    def _safe(trace: TraceRecorder, worker: str, action: str, func, default=None):
        start = time.perf_counter()
        try:
            result = func()
            trace.add_step(
                worker,
                action,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            return result
        except Exception as exc:  # noqa: BLE001
            trace.add_step(
                worker,
                action,
                status="error",
                latency_ms=int((time.perf_counter() - start) * 1000),
                detail={"error": str(exc)[:200]},
            )
            return default

    @staticmethod
    def _merge_profile(base: Dict, memory_profile: Dict) -> Dict:
        merged = dict(base or {})
        for key, value in (memory_profile or {}).items():
            if value not in (None, "", []):
                merged[key] = value
            elif key not in merged:
                merged[key] = value
        return merged

    @staticmethod
    def _format_basic_profile(profile: Dict) -> str:
        if not profile:
            return "（暂无用户档案，回答时不要假设病史。）"
        lines = []
        if profile.get("age"):
            lines.append(f"- 年龄：{profile['age']}岁")
        if profile.get("gender"):
            lines.append(f"- 性别：{profile['gender']}")
        if profile.get("allergies"):
            lines.append(f"- 过敏史：{'、'.join(profile['allergies'])}")
        if profile.get("chronic_conditions"):
            lines.append(f"- 慢性病：{'、'.join(profile['chronic_conditions'])}")
        if profile.get("special_group"):
            lines.append(f"- 特殊人群：{profile['special_group']}")
        return "\n".join(lines) if lines else "（暂无有效档案信息，回答时不要假设病史。）"

    @staticmethod
    def _interaction_severity(tool_calls: List[Dict]) -> Optional[str]:
        for call in tool_calls:
            if call.get("name") != "check_drug_safety":
                continue
            text = call.get("result_preview") or ""
            if any(word in text for word in ("禁用", "请勿", "避免同服", "高风险")):
                return "high"
            if any(word in text for word in ("慎用", "减量", "咨询医生", "相互作用")):
                return "medium"
        return None

    @staticmethod
    async def _chunk_text(text: str) -> AsyncIterator[str]:
        text = text or ""
        step = 18
        for index in range(0, len(text), step):
            yield text[index : index + step]
            await asyncio.sleep(0)

    @staticmethod
    def _done_event(
        trace_id: str,
        route: RouteDecision,
        risk_level: str,
        guardrail_blocked: bool,
        session_id: Optional[str],
        started: float,
        intent: Optional[str] = None,
    ) -> Dict:
        return {
            "type": "done",
            "trace_id": trace_id,
            "route": route.route,
            "model": route.model,
            "risk_level": risk_level,
            "guardrail_blocked": guardrail_blocked,
            "session_id": session_id,
            "intent": intent,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    # ------------------------------------------------------------ 非流式
    async def run(self, *args, **kwargs) -> Dict:
        """收集流式事件，供非流式接口使用"""
        answer_parts: List[str] = []
        risk: Dict = {}
        citations: List[Dict] = []
        suggestions: List[Dict] = []
        done: Dict = {}
        errors: List[str] = []
        async for event in self.stream(*args, **kwargs):
            event_type = event.get("type")
            if event_type == "token":
                answer_parts.append(event.get("text", ""))
            elif event_type == "risk":
                risk = event
            elif event_type == "citations":
                citations = event.get("items", [])
            elif event_type == "memory_suggestions":
                suggestions = event.get("items", [])
            elif event_type == "done":
                done = event
            elif event_type == "error":
                errors.append(event.get("text", ""))
        return {
            "message": "".join(answer_parts),
            "intent": done.get("intent") or "agent_reply",
            "risk": risk,
            "citations": citations,
            "memory_suggestions": suggestions,
            "trace_id": done.get("trace_id"),
            "route": done.get("route"),
            "model": done.get("model"),
            "risk_level": done.get("risk_level"),
            "guardrail_blocked": done.get("guardrail_blocked"),
            "latency_ms": done.get("latency_ms"),
            "session_id": done.get("session_id"),
            "errors": errors,
        }
