# -*- coding: utf-8 -*-
"""
模块 5：全链路 Trace 记录器

每次回答记录：用户输入、工作流、路由与模型、风险判定、工具调用、检索引用、
护栏结果、总耗时；每个 Worker 的步骤单独记录，支持审计回放。
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return str(value)


@dataclass
class TraceStep:
    seq: int
    worker: str
    action: str
    status: str = "ok"
    latency_ms: int = 0
    detail: Dict = field(default_factory=dict)


class TraceRecorder:
    """轻量 trace：内存累积步骤，结束时一次性落库"""

    def __init__(
        self,
        db: Optional[Session] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_input: str = "",
        workflow: str = "medical_consult",
    ):
        self.db = db
        self.trace_id = uuid.uuid4().hex
        self.user_id = user_id
        self.session_id = session_id
        self.user_input = user_input
        self.workflow = workflow
        self.intent: Optional[str] = None
        self.route: Optional[str] = None
        self.model: Optional[str] = None
        self.risk_level: Optional[str] = None
        self.tool_calls: List[Dict] = []
        self.citations: List[Dict] = []
        self.guardrail: Dict = {}
        self.steps: List[TraceStep] = []
        self.started_at = time.perf_counter()
        self.enabled = bool(settings.AGENT_TRACE_ENABLED and db is not None)
        self._finished = False

    @contextmanager
    def step(self, worker: str, action: str, detail: Optional[Dict] = None) -> Iterator[Dict]:
        """记录一个 Worker 步骤的耗时与结果"""
        start = time.perf_counter()
        payload: Dict = dict(detail or {})
        try:
            yield payload
            status = "ok"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            payload["error"] = str(exc)[:200]
            raise
        finally:
            self.add_step(
                worker=worker,
                action=action,
                status=status,
                latency_ms=int((time.perf_counter() - start) * 1000),
                detail=payload,
            )

    def add_step(
        self,
        worker: str,
        action: str,
        status: str = "ok",
        latency_ms: int = 0,
        detail: Optional[Dict] = None,
    ) -> None:
        if not self.enabled:
            return
        self.steps.append(
            TraceStep(
                seq=len(self.steps) + 1,
                worker=worker,
                action=action,
                status=status,
                latency_ms=latency_ms,
                detail=_jsonable(detail or {}),
            )
        )

    def add_tool_call(self, name: str, args: Dict, result: str, latency_ms: int) -> None:
        self.tool_calls.append(
            {
                "name": name,
                "args": _jsonable(args),
                "result_preview": (result or "")[:300],
                "latency_ms": latency_ms,
            }
        )

    def finish(
        self,
        answer: str,
        status: str = "ok",
        citations: Optional[List[Dict]] = None,
        guardrail: Optional[Dict] = None,
    ) -> str:
        """落库并返回 trace_id"""
        if self._finished:
            return self.trace_id
        self._finished = True
        total_ms = int((time.perf_counter() - self.started_at) * 1000)
        if citations is not None:
            self.citations = citations[:8]
        if guardrail is not None:
            self.guardrail = guardrail
        if not self.enabled:
            return self.trace_id
        try:
            self.db.execute(
                text(
                    """INSERT INTO agent_traces
                       (trace_id, user_id, session_id, workflow, intent, route, model,
                        risk_level, user_input, final_answer, total_latency_ms,
                        tool_calls, citations, guardrail, status)
                       VALUES (:trace_id, :user_id, :session_id, :workflow, :intent,
                               :route, :model, :risk_level, :user_input, :final_answer,
                               :latency, :tool_calls, :citations, :guardrail, :status)"""
                ),
                {
                    "trace_id": self.trace_id,
                    "user_id": self.user_id,
                    "session_id": self.session_id,
                    "workflow": self.workflow,
                    "intent": self.intent,
                    "route": self.route,
                    "model": self.model,
                    "risk_level": self.risk_level,
                    "user_input": (self.user_input or "")[:2000],
                    "final_answer": (answer or "")[:8000],
                    "latency": total_ms,
                    "tool_calls": json.dumps(_jsonable(self.tool_calls), ensure_ascii=False),
                    "citations": json.dumps(_jsonable(self.citations), ensure_ascii=False),
                    "guardrail": json.dumps(_jsonable(self.guardrail), ensure_ascii=False),
                    "status": status,
                },
            )
            if self.steps:
                self.db.execute(
                    text(
                        """INSERT INTO agent_trace_steps
                           (trace_id, seq, worker, action, status, latency_ms, detail)
                           VALUES (:trace_id, :seq, :worker, :action, :status,
                                   :latency, :detail)"""
                    ),
                    [
                        {
                            "trace_id": self.trace_id,
                            "seq": item.seq,
                            "worker": item.worker,
                            "action": item.action,
                            "status": item.status,
                            "latency": item.latency_ms,
                            "detail": json.dumps(item.detail, ensure_ascii=False),
                        }
                        for item in self.steps
                    ],
                )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001  审计失败不阻断对话
            print(f"[trace] 写入失败: {exc}")
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return self.trace_id

    def fail(self, answer: str, error: str) -> str:
        self.add_step("orchestrator", "error", status="error", detail={"error": error[:300]})
        return self.finish(answer=answer, status="error")
