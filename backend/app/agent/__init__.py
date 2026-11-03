# -*- coding: utf-8 -*-
"""
Agent 平台公共组件。

模块划分（对应《个人医疗管家Agent功能完善方案》）：
    text          中文分词 / BM25 / 文本工具（RAG 与语义记忆共用）
    guardrails    规则护栏引擎（模块 6：双层校验、风险分级、红线拦截）
    triage        分诊 Worker（模块 2：症状识别、渐进式问诊）
    retrieval     检索 Worker（模块 4：混合检索、Rerank、引用溯源）
    memory        记忆 Worker（模块 1：档案抽取、摘要沉淀、语义记忆）
    trace         全链路 trace 记录（模块 5）
    router        模型路由（模块 8）
    orchestrator  Leader-Worker 编排器（模块 2）
"""
