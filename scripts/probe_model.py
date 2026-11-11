#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐字段逼近某个模型别名的 400：不猜，一项一项加，看是哪一项把请求打崩的。

用法：
    LLM_API_KEY=sk-tp-你的key python3 scripts/probe_model.py kimi-k3

也可以直接在 Actions 里跑「probe」工作流（key 用 Secrets，不用落地）。

每个变体只比上一个多一处改动，所以「第一个失败的变体」就是触发它的那个字段。
"""
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOOLS = [{
    "type": "function",
    "function": {
        "name": "finish",
        "description": "任务完成",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]},
    },
}]


def call(url, key, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:600]}
    except Exception as e:
        return 0, {"raw": repr(e)}


def err_of(payload):
    if not isinstance(payload, dict):
        return str(payload)[:200]
    e = payload.get("error") or payload
    if isinstance(e, dict):
        bits = [str(e.get(k)) for k in ("code", "type", "message_zh", "message") if e.get(k)]
        return " / ".join(bits)[:260]
    return str(e)[:260]


def variants(model):
    """(标签, 比上一个多了什么, payload) —— 顺序即递进顺序。"""
    user = [{"role": "user", "content": "只回一个字：ok"}]
    sysmsg = [{"role": "system", "content": "你是助手。"}] + user

    out = []
    p = {"model": model, "messages": user}
    out.append(("A 最小请求", "初始", dict(p)))
    p = dict(p, messages=sysmsg)
    out.append(("B +system", "+ system 消息", dict(p)))
    p = dict(p, temperature=0.2)
    out.append(("C +temperature 0.2", "+ temperature=0.2", dict(p)))
    p = dict(p, max_tokens=64)
    out.append(("D +max_tokens 64", "+ max_tokens", dict(p)))
    p = dict(p, tools=TOOLS)
    out.append(("E +tools", "+ tools（不带 tool_choice）", dict(p)))
    p = dict(p, tool_choice="auto")
    out.append(("F +tool_choice auto", "+ tool_choice=auto（agent.py 现在的形状）", dict(p)))
    p = dict(p, temperature=1.0)
    out.append(("G temperature=1.0", "temperature 0.2 → 1.0", dict(p)))
    p = {k: v for k, v in p.items() if k != "temperature"}
    out.append(("H 去掉 temperature", "- temperature", dict(p)))
    return out


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "models.yml"), encoding="utf-8"))
    alias = sys.argv[1] if len(sys.argv) > 1 else cfg.get("default")
    m = cfg["models"].get(alias)
    if not m:
        print(f"models.yml 里没有别名 {alias!r}，可选：{', '.join(cfg['models'])}")
        return 1
    base = m["base_url"].rstrip("/")
    model = m.get("model", alias)
    key = os.environ.get(m.get("key_env") or "LLM_API_KEY", "").strip()

    print(f"alias    : {alias}")
    print(f"base_url : {base}")
    print(f"model    : {model}")
    print(f"key      : {'已设置 长度 ' + str(len(key)) if key else '❌ 没有设置'}")
    print("=" * 70)
    if not key:
        print("先设置 key：LLM_API_KEY=xxx python3 scripts/probe_model.py " + alias)
        return 1

    url = base + "/chat/completions"
    results = []
    for label, delta, payload in variants(model):
        code, body = call(url, key, payload)
        ok = code == 200
        results.append((label, delta, code, ok, err_of(body) if not ok else ""))
        print(f"[{'✅' if ok else '❌'}] {label}   ({delta})")
        if not ok:
            print(f"      HTTP {code} → {err_of(body)}")
        else:
            msg = (body.get("choices") or [{}])[0].get("message") or {}
            print(f"      回复：{(msg.get('content') or '(空，可能只有 tool_calls)')[:60]}")
    print("=" * 70)

    first_bad = next((r for r in results if not r[3]), None)
    if not first_bad:
        print("全部通过 ✅：这个模型在这里能正常吃 agent.py 的请求形状，400 与请求体无关。")
        return 0
    label, delta, code, _, err = first_bad
    print(f"第一个失败：{label}   （{delta}）")
    print(f"HTTP {code} → {err}")
    idx = results.index(first_bad)
    if idx == 0:
        print("↳ 最小请求就失败：模型名/套餐权限/该 key 未开通这个模型，与请求字段无关。")
    else:
        print(f"↳ 上一个变体「{results[idx-1][0]}」是通的，所以触发点就是：{delta}")
        print("  agent.py 里对应可调项：")
        print("    · tools/tool_choice 不被支持      → 给该节点加 plain: true（不依赖 function calling）")
        print("    · temperature 不被接受            → 把 agent.py 的 temperature 传参化，或换模型")
        print("    · max_tokens 必填/超限            → 直接改 agent.py 默认值")
    return 1


if __name__ == "__main__":
    sys.exit(main())
