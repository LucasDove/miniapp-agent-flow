#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零第三方依赖的 OpenAI 兼容 Agent（只用标准库 urllib）。

环境变量：
  OPENAI_BASE_URL  兼容端点，必须到 /v1，例如 https://xxx.example.com/v1
  OPENAI_API_KEY   密钥（本地模型可留空）
  OPENAI_MODEL     模型 ID
  AGENT_TASK       本节点要做的具体事
  AGENT_CONTEXT    注入的项目状态与约束
  AGENT_PLAIN      1 = 不用 function calling，改为让模型直接吐 JSON 文件补丁
  AGENT_MAX_TURNS  最多工具轮数，默认 12
  AGENT_ALLOW_CMDS 允许执行的命令前缀，逗号分隔

stdout 最后一行是一个 JSON：{"summary": "...", "files": [...], "log": [...]}
其余全部走 stderr，避免污染结果解析。
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "")
# 不写 = 0.2；写 none/off 则完全不传（个别模型连 temperature 字段都不接受）。
TEMPERATURE = os.environ.get("OPENAI_TEMPERATURE", "0.2").strip()
PLAIN = os.environ.get("AGENT_PLAIN", "0") == "1"
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "12"))
ALLOW = [x.strip() for x in os.environ.get(
    "AGENT_ALLOW_CMDS", "ls,cat,git status,git diff,git log,npm run,npx ,node ,python "
).split(",") if x.strip()]

LOG = []
WRITTEN = []
FORBIDDEN = (".git", ".github", "state.json", "flow.yml", "models.yml", "node_modules")


def log(msg):
    LOG.append(str(msg)[:600])
    print("[agent]", str(msg)[:300], file=sys.stderr)


HINTS = {
    401: "鉴权失败。最常见的原因是 base_url 与 key 不属于同一站点：\n"
         "  · Token Plan 套餐（key 形如 sk-tp-xxx）→ base_url 必须是 https://tokenhub.tencentmaas.com/plan/v3\n"
         "  · 按量计费 LKEAP（key 形如 sk-xxx）→ base_url 必须是 https://api.lkeap.cloud.tencent.com/v1\n"
         "  其次是 Secret 里多带了换行/空格，或 key 已过期被重置。本地跑 scripts/check_model.py 可一次定位。",
    403: "key 有效但没这个模型的权限，去控制台给这个 key 开通对应模型。",
    404: "模型名或路径不对：确认 base_url 是站点根（Token Plan 到 /plan/v3、LKEAP 到 /v1），model 字段拼写与平台一致。",
    429: "限流或额度用尽，等一会儿再试，或在评论里带 [model:别名] 换成备用模型。",
}


def diagnose_401(body, base):
    """401 的两种返回体是不同站点的指纹，据此判断是「站点配错」还是「key 本身有问题」。

    LKEAP        → {"error":{"code":"not_authorized","type":"not_authorized_error"}}
    Token Plan   → {"error":{"code":"401002","type":"authentication_error"}}
    """
    where = base or "(未设置 OPENAI_BASE_URL)"
    if "not_authorized" in body:
        return (f"按量计费 LKEAP 返回的 not_authorized，意思是它不认识这把 key（请求实际打到了 {where}）。\n"
                "  · key 是 sk-tp- 开头 → 那是 Token Plan 的 key，base_url 必须改成 "
                "https://tokenhub.tencentmaas.com/plan/v3\n"
                "  · key 是 sk-xxx 但确实属于 LKEAP → 多半是没开通该模型、没加白名单，或 key 已被重置。")
    if "401002" in body or "authentication_error" in body:
        return (f"Token Plan（{where}）返回的 401002，意思是这把 key 在该站点不存在或签名校验失败。\n"
                "  · key 是 LKEAP 的 sk-xxx → 两套体系不通用，base_url 要么换成 "
                "https://tokenhub.tencentmaas.com/plan/v3 配 Token Plan key，要么换回 LKEAP 端点。\n"
                "  · 粘贴 Secret 时带了换行/空格，或 key 已被重置，也会是这一条。")
    return HINTS[401]


