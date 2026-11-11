#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自测：用本地 mock 服务验证 agent.py 的请求形状与 flow.py 的调度逻辑。

不碰网络、不需要真 key。跑法：
    python3 scripts/selftest.py
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import http.server
import socketserver
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIVED = []
TOOLS_OK = True
FAIL_MODE = {"on": False}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        RECEIVED.append({"path": self.path, "body": body,
                         "auth": self.headers.get("Authorization")})
        if FAIL_MODE["on"]:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"code": "not_authorized",
                                                   "message": "not authorized"}}).encode())
            return
        if "tools" in body and not TOOLS_OK:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "tools not supported"}}).encode())
            return
        if "tools" in body:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "finish", "arguments": json.dumps({"summary": "mock 完成"})}}]}
        else:
            msg = {"role": "assistant", "content": json.dumps(
                {"files": {"docs/mock.md": "# mock\n"}, "note": "mock note"}, ensure_ascii=False)}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": msg}]}, ensure_ascii=False).encode())

    def log_message(self, *a):
        pass


def start_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def run_agent(base, plain):
    env = dict(os.environ)
    env.update({
        "OPENAI_BASE_URL": base,
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_MODEL": "deepseek-v4.1-flash-1017",
        "AGENT_TASK": "写个文件",
        "AGENT_CONTEXT": "测试上下文",
        "AGENT_PLAIN": "1" if plain else "0",
        "AGENT_MAX_TURNS": "3",
    })
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent.py")],
                       capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
    return p


def main():
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else "  ← " + str(extra)))
        if not cond:
            ok = False

    srv, port = start_server()
    base = f"http://127.0.0.1:{port}/plan/v3"
    print(f"mock 服务：{base}")

    # 1) tool calling 模式
    print("\n[1] agent.py · tool calling 模式")
    RECEIVED.clear()
    p = run_agent(base, plain=False)
    lines = [l for l in p.stdout.strip().splitlines() if l.strip().startswith("{")]
    payload = json.loads(lines[-1]) if lines else {}
    check("退出码 0", p.returncode == 0, p.stderr[-500:])
    check("summary 来自 finish 工具", payload.get("summary") == "mock 完成", payload)
    check("请求打到 /plan/v3/chat/completions",
          RECEIVED and RECEIVED[0]["path"] == "/plan/v3/chat/completions", RECEIVED[:1])
    check("携带 Authorization Bearer", RECEIVED and RECEIVED[0]["auth"] == "Bearer sk-test")
    check("请求体带 tools", RECEIVED and "tools" in RECEIVED[0]["body"])
    check("model 字段正确", RECEIVED and RECEIVED[0]["body"]["model"] == "deepseek-v4.1-flash-1017")

    # 2) plain 模式
    print("\n[2] agent.py · AGENT_PLAIN=1 降级模式")
    RECEIVED.clear()
    p = run_agent(base, plain=True)
    lines = [l for l in p.stdout.strip().splitlines() if l.strip().startswith("{")]
    payload = json.loads(lines[-1]) if lines else {}
    check("退出码 0", p.returncode == 0, p.stderr[-500:])
    check("写入文件成功", "docs/mock.md" in (payload.get("files") or []), payload)
    check("plain 模式不发 tools", RECEIVED and "tools" not in RECEIVED[0]["body"])
    mockfile = ROOT / "docs" / "mock.md"
    check("文件真的落地了", mockfile.exists())
    if mockfile.exists():
        mockfile.unlink()

    # 3) 401 报错是否说人话
    print("\n[3] agent.py · 401 错误提示")
    FAIL_MODE["on"] = True
    p = run_agent(base, plain=False)
    FAIL_MODE["on"] = False
    check("非 0 退出", p.returncode != 0)
    check("提示里点明站点不匹配", "tokenhub.tencentmaas.com/plan/v3" in p.stderr, p.stderr[-400:])
    check("提示里写明原始返回", "not_authorized" in p.stderr)

    # 4) flow.py 纯逻辑
    print("\n[4] flow.py · 调度逻辑")
    os.environ.setdefault("GITHUB_REPOSITORY", "x/y")
    os.environ.setdefault("GITHUB_TOKEN", "dummy")
    sys.path.insert(0, str(ROOT / "scripts"))
    import flow
    fl = flow.load_yaml("flow.yml")
    order = flow.validate(fl)
    check("节点顺序 = spec/design/code/test/review",
          order == ["spec", "design", "code", "test", "review"], order)

    models = flow.load_yaml("models.yml")["models"]
    for n in fl["nodes"]:
        if n.get("type", "agent") == "agent":
            check(f"节点 {n['id']} 的 model 存在", n.get("model") in models, n.get("model"))

    # 4a) 本轮模型优先于节点模型（备用模型能否生效的关键）
    flow.os.environ["LLM_API_KEY"] = "sk-test"
    alias_node = flow.resolve_model("kimi-k3")
    check("resolve_model 取到 design 用的 kimi-k3", alias_node[0] == "kimi-k3", alias_node[0])
    check("kimi-k3 端点已是 tokenhub",
          alias_node[1]["OPENAI_BASE_URL"] == "https://tokenhub.tencentmaas.com/plan/v3",
          alias_node[1]["OPENAI_BASE_URL"])
    check("key 从 LLM_API_KEY 注入", alias_node[1]["OPENAI_API_KEY"] == "sk-test")

    # 4b) 失败态下 comment_body 说人话
    st = {"status": {i: ("failed" if i == "spec" else "pending") for i in order}, "issue": 1}
    body = flow.comment_body(fl, st, [], "http://x")
    check("失败时指出具体节点", "`spec` 失败" in body, body.splitlines()[0])
    check("失败时给出重跑指引", "重跑" in body)

    # 4c) 面板不再把 failed 说成「已走完」
    # render_page 会写 docs/index.html，先备份再还原，避免测试污染工作区
    page = ROOT / "docs" / "index.html"
    backup = page.read_text(encoding="utf-8") if page.exists() else None
    try:
        flow.render_page(fl, st, "http://x")
        html = page.read_text(encoding="utf-8")
        check("面板未把失败当完成", "流程已走完" not in html)
        check("面板点明失败节点", "spec" in html and "failed" in html)
    finally:
        if backup is None:
            page.unlink(missing_ok=True)
        else:
            page.write_text(backup, encoding="utf-8")

    srv.shutdown()
    print("\n" + ("=" * 50))
    print("全部通过 ✅" if ok else "有失败项 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
