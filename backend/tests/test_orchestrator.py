# -*- coding: utf-8 -*-
"""编排器测试：用假 LLM 客户端验证工具循环、护栏重写、急症短路、分诊短路"""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.orchestrator import MedicalOrchestrator
from app.agent.retrieval import RetrievalResult


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
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
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


def _retrieval(db, query, **kwargs):
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
            }
        ],
        otc_drug_names=["布洛芬"],
        rx_drug_names=["阿莫西林"],
        context_text="[S1] 布洛芬·禁忌（药品说明书）",
    )


def _collect(agent, message="我头痛两天了，吃什么药", history=None):
    orchestrator = MedicalOrchestrator(agent)
    with patch("app.agent.orchestrator.RetrievalService.retrieve", side_effect=_retrieval):
        return asyncio.run(runner_for(orchestrator, message, history))


async def runner_for(orchestrator, message, history=None):
    events = []
    async for event in orchestrator.stream(
        db=None,
        user_message=message,
        history=history or [],
        profile={"age": 30, "allergies": [], "chronic_conditions": []},
        user_id=None,
        session_id=None,
    ):
        events.append(event)
    return events


def _answer(events):
    return "".join(e.get("text", "") for e in events if e.get("type") == "token")


def test_tool_loop_then_answer():
    agent = FakeAgent(
        [
            FakeMessage(tool_calls=[FakeToolCall("call_1", "check_drug_safety", '{"drug_name": "布洛芬"}')]),
            FakeMessage(content="布洛芬可用于缓解头痛，成人按说明书服用。"),
        ]
    )
    events = _collect(agent)
    assert agent.dispatched == [("check_drug_safety", {"drug_name": "布洛芬"})]
    assert "布洛芬可用于缓解头痛" in _answer(events)
    assert any(e.get("type") == "done" for e in events)
    assert any(e.get("type") == "citations" for e in events)


def test_guardrail_rewrites_diagnosis_and_rx_recommendation():
    agent = FakeAgent(
        [
            FakeMessage(content="你得了感冒，建议吃阿莫西林，一天两次。"),
            FakeMessage(content="可能与感冒有关，建议就诊排查。如需用药，请咨询医生或药师。"),
        ]
    )
    events = _collect(agent)
    answer = _answer(events)
    assert "你得了感冒" not in answer
    assert "建议吃阿莫西林" not in answer
    assert "不能替代医生" in answer
    done = next(e for e in events if e.get("type") == "done")
    assert done.get("guardrail_blocked") is True


def test_emergency_short_circuits_without_llm():
    agent = FakeAgent([])
    events = _collect(agent, message="我突然胸痛，呼吸困难")
    assert agent.client.chat.completions.calls == []
    assert "120" in _answer(events)
    risk = next(e for e in events if e.get("type") == "risk")
    assert risk["level"] == "critical"


def test_triage_clarify_short_circuits_without_llm():
    agent = FakeAgent([])
    events = _collect(agent, message="我头痛")
    assert agent.client.chat.completions.calls == []
    assert any(e.get("type") == "options" for e in events)
    assert "持续多久" in _answer(events)


def test_llm_failure_falls_back_to_local_rules():
    agent = FakeAgent([RuntimeError("upstream timeout")], fallback="本地药品库：布洛芬可参考。")
    events = _collect(agent)
    assert "本地药品库：布洛芬可参考" in _answer(events)
    assert any(e.get("type") == "done" for e in events)
