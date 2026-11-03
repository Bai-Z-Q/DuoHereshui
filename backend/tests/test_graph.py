# -*- coding: utf-8 -*-
"""LangGraph 编排层测试：图结构、急症短路、分诊追问、正常回答事件流"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.trace import TraceRecorder
from app.graph.builder import build_graph
from app.graph.nodes import GraphContext, route_after_screen, route_after_triage
from app.graph.runner import LangGraphRunner


class FakeFunction:
    def __init__(self, name, arguments="{}"):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id, name, arguments="{}"):
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return data


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(choices=[SimpleNamespace(message=response)])


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class FakeAgent:
    enabled = True

    def __init__(self, responses, fallback="本地药品库结果"):
        self.client = FakeClient(responses)
        self.tools = [{"type": "function", "function": {"name": "check_drug_safety"}}]
        self.model = "fake-model"
        self.dispatched = []
        self._fallback_text = fallback

    def _dispatch_tool(self, db, name, args, user_id=None):
        self.dispatched.append((name, args))
        return "「布洛芬」未发现与用户档案冲突。"

    def _fallback(self, db, message, answer_to=None, **kwargs):
        return {"message": self._fallback_text, "intent": "general"}


def _retrieval(db, query):
    from app.agent.retrieval import RetrievalResult

    return RetrievalResult(
        query=query,
        citations=[
            {
                "ref": 1,
                "chunk_id": "kc_1",
                "source_type": "drug_label",
                "source_id": "drug_001",
                "title": "布洛芬",
                "section": "禁忌",
                "snippet": "对本品过敏者禁用。",
                "content": "对本品过敏者禁用。",
                "updated_at": "2026-11-02",
            }
        ],
        otc_drug_names=["布洛芬"],
        rx_drug_names=["阿莫西林"],
        context_text="[S1] 布洛芬·禁忌（药品说明书）",
    )


def _collect(agent, message, profile=None, history=None):
    runner = LangGraphRunner(agent)
    with patch("app.graph.nodes.RetrievalService.retrieve", side_effect=_retrieval):
        async def run():
            events = []
            async for event in runner.stream(
                db=None,
                user_message=message,
                history=history or [],
                profile=profile
                or {"age": 30, "allergies": [], "chronic_conditions": []},
                user_id=None,
                session_id=None,
            ):
                events.append(event)
            return events

        return asyncio.run(run())


def _tokens(events):
    return "".join(e.get("text", "") for e in events if e.get("type") == "token")


def test_graph_has_expected_nodes():
    agent = FakeAgent([])
    trace = TraceRecorder(user_input="test")
    ctx = GraphContext(
        agent=agent,
        db=None,
        trace=trace,
        user_message="test",
        history=[],
        profile={},
        user_id=None,
        session_id=None,
        started_at=0.0,
    )
    graph = build_graph(ctx)
    nodes = set(graph.get_graph().nodes)
    assert {"screen", "emergency", "triage", "clarify", "memory", "retrieval",
            "generate", "guardrail", "finalize"}.issubset(nodes)


def test_route_conditions():
    assert route_after_screen({"screen": {"is_emergency": True}}) == "emergency"
    assert route_after_screen({"screen": {"is_emergency": False}}) == "triage"
    assert route_after_triage({"triage": {"needs_info": True}}) == "clarify"
    assert route_after_triage({"triage": {"needs_info": False}}) == "memory"


def test_emergency_short_circuits():
    agent = FakeAgent([])
    events = _collect(agent, "我突然胸痛，呼吸困难")
    assert agent.client.chat.completions.calls == []
    risk = next(e for e in events if e.get("type") == "risk")
    assert risk["level"] == "critical"
    assert "120" in _tokens(events)
    assert any(e.get("type") == "done" for e in events)


def test_clarify_short_circuits():
    agent = FakeAgent([])
    events = _collect(agent, "我头痛")
    assert agent.client.chat.completions.calls == []
    assert any(e.get("type") == "options" for e in events)
    assert "持续多久" in _tokens(events)


def test_normal_flow_emits_answer_and_citations():
    agent = FakeAgent(
        [FakeMessage(content="可能与紧张性头痛有关，建议就诊排查。可参考布洛芬，按说明书使用。")]
    )
    events = _collect(agent, "我头痛两天了，吃什么药")
    answer = _tokens(events)
    errors = [e.get("text") for e in events if e.get("type") == "error"]
    assert "紧张性头痛" in answer, errors
    assert "不能替代医生" in answer
    assert any(e.get("type") == "citations" for e in events)
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("trace_id")
    assert done.get("route") == "reasoning"


def test_graph_records_trace_and_risk():
    agent = FakeAgent([FakeMessage(content="建议先休息，必要时咨询医生。")])
    events = _collect(agent, "我头痛两天了，吃什么药")
    risk = next(e for e in events if e.get("type") == "risk")
    assert risk["level"] in ("low", "medium", "high", "critical")
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("guardrail_blocked") is False


def test_engine_switch_to_legacy():
    """AGENT_ENGINE=legacy 时仍走内置编排器，事件协议不变"""
    from app.config import settings
    from app.services.agent_service import MedicalAgent

    agent = MedicalAgent()
    old_engine = settings.AGENT_ENGINE
    settings.AGENT_ENGINE = "legacy"
    try:
        async def run():
            events = []
            async for event in agent.stream_events(
                db=None,
                user_message="我头痛",
                history=[],
                user_profile={"age": 30, "allergies": [], "chronic_conditions": []},
                user_id=None,
                session_id=None,
            ):
                events.append(event)
            return events

        events = asyncio.run(run())
        assert any(e.get("type") == "options" for e in events)
        assert "持续多久" in _tokens(events)
    finally:
        settings.AGENT_ENGINE = old_engine
