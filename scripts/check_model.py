#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型连通性诊断：一次问清楚 base_url 对不对、key 有效吗、模型名存在吗、支持 tools 吗。

用法（key 只走环境变量，不落盘、不写进 git）：
    LLM_API_KEY=sk-tp-你的key python3 scripts/check_model.py

只想测某几个别名：
    LLM_API_KEY=xxx python3 scripts/check_model.py tencent_cloud_ds_1017 kimi-k3
"""
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 两套互不通用的体系，填错一半就是 401
SITES = {
    "tokenhub.tencentmaas.com": ("Token Plan 套餐", "sk-tp-"),
    "api.lkeap.cloud.tencent.com": ("按量计费 LKEAP", "sk-"),
}


def call(url, key, payload=None, method="GET"):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
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
        return str(payload)[:300]
    e = payload.get("error") or payload
    if isinstance(e, dict):
        bits = [str(e.get(k)) for k in ("code", "type", "message_zh", "message") if e.get(k)]
        return " / ".join(bits)[:300]
    return str(e)[:300]


def site_of(base):
    for host, (name, prefix) in SITES.items():
        if host in base:
            return name, prefix
    return "未知站点", ""


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "models.yml"), encoding="utf-8"))
    models = cfg["models"]
    want = sys.argv[1:] or [k for k in models if k != "local"]

    base = next((models[n]["base_url"].rstrip("/") for n in want if n in models), None)
    if not base:
        print("models.yml 里找不到这些别名：", want)
        return 1

    site, expect_prefix = site_of(base)
    key = os.environ.get("LLM_API_KEY", "").strip()

    print(f"base_url : {base}")
    print(f"站点判定 : {site}")
    print(f"key      : {'已设置 长度 ' + str(len(key)) + ' 前缀 ' + key[:8] + '…' if key else '❌ 没有设置 LLM_API_KEY'}")
    if key and expect_prefix and not key.startswith(expect_prefix):
        print(f"           ⚠️ 这个站点的 key 通常以 {expect_prefix} 开头，当前是 {key[:8]}…")
        print("              很可能就是它导致 401 —— 换成该站点配套的 key 再试。")
    print("=" * 66)

    if not key:
        print("先设置 key 再跑：LLM_API_KEY=xxx python3 scripts/check_model.py")
        return 1

    all_ok = True
    for name in want:
        m = models.get(name)
        if not m:
            print(f"[{name}] ⚠️ models.yml 里没有这个别名")
            continue
        mid = m.get("model", name)
        mbase = m["base_url"].rstrip("/")
        body = {
            "model": mid,
            "messages": [{"role": "user", "content": "只回一个字：ok"}],
            "max_tokens": 16,
            "temperature": 0,
            "stream": False,
        }
        code, payload = call(mbase + "/chat/completions", key, body, "POST")
        print(f"[{name}]  model={mid}")
        print(f"    {mbase}/chat/completions")
        if code != 200:
            all_ok = False
            print(f"    ❌ HTTP {code} → {err_of(payload)}")
            msg = json.dumps(payload, ensure_ascii=False)
            if "401002" in msg or "not_authorized" in msg or "unauthorized" in msg:
                print("    ↳ 鉴权失败。检查顺序：① key 与 base_url 是否属于同一站点 "
                      "② Secret 里是否多带了换行 ③ key 是否已过期/被重置")
            elif "20033" in msg or "invalid model" in msg.lower():
                print("    ↳ 模型名不在该套餐清单里，去控制台核对 Model ID（必须全小写）")
            continue
        print("    ✅ 对话成功")

        body2 = dict(body)
        body2["tools"] = [{
            "type": "function",
            "function": {
                "name": "finish",
                "description": "任务完成",
                "parameters": {"type": "object",
                               "properties": {"summary": {"type": "string"}},
                               "required": ["summary"]},
            },
        }]
        code2, payload2 = call(mbase + "/chat/completions", key, body2, "POST")
        if code2 == 200:
            print("    ✅ function calling 支持，flow.yml 用默认模式即可")
        else:
            print(f"    ⚠️ function calling 不支持（HTTP {code2}）→ 给该节点加 plain: true，或设变量 AGENT_PLAIN=1")

    print("=" * 66)
    if all_ok:
        print("全部通过。把同一个 key 填进 GitHub Secret LLM_API_KEY，然后去 Issue 里回一句话重跑。")
        return 0
    print("有失败项，按上面的 ↳ 提示处理；改完 models.yml 记得 commit 推送。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
