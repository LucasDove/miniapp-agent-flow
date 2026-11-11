# 需求清单：连通性冒烟（spec 节点产出）

> 结论先行：本次只新建 **一个** 文件 `docs/smoke.md`，内容一行 `smoke ok <UTC 时间>`。除此之外不改任何文件、不跑任何构建、不动小程序源码。本节点只出清单，不写实现。

## 0. 事实核对（读仓库后确认，不猜）

- 仓库根目录实际内容：`README.md`、`docs/`、`flow.yml`、`models.yml`、`requirements.txt`、`scripts/`、`state.json`。
- **当前仓库里没有 `pages/`、`app.json`、`app.js`、`app.wxss`**（这是调度器/工作流仓库，不是小程序源码仓库）。所以「不改小程序源码」在本仓库的实际含义是：除新建 `docs/smoke.md` 外，**任何已存在文件零改动**。若后续节点发现 `pages/` 等目录存在，同样视为禁止改动对象。
- `docs/` 目录已存在，内含 `index.html`（机器人自动重绘的页面，**禁止改动**）。

## 1. 要改哪些文件（白名单，仅此两项）

| 文件 | 动作 | 内容要求 |
|---|---|---|
| `docs/smoke.md` | **新建** | 只有一行文本：`smoke ok <UTC 时间>`，行尾一个换行，**无标题、无空行、无代码块包裹** |
| `docs/spec.md` | 本节点（spec）已写入 | 本清单本身；code/review 节点只读不改 |

时间格式（严格）：`YYYY-MM-DDTHH:MM:SSZ`，例如 `2026-11-11T04:16:00Z`。
取值规则：优先用能拿到的真实 UTC 时间；若执行环境命令白名单不允许 `date`，则使用需求注入的当前时间 `2026-11-11T04:16:00Z`，**不得**编造与注入时间明显不符的值。

即最终文件内容形如（举例）：

```
smoke ok 2026-11-11T04:16:00Z
```

**不涉及任何页面/组件改动**（本次无 UI 变更，故「要改哪些页面/组件」一栏为：无）。

## 2. 验收标准（可一条命令确认，不需要看手机）

本次是纯连通性冒烟，验收不依赖真机/开发者工具，标准如下：

1. `docs/smoke.md` 存在，且 `wc -l` 结果为 1（恰好一行）。
2. 内容匹配正则 `^smoke ok \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`（zsh/grep -E 写法：`grep -Eq '^smoke ok [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' docs/smoke.md`）。
3. `git status --short` 只出现：`?? docs/smoke.md`（以及本节点新增的 `?? docs/spec.md`）；**没有任何 modified/deleted 条目**。
4. 文件里没有 Markdown 标题、没有多余空行、没有中文标点、没有尾部空格。
5. 手机端可见性（等价的「一眼看出」替代）：本次不产出 UI，验证方式是从仓库文件页直接打开 `docs/smoke.md`，看到且只看到那一行 `smoke ok …`。

## 3. 明确不做什么（禁止清单）

- 不改 `pages/`、`app.json`、`app.js`、`app.wxss` 及任何小程序源码/配置（当前仓库也不存在这些路径，**不要新建它们**）。
- 不改 `flow.yml`、`models.yml`、`state.json`、`.github/` 下任何文件。
- 不改 `scripts/`（含 `flow.py`、`agent.py`、`check_model.py`、`preview.js`、`upload.js`）。
- 不改 `docs/index.html`、`README.md`，不新增 `docs/` 下的其他文件。
- 不跑 `git commit` / `git push` / `git add`、不建分支、不发评论（提交由调度器负责）。
- 不做「额外的」冒烟：不装依赖、不跑 `scripts/check_model.py`、不触发 workflow、不生成二维码、不构建。
- 不写多行内容、不写说明文字、不留 TODO、不在文件里写时间以外的任何东西。

## 4. 交接给下一节点（code）

- 只做一件事：`write_file docs/smoke.md`，内容为 `smoke ok 2026-11-11T04:16:00Z`（若拿到真实 UTC 时间则替换时间戳）。
- 完成后不要自行校验改动范围以外的文件；由 test/review 节点按第 2 节逐条核对。
