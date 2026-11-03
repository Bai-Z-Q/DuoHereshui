# -*- coding: utf-8 -*-
"""LangGraph 状态图构建：screen → triage → memory → retrieval → generate → guardrail → finalize"""
from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from .nodes import (
    GraphContext,
    clarify_node,
    emergency_node,
    finalize_node,
    generate_node,
    guardrail_node,
    memory_node,
    retrieval_node,
    route_after_screen,
    route_after_triage,
    screen_node,
    triage_node,
)
from .state import GraphState


def build_graph(ctx: GraphContext, checkpointer=None):
    """构建并编译状态图；节点通过闭包拿到本次请求的 DB/Agent/Trace"""

    async def screen(state):
        return await screen_node(state, ctx)

    async def emergency(state):
        return await emergency_node(state, ctx)

    async def triage_node_wrapped(state):
        return await triage_node(state, ctx)

    async def clarify(state):
        return await clarify_node(state, ctx)

    async def memory(state):
        return await memory_node(state, ctx)

    async def retrieval(state):
        return await retrieval_node(state, ctx)

    async def generate(state):
        return await generate_node(state, ctx)

    async def guardrail(state):
        return await guardrail_node(state, ctx)

    async def finalize(state):
        return await finalize_node(state, ctx)

    graph = StateGraph(GraphState)
    graph.add_node("screen", screen)
    graph.add_node("emergency", emergency)
    graph.add_node("triage", triage_node_wrapped)
    graph.add_node("clarify", clarify)
    graph.add_node("memory", memory)
    graph.add_node("retrieval", retrieval)
    graph.add_node("generate", generate)
    graph.add_node("guardrail", guardrail)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "screen")
    graph.add_conditional_edges(
        "screen",
        route_after_screen,
        {"emergency": "emergency", "triage": "triage"},
    )
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {"clarify": "clarify", "memory": "memory"},
    )
    graph.add_edge("memory", "retrieval")
    graph.add_edge("retrieval", "generate")
    graph.add_edge("generate", "guardrail")
    graph.add_edge("guardrail", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("emergency", END)
    graph.add_edge("clarify", END)

    return graph.compile(checkpointer=checkpointer)
