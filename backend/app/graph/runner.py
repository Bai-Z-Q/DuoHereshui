# -*- coding: utf-8 -*-
"""
LangGraph 对外运行器

- 对上层暴露与旧编排器一致的 `stream()` / `run()` 事件协议；
- 使用 InMemorySaver 保存每个 session 的图状态（进程内，重启后清空；
  生产可替换为 PostgresSaver / Redis checkpointer）；
- 图执行异常时返回安全兜底回答并写入 trace，不把异常抛给 SSE。
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, List, Optional

from langgraph.checkpoint.memory import InMemorySaver

from ..agent.orchestrator import MedicalOrchestrator
from ..agent.trace import TraceRecorder
from ..config import settings
from .builder import build_graph
from .nodes import GraphContext

_CHECKPOINTER = InMemorySaver()


class LangGraphRunner:
    """把 LangGraph 状态图包装成现有对话服务需要的事件流"""

    def __init__(self, agent: Any):
        self.agent = agent

    async def stream(
        self,
        db,
        user_message: str,
        history: Optional[List[Dict]] = None,
        profile: Optional[Dict] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        answer_to: Optional[str] = None,
    ) -> AsyncIterator[Dict]:
        trace = TraceRecorder(
            db=db, user_id=user_id, session_id=session_id, user_input=user_message
        )
        ctx = GraphContext(
            agent=self.agent,
            db=db,
            trace=trace,
            user_message=user_message,
            history=history or [],
            profile=profile or {},
            user_id=user_id,
            session_id=session_id,
            answer_to=answer_to,
            started_at=time.perf_counter(),
        )
        graph = build_graph(
            ctx,
            checkpointer=_CHECKPOINTER if settings.AGENT_GRAPH_CHECKPOINTER else None,
        )
        thread_id = session_id or trace.trace_id
        trace.add_step(
            "orchestrator",
            "langgraph_start",
            detail={"engine": "langgraph", "thread_id": thread_id},
        )
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 30,
        }
        state = {
            "message": user_message,
            "history": history or [],
            "profile": profile or {},
            "user_id": user_id,
            "session_id": session_id,
            "answer_to": answer_to,
        }

        try:
            async for event in graph.astream(state, config=config, stream_mode="custom"):
                if isinstance(event, dict):
                    yield event
        except Exception as exc:  # noqa: BLE001  图异常不把栈抛给前端
            answer = (
                "抱歉，这次咨询的编排流程出现了异常，请稍后重试。\n"
                "如果症状紧急（胸痛、呼吸困难、意识改变、严重过敏、大量出血），"
                "请立即拨打 120 或前往急诊。\n\n"
                "⚠️ 以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。"
            )
            trace.fail(answer, str(exc))
            yield {"type": "error", "text": f"编排异常：{str(exc)[:200]}"}
            async for chunk in MedicalOrchestrator._chunk_text(answer):
                yield {"type": "token", "text": chunk}
            yield {
                "type": "done",
                "trace_id": trace.trace_id,
                "route": "safety",
                "model": settings.LLM_MODEL,
                "risk_level": "high",
                "guardrail_blocked": True,
                "session_id": session_id,
                "intent": "agent_reply",
                "latency_ms": int((time.perf_counter() - ctx.started_at) * 1000),
            }

    async def run(self, *args, **kwargs) -> Dict:
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
