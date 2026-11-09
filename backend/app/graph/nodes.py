# -*- coding: utf-8 -*-
"""LangGraph 各节点：复用现有分诊 / 记忆 / 检索 / 护栏 / 生成能力"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from langgraph.config import get_stream_writer
from sqlalchemy.orm import Session

from ..agent.guardrails import (
    GuardrailContext,
    RiskScreen,
    assess_risk,
    build_fallback_answer,
    emergency_answer,
    ensure_disclaimer,
    guard_output,
    risk_meta,
    screen_input,
)
from ..agent.memory import MemoryService, format_memory_for_prompt
from ..agent.orchestrator import (
    MedicalOrchestrator,
    _append_citations as append_citations,
    _public_citations as public_citations,
)
from ..agent.prompts import build_system_prompt
from ..agent.retrieval import RetrievalResult, RetrievalService
from ..agent.router import RouteDecision, choose_route
from ..agent.trace import TraceRecorder
from ..agent.triage import (
    TriageResult,
    build_clarifying_answer,
    screen_context,
    triage,
)
from ..config import settings
from ..utils.nlp import NLPProcessor
from .state import GraphState


@dataclass
class GraphContext:
    """一次请求的运行期依赖（不进入图状态，避免被 checkpointer 序列化）"""

    agent: Any
    db: Optional[Session]
    trace: TraceRecorder
    user_message: str
    history: List[Dict]
    profile: Dict
    user_id: Optional[str]
    session_id: Optional[str]
    started_at: float
    answer_to: Optional[str] = None  # 前端选项回传的追问维度


def _emit(event: Dict) -> None:
    try:
        get_stream_writer()(event)
    except Exception:  # noqa: BLE001  非图内调用（单元测试直接调节点）时忽略
        pass


def _stage(stage: str, label: str, status: str = "done") -> Dict:
    return {"type": "stage", "stage": stage, "label": label, "status": status}


def _route(state: GraphState) -> RouteDecision:
    return RouteDecision(**state["route"])


def _risk_event(level: str, reasons: List[str]) -> Dict:
    meta = risk_meta(level)
    return {
        "type": "risk",
        "level": level,
        "label": meta["label"],
        "advice": meta["advice"],
        "reasons": list(dict.fromkeys([item for item in reasons if item]))[:5],
    }


async def _emit_text(text: str) -> None:
    async for chunk in MedicalOrchestrator._chunk_text(text or ""):
        _emit({"type": "token", "text": chunk})


def _emit_done(
    state: GraphState,
    ctx: GraphContext,
    trace_id: str,
    risk_level: str,
    blocked: bool,
) -> None:
    _emit(
        MedicalOrchestrator._done_event(
            trace_id,
            _route(state),
            risk_level,
            blocked,
            ctx.session_id,
            ctx.started_at,
            state.get("intent"),
        )
    )


# ============================================================
# 节点
# ============================================================
async def screen_node(state: GraphState, ctx: GraphContext) -> Dict:
    message = state.get("message") or ""
    history = state.get("history") or []
    # 追问短回答（"今天刚开始"）需结合上一轮症状做安全筛查
    screen = screen_input(screen_context(message, history))
    # 选项回答 / 追问短回答都标记为 triage_answer，绕开「短文本→药品名」误判
    followup_answer = bool(ctx.answer_to) or NLPProcessor.is_triage_answer_only(message)
    intent = "triage_answer" if followup_answer else NLPProcessor.detect_intent(message)
    route = choose_route(
        intent,
        message,
        screen,
        history_len=len(history),
        default_model=getattr(ctx.agent, "model", None),
    )
    ctx.trace.intent = intent
    ctx.trace.route = route.route
    ctx.trace.model = route.model
    ctx.trace.add_step(
        "guardrail",
        "input_screen",
        detail={"level": screen.level, "matched": screen.matched, "route": route.route},
    )
    _emit(_stage("screen", "安全检查"))
    return {"screen": asdict(screen), "intent": intent, "route": asdict(route)}


def route_after_screen(state: GraphState) -> str:
    return "emergency" if (state.get("screen") or {}).get("is_emergency") else "triage"


async def emergency_node(state: GraphState, ctx: GraphContext) -> Dict:
    screen = RiskScreen(**state["screen"])
    answer = emergency_answer(screen, state.get("profile") or {})
    ctx.trace.risk_level = "critical"
    ctx.trace.add_step(
        "orchestrator",
        "graph_emergency",
        detail={"matched": screen.matched, "categories": screen.categories},
    )
    trace_id = ctx.trace.finish(
        answer,
        status="blocked",
        guardrail={"blocked": True, "code": "emergency", "matched": screen.matched},
    )
    _emit(_risk_event("critical", screen.reasons[:4]))
    await _emit_text(answer)
    _emit_done(state, ctx, trace_id, "critical", True)
    return {"answer": answer, "risk_level": "critical", "trace_id": trace_id}


async def triage_node(state: GraphState, ctx: GraphContext) -> Dict:
    screen = RiskScreen(**state["screen"])
    result = triage(
        ctx.user_message,
        ctx.history,
        state.get("profile") or {},
        screen,
        answer_to=ctx.answer_to,
    )
    ctx.trace.add_step(
        "triage",
        "assess",
        detail={
            "symptoms": result.symptoms,
            "urgency": result.urgency,
            "needs_info": result.needs_info,
            "department": result.department,
            "dimension": result.dimension,
            "missing": result.missing,
        },
    )
    _emit(_stage("triage", "分诊判断"))
    return {"triage": asdict(result)}


def route_after_triage(state: GraphState) -> str:
    triage_data = state.get("triage") or {}
    if settings.AGENT_TRIAGE_ENABLED and triage_data.get("needs_info"):
        return "clarify"
    return "memory"


async def clarify_node(state: GraphState, ctx: GraphContext) -> Dict:
    screen = RiskScreen(**state["screen"])
    result = TriageResult(**state["triage"])
    answer = build_clarifying_answer(result)
    risk_level = assess_risk(screen, state.get("profile") or {}, [])
    ctx.trace.risk_level = risk_level
    ctx.trace.add_step("triage", "clarify", detail={"question": result.question})
    trace_id = ctx.trace.finish(
        answer, status="ok", guardrail={"blocked": False, "code": "clarify"}
    )
    _emit(_risk_event(risk_level, screen.reasons[:3]))
    _emit(
        {
            "type": "options",
            "items": [
                {"text": opt, "answer_to": result.dimension}
                for opt in result.options
            ],
        }
    )
    await _emit_text(answer)
    _emit_done(state, ctx, trace_id, risk_level, False)
    return {"answer": answer, "risk_level": risk_level, "trace_id": trace_id}


async def memory_node(state: GraphState, ctx: GraphContext) -> Dict:
    memory: Dict = {}
    if settings.AGENT_MEMORY_ENABLED and state.get("user_id"):
        start = time.perf_counter()
        triage_data = state.get("triage") or {}
        memory_query = triage_data.get("context_text") or ctx.user_message
        try:
            memory = (
                MemoryService.context(
                    ctx.db, state["user_id"], ctx.session_id, memory_query
                )
                or {}
            )
            ctx.trace.add_step(
                "memory",
                "load_context",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            ctx.trace.add_step(
                "memory",
                "load_context",
                status="error",
                latency_ms=int((time.perf_counter() - start) * 1000),
                detail={"error": str(exc)[:180]},
            )
            memory = {}
        _emit(_stage("memory", "加载健康记忆"))

    merged_profile = MedicalOrchestrator._merge_profile(
        state.get("profile") or {}, memory.get("profile") or {}
    )
    return {"memory": memory, "profile": merged_profile}


async def retrieval_node(state: GraphState, ctx: GraphContext) -> Dict:
    start = time.perf_counter()
    # 追问答案场景用分诊合并后的上下文检索（症状+回答），
    # 避免拿"今天刚开始"这种纯回答文本去查药品库/知识库。
    triage_data = state.get("triage") or {}
    symptom_terms = triage_data.get("symptoms") or []
    base_text = triage_data.get("context_text") or ctx.user_message
    # 并入分诊识别出的规范症状名，避免口语描述与科普章节词面脱节
    retrieval_query = " ".join([*symptom_terms, base_text]).strip()
    try:
        retrieval = RetrievalService.retrieve(ctx.db, retrieval_query)
        ctx.trace.add_step(
            "retrieval",
            "hybrid_search",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        ctx.trace.add_step(
            "retrieval",
            "hybrid_search",
            status="error",
            latency_ms=int((time.perf_counter() - start) * 1000),
            detail={"error": str(exc)[:180]},
        )
        retrieval = RetrievalResult(query=retrieval_query)

    ctx.trace.add_step(
        "retrieval",
        "result",
        detail={
            "citations": len(retrieval.citations),
            "matched_drugs": retrieval.matched_drugs,
        },
    )
    _emit(_stage("retrieval", "检索资料与说明书"))
    return {"retrieval": asdict(retrieval)}


async def generate_node(state: GraphState, ctx: GraphContext) -> Dict:
    memory = state.get("memory") or {}
    profile = state.get("profile") or {}
    retrieval = state.get("retrieval") or {}
    triage_data = state.get("triage") or {}
    route = _route(state)

    memory_text = (
        format_memory_for_prompt(memory)
        if memory
        else MedicalOrchestrator._format_basic_profile(profile)
    )
    profile_hint = ""
    if not profile.get("allergies") and not profile.get("age"):
        profile_hint = (
            "用户档案不完整：可提醒补充过敏史与年龄，但不要反复追问，也不要假设病史。"
        )

    system_prompt = build_system_prompt(
        memory_text=memory_text,
        retrieval_text=retrieval.get("context_text", ""),
        triage_note=triage_data.get("note", ""),
        profile_hint=profile_hint,
    )
    messages: List[Dict] = [{"role": "system", "content": system_prompt}]
    history = state.get("history") or []
    if history:
        messages.extend(history[-settings.AGENT_HISTORY_TURNS :])
    messages.append({"role": "user", "content": ctx.user_message})

    fallback_text = ""
    try:
        fallback_text = (
            ctx.agent._fallback(
                ctx.db,
                ctx.user_message,
                answer_to=ctx.answer_to,
                symptom_hint=triage_data.get("symptoms") or [],
                context_text=triage_data.get("context_text"),
            )
            or {}
        ).get("message") or ""
    except Exception:  # noqa: BLE001
        fallback_text = ""

    answer = ""
    if not ctx.agent.enabled or not getattr(ctx.agent, "client", None):
        ctx.trace.add_step("leader", "rule_fallback", detail={"reason": "未配置 LLM"})
        answer = fallback_text
        _emit(_stage("generation", "本地规则模式"))
    else:
        _emit(_stage("generation", "生成建议", "running"))
        helper = MedicalOrchestrator(ctx.agent)
        async for event in helper._generate(
            ctx.db,
            messages,
            route,
            ctx.trace,
            state.get("user_id"),
            fallback_text=fallback_text,
        ):
            if event["type"] == "status":
                _emit({"type": "status", "text": event["text"]})
            elif event["type"] == "answer":
                answer = event["text"]
        _emit(_stage("generation", "生成建议"))

    if not (answer or "").strip():
        answer = "抱歉，我暂时没能生成合适的回答。可以换个问法，或直接描述症状与持续时间。"

    return {"answer": answer, "prompt_messages": messages}


async def guardrail_node(state: GraphState, ctx: GraphContext) -> Dict:
    answer = state.get("answer") or ""
    retrieval = state.get("retrieval") or {}
    profile = state.get("profile") or {}
    screen = RiskScreen(**state["screen"])

    guard_ctx = GuardrailContext(
        user_text=ctx.user_message,
        profile=profile,
        otc_drug_names=retrieval.get("otc_drug_names") or (),
        rx_drug_names=retrieval.get("rx_drug_names") or (),
        citations=retrieval.get("citations") or [],
        screen=screen,
    )
    guard = guard_output(answer, guard_ctx)
    initial_blocked = guard.blocked
    initial_issues = list(guard.issues)

    if guard.blocked and ctx.agent.enabled:
        helper = MedicalOrchestrator(ctx.agent)
        messages = state.get("prompt_messages") or []
        for _attempt in range(max(0, settings.AGENT_GUARDRAIL_MAX_RETRIES)):
            _emit({"type": "status", "text": "检测到表述风险，正在按医疗边界重写…"})
            regenerated = await helper._regenerate(messages, answer, guard.issues, _route(state))
            if not regenerated:
                break
            reguard = guard_output(regenerated, guard_ctx)
            answer, guard = reguard.answer, reguard
            ctx.trace.add_step(
                "guardrail",
                "regenerate",
                detail={"blocked": reguard.blocked, "issues": [i.code for i in reguard.issues]},
            )
            if not reguard.blocked:
                break

    if guard.blocked:
        answer = build_fallback_answer(guard_ctx, guard.issues)
        guard = guard_output(answer, guard_ctx)
        ctx.trace.add_step(
            "guardrail",
            "blocked_fallback",
            detail={"issues": [i.code for i in guard.issues]},
        )

    interaction_severity = MedicalOrchestrator._interaction_severity(ctx.trace.tool_calls)
    risk_level = assess_risk(screen, profile, guard.issues, interaction_severity)
    ctx.trace.risk_level = risk_level

    final_answer = append_citations(
        guard.answer, retrieval.get("citations") or []
    )
    final_answer, _ = ensure_disclaimer(final_answer)

    guardrail_payload = guard.to_dict()
    guardrail_payload.update(
        {
            "initial_blocked": initial_blocked,
            "rewritten": initial_blocked and not guard.blocked,
            "initial_issues": [issue.to_dict() for issue in initial_issues],
        }
    )
    ctx.trace.add_step("guardrail", "output_check", detail=guardrail_payload)
    _emit(_stage("guardrail", "安全复核"))

    reasons = list(screen.reasons)
    reasons.extend(
        issue.message for issue in guard.issues if issue.severity in ("high", "medium")
    )
    if initial_blocked:
        reasons.append("原回答触发医疗安全规则，已替换为安全表述")
    risk_event = _risk_event(risk_level, reasons)

    return {
        "answer": final_answer,
        "guardrail": guardrail_payload,
        "risk_level": risk_level,
        "risk": risk_event,
    }


async def finalize_node(state: GraphState, ctx: GraphContext) -> Dict:
    retrieval = state.get("retrieval") or {}
    citations = retrieval.get("citations") or []
    guardrail = state.get("guardrail") or {}
    blocked = bool(guardrail.get("initial_blocked") or guardrail.get("blocked"))

    suggestions: List[Dict] = []
    if settings.AGENT_MEMORY_ENABLED and state.get("user_id"):
        start = time.perf_counter()
        try:
            suggestions = (
                MemoryService.suggest_from_message(
                    ctx.db,
                    state["user_id"],
                    ctx.session_id,
                    ctx.user_message,
                )
                or []
            )
            ctx.trace.add_step(
                "memory",
                "extract_facts",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            ctx.trace.add_step(
                "memory",
                "extract_facts",
                status="error",
                latency_ms=int((time.perf_counter() - start) * 1000),
                detail={"error": str(exc)[:180]},
            )

    answer = state.get("answer") or ""
    trace_id = ctx.trace.finish(
        answer,
        status="blocked" if blocked else "ok",
        citations=citations,
        guardrail=guardrail,
    )

    _emit(state.get("risk") or _risk_event(state.get("risk_level") or "low", []))
    if citations:
        _emit(
            {
                "type": "citations",
                "items": public_citations(citations),
            }
        )
    if suggestions:
        _emit({"type": "memory_suggestions", "items": suggestions})
    await _emit_text(answer)
    _emit_done(state, ctx, trace_id, state.get("risk_level") or "low", blocked)
    return {
        "trace_id": trace_id,
        "suggestions": suggestions,
        "latency_ms": int((time.perf_counter() - ctx.started_at) * 1000),
    }
