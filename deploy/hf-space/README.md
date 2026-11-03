---
title: Duohereshui
emoji: 🩺
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# 多喝热水 · 个人医疗管家

FastAPI + LangGraph + PostgreSQL 的个人健康信息助手。

- 症状咨询与 OTC 药品参考
- 分诊追问、上下文记忆
- 药品说明书 / 健康科普 RAG 引用
- 医疗安全护栏与审计回放
- 用药打卡、漏服检测、周报

## 配置

在 Space 的 **Settings → Variables and secrets** 中添加：

- `DATABASE_URL`（secret）：Neon Direct connection，必须带 `?sslmode=require`
- `SECRET_KEY`（secret）：随机长字符串
- `LLM_API_KEY`（secret，可选）
- `PGSSLMODE=require`
- `TZ=Asia/Shanghai`
- `PGTZ=Asia/Shanghai`
- `AGENT_ENGINE=langgraph`
- `REGISTRATION_ENABLED=true`（创建账号后改为 false）
- `ALLOW_LLM_SETTINGS=false`

首次启动会自动建表、导入种子数据并执行迁移。

> 本项目仅供健康信息参考，不能替代医生诊断。请勿在公开 Demo 中存放真实健康数据。