def chat(messages, tools=None):
    if not KEY:
        raise RuntimeError("OPENAI_API_KEY 为空：检查 GitHub Secrets 里的 LLM_API_KEY 是否已配置、"
                           "以及 models.yml 里该别名的 key_env 是否写成 LLM_API_KEY")
    payload = {"model": MODEL, "messages": messages}
    if TEMPERATURE and TEMPERATURE.lower() not in ("none", "off", "-"):
        try:
            payload["temperature"] = float(TEMPERATURE)
        except ValueError:
            raise RuntimeError(
                f"OPENAI_TEMPERATURE={TEMPERATURE!r} 不是数字：检查 models.yml 里该别名的 temperature")
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["choices"][0]["message"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        hint = diagnose_401(body, BASE) if e.code == 401 else HINTS.get(
            e.code, "检查 base_url /v1、key、模型名、是否支持 tools")
        raise RuntimeError(f"HTTP {e.code}（model={MODEL}）→ {hint}\n原始返回：{body}") from e


def safe_path(p):
    p = pathlib.Path(p)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("不允许绝对路径或 .. ：" + str(p))
    if any(part in FORBIDDEN for part in p.parts):
        raise ValueError("不允许改动受保护文件：" + str(p))
    return ROOT / p


def write_file(path, content):
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    WRITTEN.append(str(path))
    return f"已写入 {path}（{len(content)} 字符）"


def run_command(cmd):
    if not any(cmd.strip().startswith(a) for a in ALLOW):
        return "拒绝执行（不在白名单）：" + cmd
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=180)
        return ((p.stdout or "") + (p.stderr or ""))[-3000:] or f"完成，退出码 {p.returncode}"
    except subprocess.TimeoutExpired:
        return "命令超时"


TOOLS = [
    {"type": "function", "function": {
        "name": "write_file", "description": "创建或覆盖项目内的一个文本文件，content 必须是文件完整内容",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "相对仓库根目录的路径"},
            "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_command", "description": "运行一条 shell 命令（受白名单限制）",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "finish", "description": "任务完成时调用，给出给人类看的简短摘要",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]


def execute(name, args):
    if name == "write_file":
        return write_file(args.get("path", ""), args.get("content", ""))
    if name == "run_command":
        return run_command(args.get("cmd", ""))
    if name == "finish":
        return "__FINISH__" + args.get("summary", "")
    return "未知工具：" + name


def parse_plain(text):
    """从可能带 ```json 包裹的回复里抠出 JSON。"""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e < s:
        raise ValueError("模型没有返回 JSON：" + text[:400])
    return json.loads(raw[s:e + 1])


def build_messages():
    system = (
        "你是在 GitHub 仓库里工作的开发 Agent。你会被拆成多个离散节点执行，"
        "每次只看得到注入的状态档案，所以务必把需要留给下一节点的信息写进文件。\n"
        "准则：结论先行；不确定的事不要编；只做本次任务；改文件前先想清楚完整内容；"
        "小程序项目遵守 pages/app.json 的既有结构。\n\n"
        "【项目状态与约束】\n" + os.environ.get("AGENT_CONTEXT", "")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": os.environ.get("AGENT_TASK", "")}]


def run_plain():
    messages = build_messages()
    messages[1]["content"] += (
        "\n\n请只输出一个 JSON 对象（可以包在 ```json 代码块里，但不要有其他文字）：\n"
        '{"files": {"相对路径": "文件完整内容"}, "note": "一句话摘要"}\n'
        "只列出你要新增或修改的文件，没改的不要列。不要输出 Markdown 表格或解释。"
    )
    msg = chat(messages)
    data = parse_plain(msg.get("content") or "")
    for p, c in (data.get("files") or {}).items():
        log(write_file(p, c))
    return data.get("note", "完成")


def run_tools():
    messages = build_messages()
    for turn in range(MAX_TURNS):
        msg = chat(messages, TOOLS)
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or "完成（模型未调用 finish）"
        messages.append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": calls,
        })
        for tc in calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            log(f"turn {turn} → {name}({json.dumps(args, ensure_ascii=False)[:200]})")
            result = execute(name, args)
            if isinstance(result, str) and result.startswith("__FINISH__"):
                return result[len("__FINISH__"):]
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": str(result)[:6000]})
    return "达到最大轮数，已停止（可把 AGENT_MAX_TURNS 调大）"


def main():
    if not BASE or not MODEL:
        raise RuntimeError("缺少 OPENAI_BASE_URL / OPENAI_MODEL，请检查 models.yml")
    log(f"endpoint={BASE} model={MODEL} plain={PLAIN}")
    summary = run_plain() if PLAIN else run_tools()
    print(json.dumps({"summary": summary, "files": WRITTEN, "log": LOG}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AGENT ERROR:", repr(e), file=sys.stderr)
        print(json.dumps({"summary": "❌ " + str(e), "files": WRITTEN, "log": LOG}, ensure_ascii=False))
        sys.exit(1)
