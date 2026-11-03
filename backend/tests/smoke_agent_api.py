# -*- coding: utf-8 -*-
"""
Agent 平台端到端冒烟测试（无需 pytest）

用法：
    python backend/tests/smoke_agent_api.py                 # 默认 http://127.0.0.1:8010
    python backend/tests/smoke_agent_api.py --base http://127.0.0.1:8000
    python backend/tests/smoke_agent_api.py --keep          # 保留测试账号，便于巡检

覆盖：注册/档案、流式对话（分诊/急症/普通）、记忆建议与确认、
知识库检索、漏服/周报、指标/trace/反馈、数据导出。
"""
import argparse
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name} {detail}")


def request(
    method: str,
    url: str,
    payload=None,
    token=None,
    expect_json=True,
    timeout=60,
):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not expect_json:
                return resp.status, raw
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url} -> {exc.code}: {body[:400]}")


def stream_chat(base: str, token: str, user_id: str, message: str, session_id=None):
    payload = {"user_id": user_id, "message": message}
    if session_id:
        payload["session_id"] = session_id
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/stream",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    events = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw_line in resp.read().decode("utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                continue
    return events


def summarize_events(events):
    answer = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    risk = next((e for e in events if e.get("type") == "risk"), {})
    done = next((e for e in events if e.get("type") == "done"), {})
    citations = next((e for e in events if e.get("type") == "citations"), {})
    suggestions = next((e for e in events if e.get("type") == "memory_suggestions"), {})
    options = next((e for e in events if e.get("type") == "options"), {})
    stages = [e.get("stage") for e in events if e.get("type") == "stage"]
    return {
        "answer": answer,
        "risk": risk,
        "done": done,
        "citations": citations.get("items", []),
        "suggestions": suggestions.get("items", []),
        "options": options.get("items", []),
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    base = args.base.rstrip("/") + "/api"
    username = f"smoke_agent_{random.randint(10000, 99999)}"
    user_id = None

    print("=" * 64)
    print(f"Agent 平台冒烟测试 @ {base}")
    print("=" * 64)

    # 1. 注册与档案
    status, reg = request("POST", f"{base}/auth/register", {"username": username, "password": "test123456"})
    token = reg["token"]
    user_id = reg["user_id"]
    check("注册返回 token", bool(token))
    status, profile = request(
        "PUT",
        f"{base}/users/me",
        {
            "age": 34,
            "gender": "男",
            "chronic_conditions": ["高血压"],
            "allergies": ["青霉素"],
        },
        token,
    )
    check("档案更新（中文）", "青霉素" in (profile.get("allergies") or []), str(profile.get("allergies")))

    # 2. 分诊追问
    events = stream_chat(base, token, user_id, "我头痛")
    triage = summarize_events(events)
    check("分诊阶段事件", "triage" in triage["stages"], str(triage["stages"]))
    check("渐进式追问问题", any("多久" in opt for opt in triage["options"]) or "多久" in triage["answer"])
    session_id = triage["done"].get("session_id")

    # 2.1 追问上下文：短回答不能被当成药品名，且能继续补齐维度
    events = stream_chat(base, token, user_id, "今天刚开始", session_id)
    follow = summarize_events(events)
    check(
        "追问短回答不被当成药品名",
        "没有在药品库中找到" not in follow["answer"],
        follow["answer"][:120],
    )
    check(
        "追问后继续补齐关键维度",
        ("程度" in follow["answer"]) or ("轻微" in follow["answer"]),
        follow["answer"][:120],
    )

    events = stream_chat(base, token, user_id, "轻微，不影响生活", session_id)
    completed = summarize_events(events)
    check(
        "补齐信息后继承症状回答",
        ("头痛" in completed["answer"] or "布洛芬" in completed["answer"])
        and "没有在药品库中找到" not in completed["answer"],
        completed["answer"][:120],
    )

    # 3. 普通咨询（无有效 LLM 时自动降级到本地药品库）
    events = stream_chat(base, token, user_id, "我头痛两天了，有什么药可以吃？", session_id)
    normal = summarize_events(events)
    check("返回回答", bool(normal["answer"]))
    check("风险分级事件", normal["risk"].get("level") in ("low", "medium", "high", "critical"))
    check("知识库引用", len(normal["citations"]) > 0, str(len(normal["citations"])))
    check("trace 已记录", bool(normal["done"].get("trace_id")))
    trace_id = normal["done"].get("trace_id")

    # 3.1 正式回答后用户主动补充时长：应承接上一症状，而不是把短句当药品名
    events = stream_chat(base, token, user_id, "今天刚开始", session_id)
    supplement = summarize_events(events)
    check(
        "正式回答后的补充承接上一症状",
        "没有在药品库中找到" not in supplement["answer"]
        and ("头痛" in supplement["answer"] or "布洛芬" in supplement["answer"]),
        supplement["answer"][:120],
    )
    if args.verbose:
        print("\n----- 普通咨询回答（节选） -----")
        print(normal["answer"][:600])
        print("----- 风险 -----", normal["risk"])
        print("----- 引用 -----", [c.get("title") for c in normal["citations"]])
        print("-------------------------------\n")

    # 4. 急症硬拦截
    events = stream_chat(base, token, user_id, "我突然胸痛，呼吸困难，吃什么药", session_id)
    emergency = summarize_events(events)
    check("急症风险=critical", emergency["risk"].get("level") == "critical", str(emergency["risk"]))
    check("急症引导 120", "120" in emergency["answer"])

    # 5. 记忆抽取与确认
    events = stream_chat(base, token, user_id, "我对磺胺过敏", session_id)
    memory = summarize_events(events)
    check("产生记忆建议", len(memory["suggestions"]) > 0, str(memory["suggestions"]))
    status, overview = request("GET", f"{base}/memory/overview", token=token)
    pending = overview.get("pending_suggestions") or []
    allergy_suggestion = next((p for p in pending if p["field"] == "allergies"), None)
    check("待确认列表含过敏史", allergy_suggestion is not None)
    if allergy_suggestion:
        status, applied = request(
            "POST",
            f"{base}/memory/suggestions/{allergy_suggestion['suggestion_id']}/accept",
            {},
            token,
        )
        check("确认写入档案", applied.get("applied") is True, str(applied))
        status, profile = request("GET", f"{base}/users/me", token=token)
        check("档案新增磺胺", "磺胺" in (profile.get("allergies") or []), str(profile.get("allergies")))

    # 6. 照护对象 + 当前用药建议
    events = stream_chat(base, token, user_id, "我妈妈有高血压，最近在吃氨氯地平", session_id)
    care_memory = summarize_events(events)
    fields = {item["field"] for item in care_memory["suggestions"]}
    check("识别照护对象或当前用药", bool(fields & {"care_context", "current_medication"}), str(fields))

    # 7. 语义记忆检索
    status, search = request(
        "GET", f"{base}/memory/search?q={urllib.parse.quote('头痛')}&top_k=5", token=token
    )
    check("语义记忆可召回", len(search.get("items") or []) > 0)

    # 8. 知识库
    status, kb = request(
        "GET", f"{base}/knowledge/search?q={urllib.parse.quote('布洛芬的禁忌')}&top_k=3", token=token
    )
    check("知识库检索命中说明书", any(r["source_type"] == "drug_label" for r in kb.get("results", [])))
    status, kb_stats = request("GET", f"{base}/knowledge/stats", token=token)
    check("知识库索引已构建", kb_stats.get("total_chunks", 0) > 0, str(kb_stats))

    # 9. 漏服 / 周报
    status, drugs = request(
        "GET", f"{base}/drugs/search/?keyword={urllib.parse.quote('布洛芬')}&limit=1", token=token
    )
    check("药品搜索可用", bool(drugs))
    if drugs:
        today = date.today().isoformat()
        status, created = request(
            "POST",
            f"{base}/medications",
            {
                "drug_id": drugs[0]["drug_id"],
                "start_date": today,
                "dosage": "一次1片",
                "frequency": "每日3次",
                "reminder_times": "00:01",
                "notes": "smoke test",
            },
            token,
        )
        check("用药记录创建", bool(created.get("medication_id")), str(created))
        med_id = created.get("medication_id")
        if med_id:
            status, updated = request(
                "PUT",
                f"{base}/medications/{med_id}",
                {
                    "dosage": "一次2片",
                    "frequency": "每日2次",
                    "reminder_times": "08:00,20:00",
                    "notes": "smoke update",
                },
                token,
            )
            check(
                "用药记录可修改",
                updated.get("dosage") == "一次2片"
                and updated.get("frequency") == "每日2次"
                and updated.get("reminder_times") == "08:00,20:00",
                str(updated),
            )
            status, off = request(
                "PUT", f"{base}/medications/{med_id}", {"is_active": False}, token
            )
            check("用药记录可停用", off.get("is_active") is False, str(off))
            status, on = request(
                "PUT", f"{base}/medications/{med_id}", {"is_active": True}, token
            )
            check("用药记录可重新启用", on.get("is_active") is True, str(on))

        status, care = request("GET", f"{base}/care/dashboard", token=token)
        check("漏服检测命中", len(care.get("missed_doses") or []) > 0, str(care.get("missed_doses")))
        missed_item = (care.get("missed_doses") or [None])[0]
        if missed_item:
            request(
                "POST",
                f"{base}/medications/logs",
                {
                    "medication_id": missed_item["medication_id"],
                    "scheduled_time": missed_item["scheduled_time"],
                    "status": "taken",
                },
                token,
            )
            status, care_after = request("GET", f"{base}/care/dashboard", token=token)
            check("补服后不再提示漏服", len(care_after.get("missed_doses") or []) == 0)
    else:
        status, care = request("GET", f"{base}/care/dashboard", token=token)
    check("主动能力看板", "missed_doses" in care and "adherence" in care)

    status, sub = request(
        "POST", f"{base}/care/subscription", {"is_active": True, "channel": "in_app"}, token
    )
    check("药品警示订阅", sub.get("is_active") is True)

    status, report = request("GET", f"{base}/care/weekly-report?days=7", token=token)
    check("周报生成", "用药周报" in (report.get("markdown") or ""))

    # 10. 指标 / trace / 反馈
    status, metrics = request("GET", f"{base}/observability/metrics?days=7", token=token)
    check("指标含高风险统计", "emergency" in metrics and "guardrail" in metrics)
    check("指标含反馈率", "feedback" in metrics)
    status, traces = request("GET", f"{base}/observability/traces?limit=10", token=token)
    check("trace 列表", len(traces.get("items") or []) > 0)
    if trace_id:
        status, trace = request("GET", f"{base}/observability/traces/{trace_id}", token=token)
        check("审计回放步骤", len(trace.get("steps") or []) >= 3, str(len(trace.get("steps") or [])))
        status, fb = request(
            "POST",
            f"{base}/feedback",
            {"trace_id": trace_id, "rating": "up", "reason": "helpful"},
            token,
        )
        check("反馈落库", fb.get("rating") == "up", str(fb))

    # 11. 导出
    status, exported = request("GET", f"{base}/export/my-data?format=json", token=token)
    check("导出含档案与记忆", bool(exported.get("profile")) and "memories" in exported)
    status, md = request("GET", f"{base}/export/my-data?format=markdown", token=token, expect_json=False)
    check("Markdown 导出", "个人健康数据导出" in md)

    # 12. 会话与历史
    status, sessions = request("GET", f"{base}/chat/sessions/{user_id}", token=token)
    check("会话列表", len(sessions.get("sessions") or []) > 0)
    if session_id:
        status, history = request(
            "GET", f"{base}/chat/history/{user_id}?session_id={session_id}", token=token
        )
        assistant_msgs = [m for m in history.get("history", []) if m["role"] == "assistant"]
        check("历史消息含元数据", bool(assistant_msgs) and bool(assistant_msgs[-1].get("metadata")), str(assistant_msgs[-1].get("metadata") if assistant_msgs else None))

    print("\n" + "=" * 64)
    print(f"结果：{len(PASSED)} 通过，{len(FAILED)} 失败")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print(f"  - {name}")
    print("=" * 64)

    if not args.keep:
        try:
            sys.path.insert(0, str(__file__).rsplit("backend", 1)[0] + "database")
            import psycopg2
            from db_config import db_config

            conn = psycopg2.connect(**db_config())
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("DELETE FROM answer_feedback WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM agent_trace_steps WHERE trace_id IN (SELECT trace_id FROM agent_traces WHERE user_id = %s)", (user_id,))
            cur.execute("DELETE FROM agent_traces WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
            cur.close()
            conn.close()
            print(f"已清理测试账号：{username}")
        except Exception as exc:  # noqa: BLE001
            print(f"清理测试账号失败（可手动删除 {username}）：{exc}")
    else:
        print(f"测试账号保留：{username} / {user_id}")

    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
