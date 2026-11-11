#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DAG 调度引擎：解析事件 -> 推进节点 -> 渲染状态 -> 贴 Issue 评论。

由 .github/workflows/flow.yml 调用。除了 PyYAML 无第三方依赖。
状态唯一真相源是仓库里的 state.json，每次运行读它、写它、提交它。
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MARK = "<!-- flow-bot -->"

APPROVE = re.compile(r"^\s*(/approve|approve|lgtm|ok|通过|可以|没问题|继续|go)\s*[。.!！~]?\s*$", re.I)
MODEL_TAG = re.compile(r"\[model:\s*([\w.\-:]+)\]", re.I)

CLASSDEF = [
    "  classDef done fill:#d1fae5,stroke:#059669,color:#065f46;",
    "  classDef waiting fill:#fef3c7,stroke:#d97706,stroke-width:3px,color:#92400e;",
    "  classDef running fill:#dbeafe,stroke:#2563eb,color:#1e40af;",
    "  classDef pending fill:#f3f4f6,stroke:#9ca3af,color:#6b7280;",
    "  classDef failed fill:#fee2e2,stroke:#dc2626,color:#991b1b;",
]


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def api(method, path, data=None):
    if not TOKEN or not REPO:
        raise RuntimeError("缺少 GITHUB_TOKEN / GITHUB_REPOSITORY")
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r) if r.status != 204 else {}


def create_issue(task):
    title = task.strip().splitlines()[0][:80] if task.strip() else "新任务"
    body = MARK + "\n\n" + task + "\n\n> 在下面回复「通过」或写修改意见，即可驱动流程。"
    issue = api("POST", f"/repos/{REPO}/issues", {"title": title, "body": body, "labels": []})
    return issue["number"]


def post_comment(issue, text):
    api("POST", f"/repos/{REPO}/issues/{issue}/comments", {"body": MARK + "\n" + text})


