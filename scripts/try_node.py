#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 models.yml 的真实配置单独跑一次 agent.py，验证「这个别名能不能干活」。

不读 state.json、不写 state.json、不碰 flow.yml，也不提交任何东西，所以可以随便跑。

    LLM_API_KEY=sk-tp-xxx python3 scripts/try_node.py kimi-k3
    LLM_API_KEY=... python3 scripts/try_node.py kimi-k3 --task "把 hello 写进 docs/hello.md"

它和 flow.py 走的是同一个 resolve_model()，所以 env（端点 / key / model / temperature）
跟真跑节点完全一致 —— 能过就说明这个别名在流程里也能过。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import flow  # noqa: E402

DEFAULT_TASK = "只调用 finish 工具，summary 里写 ok。不要调用其他工具，也不要改任何文件。"


def main():
    args = sys.argv[1:]
    alias, task, i = "", DEFAULT_TASK, 0
    while i < len(args):
        if args[i] == "--task":
            task = args[i + 1] if i + 1 < len(args) else DEFAULT_TASK
            i += 2
        else:
            alias = alias or args[i]
            i += 1
    if not alias:
        alias = flow.load_yaml("models.yml").get("default")

    name, env = flow.resolve_model(alias)
    print(f"alias : {name}")
    for k in ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_TEMPERATURE"):
        print(f"  {k} = {env[k]}")
    k = env.get("OPENAI_API_KEY", "")
    print(f"  OPENAI_API_KEY = {'已设置 长度 ' + str(len(k)) if k else '❌ 空'}")
    print("=" * 60)

    e = os.environ.copy()
    e.update(env)
    e["AGENT_TASK"] = task
    e["AGENT_CONTEXT"] = "单节点试跑（scripts/try_node.py），只验证这个别名能否正常对话与调用工具"
    e.setdefault("AGENT_MAX_TURNS", "4")

    p = subprocess.run([sys.executable, os.path.join(HERE, "agent.py")],
                       env=e, capture_output=True, text=True, timeout=600)
    print("--- stderr ---")
    print((p.stderr or "").strip()[-4000:])
    print("--- stdout ---")
    print((p.stdout or "").strip()[-2000:])
    print("=" * 60)
    print("exit", p.returncode, "→", "✅ 这个别名能干活" if p.returncode == 0 else "❌ 这个别名跑不起来")
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
