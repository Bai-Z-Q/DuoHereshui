# -*- coding: utf-8 -*-
"""
LangGraph 编排层（v1.3）

目录结构：
    state.py   图状态定义（只放可序列化的业务数据）
    nodes.py   各 Worker 对应的图节点
    builder.py 状态图与条件边
    runner.py  对外流式入口 + checkpointer

设计原则：
- 图状态只存 dict/list/str/float，运行期依赖（DB Session、Agent、Trace）
  通过 GraphContext 闭包传入，避免 checkpointer 序列化失败；
- 对外事件协议保持不变（stage/status/risk/citations/options/
  memory_suggestions/token/done），前端与旧编排器完全兼容；
- 医疗安全逻辑不在图里重写，节点复用 agent.memory / retrieval / guardrails。
"""