def load_yaml(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def load_state():
    p = ROOT / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(state):
    state["updated"] = now()
    (ROOT / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate(flow):
    seen = []
    for n in flow["nodes"]:
        for dep in n.get("needs", []) or []:
            if dep not in seen:
                raise ValueError(
                    f"flow.yml 中节点 {n['id']} 的 needs={dep} 必须写在它前面（文件顺序即执行顺序）"
                )
        seen.append(n["id"])
    return seen


def resolve_model(name):
    cfg_all = load_yaml("models.yml")
    name = name or cfg_all.get("default")
    cfg = cfg_all["models"].get(name)
    if not cfg:
        raise ValueError(f"models.yml 里没有模型别名 {name!r}")
    key = os.environ.get(cfg.get("key_env", ""), "") if cfg.get("key_env") else ""
    return name, {
        "OPENAI_BASE_URL": cfg.get("base_url", ""),
        "OPENAI_API_KEY": key,
        "OPENAI_MODEL": cfg.get("model", name),
    }


def run_shell(cmd, env_extra=None):
    env = os.environ.copy()
    env.update(env_extra or {})
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out[-6000:]
    except subprocess.TimeoutExpired:
        return False, "命令超时（15 分钟）"


def run_agent(node, state):
    # 本轮显式选择的模型（Issue 表单 / 评论 [model:xxx] / Run workflow）优先于节点写死的 model，
    # 这样主力模型抽风时可以直接在评论里切到备用别名顶上。
    alias, model_env = resolve_model(state.get("model") or node.get("model"))
    task = node.get("prompt", "")
    if state.get("feedback"):
        task += "\n\n【上一轮手机验收反馈，最高优先级，必须逐条响应】\n" + state["feedback"]
        state["feedback"] = ""

    context = (
        "当前时间：" + now()
        + "\n当前 DAG 节点：" + node["id"] + "（" + node.get("title", "") + "）"
        + "\n任务原始需求：\n" + str(state.get("task", ""))[:4000]
        + "\n节点状态：" + json.dumps(state.get("status", {}), ensure_ascii=False)
        + "\n\n约束：只做本节点的事；不要改 .github/、state.json、flow.yml、models.yml；"
        + "不要编造数据；完成后用 finish 工具给出简短摘要。"
    )
    env = model_env.copy()
    env["AGENT_TASK"] = task
    env["AGENT_CONTEXT"] = context
    env["AGENT_PLAIN"] = "1" if (node.get("plain") or os.environ.get("AGENT_PLAIN") == "1") else "0"
    ok, out = run_shell('"' + sys.executable + '" scripts/agent.py', env)
    payload = None
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and '"summary"' in line:
            try:
                candidate = json.loads(line)
                if isinstance(candidate, dict) and "summary" in candidate:
                    payload = candidate
                    break
            except json.JSONDecodeError:
                continue
    if payload:
        summary = payload.get("summary", "")
        detail = "\n".join(payload.get("log", [])) or out[-3000:]
    else:
        summary, detail = "", out[-4000:]
    if not ok:
        summary = "❌ agent 执行失败：" + summary
    return ok, f"模型：{alias} / {model_env['OPENAI_MODEL']}\n{summary}\n\n<details><summary>执行日志</summary>\n\n```\n{detail[-4000:]}\n```\n</details>"


def run_node(nid, node, state):
    typ = node.get("type", "agent")
    if typ == "agent":
        return run_agent(node, state)
    if typ == "shell":
        return run_shell(node.get("run", "true"))
    return True, "（空节点）"


def mermaid(flow, state):
    lines = ["flowchart LR"]
    for n in flow["nodes"]:
        nid, title = n["id"], n.get("title", n["id"])
        st = state["status"].get(nid, "pending")
        shape = f'{nid}{{"{title}"}}' if n.get("type") == "hitl" else f'{nid}["{title}"]'
        lines.append("  " + shape + ":::" + st)
    for n in flow["nodes"]:
        for dep in n.get("needs", []) or []:
            lines.append(f"  {dep} --> {n['id']}")
    lines.extend(CLASSDEF)
    return "\n".join(lines)


def render_page(flow, state, page_url):
    graph = mermaid(flow, state)
    rows = []
    for n in flow["nodes"]:
        st = state["status"].get(n["id"], "pending")
        icon = {"done": "✅", "waiting": "⏳", "running": "🔵", "pending": "⚪", "failed": "❌"}.get(st, "⚪")
        rows.append(f"<tr><td>{icon}</td><td><code>{n['id']}</code></td><td>{n.get('title','')}</td><td>{st}</td></tr>")
    waiting = next((n for n in flow["nodes"] if state["status"].get(n["id"]) == "waiting"), None)
    failed = next((n for n in flow["nodes"] if state["status"].get(n["id"]) == "failed"), None)
    if waiting:
        ask = waiting.get("ask", "结果可以吗？回复「通过」或写修改意见")
    elif failed:
        ask = f"<b style='color:#b91c1c'>节点 {failed['id']}（{failed.get('title','')}）失败了</b>，流程停在出错处。看下面日志的最后一段，修好后在 Issue 里回复「继续」，我会从出错节点重跑。"
    else:
        ask = "流程已走完 ✅"
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111}
h1{font-size:20px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;padding:8px;text-align:left;font-size:14px}
.card{background:#fffbeb;border:1px solid #fcd34d;border-radius:10px;padding:14px;margin:16px 0}
img{max-width:260px;border:1px solid #ddd;border-radius:8px}code{background:#f3f4f6;padding:2px 5px;border-radius:4px}</style></head><body>
<h1>__TITLE__</h1><p style="color:#6b7280;font-size:13px">更新于 __TIME__ · 手机直接看这张图，去 GitHub Issue 里回复即可推进</p>
<pre class="mermaid">__GRAPH__</pre>
<div class="card"><b>现在等你：</b> __ASK__</div>
<h2>节点状态</h2><table><tr><th></th><th>节点</th><th>名称</th><th>状态</th></tr>__ROWS__</table>
__QR__
<h2>怎么操作</h2><p style="font-size:14px">在 GitHub App 打开本项目 Issue，回复 <code>通过</code> 继续，或直接写修改意见回退重做；<br>
想换模型就在评论里带 <code>[model:kimi-k3]</code> 这种别名。<a href="__ISSUE_URL__">打开 Issue →</a></p>
<script>mermaid.initialize({startOnLoad:true,theme:'default'});</script></body></html>"""
    qr = ""
    if (ROOT / "docs" / "preview-qrcode.jpg").exists():
        qr = '<h2>体验版二维码</h2><img src="preview-qrcode.jpg" alt="预览二维码" onerror="this.style.display=\'none\'">'
    issue_url = f"https://github.com/{REPO}/issues/{state.get('issue', 0)}"
    html = (html.replace("__TITLE__", flow.get("name", "迭代流程"))
                .replace("__TIME__", now())
                .replace("__GRAPH__", graph)
                .replace("__ASK__", ask)
                .replace("__ROWS__", "".join(rows))
                .replace("__QR__", qr)
                .replace("__ISSUE_URL__", issue_url))
    (ROOT / "docs" / "index.html").write_text(html, encoding="utf-8")
    return page_url


def comment_body(flow, state, logs, page_url):
    graph = mermaid(flow, state)
    waiting = next((n for n in flow["nodes"] if state["status"].get(n["id"]) == "waiting"), None)
    if waiting:
        head = f"## ⏳ 现在等你验收：{waiting.get('title', waiting['id'])}\n\n{waiting.get('ask','结果可以吗？回复「通过」或写修改意见')}"
    elif "failed" in state["status"].values():
        bad = next((n['id'] for n in flow["nodes"] if state["status"].get(n['id']) == "failed"), "")
        head = f"## ❌ 节点 `{bad}` 失败，流程停在出错处\n\n看日志最后一段的报错。修好后**在这条 Issue 里回一句话**（比如「重试」），我会从这个节点重跑；带 `[model:ds_1017_raw]` 可以顺便换成备用模型。"
    else:
        head = "## ✅ 本轮流程全部走完"
    log_block = "\n\n".join(logs) if logs else "（本轮无新执行日志）"
    return f"""{head}

### 当前 DAG

```mermaid
{graph}
```

📱 [打开可视化面板]({page_url})

<details><summary>本轮执行日志</summary>

{log_block}

</details>

---
回复 **通过** 继续；直接写修改意见则回退重做；评论里带 `[model:别名]` 可换模型。"""


def head_info():
    """本次实际运行的是哪个 commit。

    点「Re-run」会原封不动重放旧 commit —— 这是「models.yml / flow.yml 改了却没生效」
    最常见的原因，把它写进 Issue 日志，一眼就能看出来。
    """
    sha = os.environ.get("GITHUB_SHA", "")
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
        sha = out or sha
    except Exception:
        pass
    msg = f"🔖 本次运行 commit `{sha or '未知'}`"
    try:
        latest = api("GET", f"/repos/{REPO}/commits/main")["sha"][:7]
    except Exception:
        return msg
    if latest and sha and latest != sha:
        msg += (f"，但 main 最新是 `{latest}` —— **这次跑的是旧代码**。"
                "改了 models.yml/flow.yml 没生效就是这个原因：别点 Re-run，要重新 Run workflow（选 main）。")
    return msg


def main():
    flow = load_yaml("flow.yml")
    order = validate(flow)
    nodes = {n["id"]: n for n in flow["nodes"]}
    event = os.environ.get("FLOW_EVENT", "start")
    task = os.environ.get("FLOW_TASK", "")
    comment = os.environ.get("FLOW_COMMENT", "")
    model = os.environ.get("FLOW_MODEL", "").strip()
    issue = int(os.environ.get("FLOW_ISSUE") or 0)
    page_url = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[-1]}/" if REPO else ""

    state = load_state()
    logs = []
    try:
        logs.append(head_info())
    except Exception:
        pass

    if event == "start":
        if not issue:
            issue = create_issue(task)
        # 手机表单里的「模型」字段：### 模型\ntencent_cloud_ds_1017
        m = re.search(r"###\s*模型\s*\n\s*(\S+)", task)
        chosen = model or (m.group(1) if m else "")
        if chosen and chosen not in load_yaml("models.yml")["models"]:
            chosen = ""  # 表单选了「默认」之类，回落到 models.yml 的 default
        state = {
            "issue": issue,
            "task": task,
            "model": chosen,
            "active": None,
            "feedback": "",
            "status": {i: "pending" for i in order},
            "history": [],
        }
        state["history"].append({"at": now(), "event": "start", "node": "", "text": task[:200]})
    else:
        if not state or not issue:
            print("state.json 为空或缺少 issue 号，请先在 GitHub 上开一个任务 Issue", file=sys.stderr)
            return 0
        active = state.get("active")
        failed = next((i for i in order if state["status"].get(i) == "failed"), None)

        # 有节点失败时：任何一条评论都当作「修好了，重跑」，并从失败节点开始
        if failed:
            if "/stop" in (comment or "").lower():
                post_comment(issue, "已停止本轮。想重新开始时开一个新 Issue。")
                return 0
            mt = MODEL_TAG.search(comment or "")
            if mt:
                state["model"] = mt.group(1)
                comment = MODEL_TAG.sub("", comment).strip()
            state["feedback"] = "" if APPROVE.match(comment or "") else (comment or "")
            for i in order[order.index(failed):]:
                state["status"][i] = "pending"
            state["active"] = None
            state["history"].append({"at": now(), "event": "retry", "node": failed, "text": (comment or "")[:300]})
            logs.append(f"🔁 从失败节点 `{failed}` 重跑。")
        elif not active or state["status"].get(active) != "waiting":
            post_comment(issue, "ℹ️ 当前没有等您拍板的节点，先看看面板上的进度就好。")
            return 0
        else:
            mt = MODEL_TAG.search(comment or "")
            if mt:
                state["model"] = mt.group(1)
                comment = MODEL_TAG.sub("", comment).strip()
            node = nodes[active]
            if APPROVE.match(comment or ""):
                if node.get("on_approve"):
                    ok, out = run_shell(node["on_approve"])
                    logs.append(f"### {active} · 通过后动作\n```\n{out[-2000:]}\n```")
                    if not ok:
                        state["status"][active] = "failed"
                        save_state(state)
                        render_page(flow, state, page_url)
                        post_comment(issue, "❌ 通过后动作执行失败，写一句意见可重跑。")
                        return 0
                state["status"][active] = "done"
                state["feedback"] = ""
                state["history"].append({"at": now(), "event": "approve", "node": active, "text": comment})
            else:
                state["feedback"] = comment
                target = node.get("reject_to") or next(
                    (i for i in reversed(order[: order.index(active)]) if nodes[i].get("type") == "agent"),
                    order[0],
                )
                for i in order[order.index(target):]:
                    state["status"][i] = "pending"
                state["history"].append({"at": now(), "event": "feedback", "node": active, "text": comment[:300]})
                logs.append(f"↩️ 收到反馈，回退到 `{target}` 重做。")
            state["active"] = None

    while True:
        nid = next((i for i in order if state["status"][i] == "pending"), None)
        if nid is None:
            break
        node = nodes[nid]
        if node.get("type") == "hitl":
            state["status"][nid] = "waiting"
            state["active"] = nid
            break
        state["status"][nid] = "running"
        ok, out = run_node(nid, node, state)
        state["status"][nid] = "done" if ok else "failed"
        state["history"].append({"at": now(), "event": "node", "node": nid, "ok": ok})
        logs.append(f"### {nid} · {node.get('title','')}\n\n{out}")
        if not ok:
            break

    save_state(state)
    try:
        render_page(flow, state, page_url)
    except Exception as e:
        print("WARN: 面板渲染失败（不影响流程）：", repr(e), file=sys.stderr)
    try:
        post_comment(state["issue"], comment_body(flow, state, logs, page_url))
    except Exception as e:
        # 通知失败不能让 state.json 提交不了，否则下一轮会失忆
        print("WARN: 评论推送失败（状态仍会提交）：", repr(e), file=sys.stderr)
    print("流程推进完成，当前状态：", json.dumps(state["status"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("FLOW ERROR:", repr(e), file=sys.stderr)
        sys.exit(1)
