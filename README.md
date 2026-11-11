# 一句话提需求、手机验收、DAG 可见的小程序开发流

你只需要做两件事：**开一个 Issue 说要做什么**，以及**在手机上回复「通过」或写修改意见**。
Git、上下文、多机同步、状态持久化全部由仓库和 GitHub Actions 自动完成，你一次都不用手敲。

```
手机开 Issue ──> Actions 按 flow.yml 跑节点 ──> 自动 commit + 重绘 DAG ──> 推一条评论到手机
     ▲                                                                        │
     └────────── 回复「通过」/ 写意见 ──> issue_comment 触发下一轮 ─────────────┘
```

---

## 一、10 分钟装好（只做一次）

### 1. 建仓库
新建一个 **Public** 仓库（公有仓库 Actions 分钟数不计费，Pages 也最省事；私有仓库也能用，见文末注意），把本目录所有文件推上去：

```bash
cd mini-agent-flow
git init && git add -A && git commit -m "init flow"
git remote add origin https://github.com/<你>/<仓库>.git
git push -u origin main
```

### 2. 配一个 Secret
`Settings → Secrets and variables → Actions → New repository secret`

| 名字 | 值 |
|---|---|
| `LLM_API_KEY` | 你自己的 OpenAI 兼容 API 密钥 |

（可选）`Settings → Secrets and variables → Actions → Variables` 里加 `AGENT_PLAIN=1`，仅当你的模型**不支持 function calling** 时。

### 3. 把模型改成你自己的
编辑根目录 **`models.yml`**，只改 `base_url` 和 `model` 两处：

```yaml
fast:
  base_url: https://你的服务.example.com/v1     # 必须以 /v1 结尾
  model: 你的模型ID
  key_env: LLM_API_KEY
```

> 三个别名 `fast / strong / local` 分别给「拆解」「写代码」「本地模型」用，可以在 `flow.yml` 里给每个节点单独指定。

### 4. 打开可视化面板（可选但推荐）
`Settings → Pages → Build and deployment → Source` 选 **GitHub Actions**。

⚠️ **不要选「Deploy from a branch / docs」**：用 `GITHUB_TOKEN` 推送的提交不会触发 Pages 重新构建，面板会永远停在第一次的样子。workflow 里已经走 artifact 部署，所以发布源必须选 GitHub Actions。

再到 `Settings → Secrets and variables → Actions → Variables` 加一条：

| 名字 | 值 |
|---|---|
| `ENABLE_PAGES` | `1` |

一分钟后手机固定访问：

```
https://<你的用户名>.github.io/<仓库名>/
```

面板上是自动重绘的 Mermaid DAG：绿色完成、黄色等你拍板、灰色未开始。不开 Pages 也行（不加这个变量即可）——每条 Issue 评论里同样带这张图。

### 5. 手机装 GitHub App，登录，试跑
在 App 里 `Issues → New issue → 派一个活`，填一句需求，例如：

> 把「我的」页的头像改成圆形，加 44px 最小点击区，不要动其他页面。

提交后去 `Actions` 页能看到 `flow` 在跑。跑完手机会收到一条带 DAG 图和日志的评论，停在「手机验收」节点等你。

---

## 二、日常就这三步

| 时机 | 你做什么 |
|---|---|
| 通勤/摸鱼 | 手机开 Issue 说要做什么，或直接评论 `[model:strong] 把列表页加下拉刷新` |
| 收到通知 | 点开评论看 DAG + 日志，或打开面板网页 |
| 拍板 | 回复 **`通过`** → 继续往下；**直接写意见**（如「按钮太小，改 44px」）→ 自动回退到写代码节点重做 |

评论里带 `[model:别名]` 可给本轮临时换模型；不写就沿用 `flow.yml` 里节点指定的模型。

**一次只跑一条流**（`concurrency: agent-flow` 已保证排队），别同时开两个任务 Issue。

---

## 三、自定义你的 DAG

只改根目录 **`flow.yml`**，按执行顺序从上往下写，`needs` 只用来画连线（必须指向前面已出现的节点）。

| 字段 | 说明 |
|---|---|
| `type: agent` | 调模型干活，配 `prompt` + `model` |
| `type: shell` | 跑命令，配 `run`（构建、lint、上传等） |
| `type: hitl` | **停下来等你**，配 `ask` |
| `needs: [x]` | 图上的依赖连线 |
| `reject_to: code` | 你写修改意见时回退到哪个节点重做（默认回退到前面最近的 agent 节点） |
| `on_approve: <命令>` | 你回复「通过」时顺带执行的动作（例如上传体验版） |
| `plain: true` | 该节点不用 function calling，改用 JSON 文件补丁模式 |

例子：想加一个「生成 changelog」节点，插到 `test` 后面就行：

```yaml
  - id: changelog
    title: 生成更新说明
    type: agent
    model: fast
    needs: [test]
    prompt: 根据本次 git diff 写一段给用户看的更新说明，写入 docs/CHANGELOG.md
```

> 设计建议：**job 边界 = 验收边界，不是推理步边界**。别把「读文件 / 调模型 / 改代码」各拆成一个节点；让一个 agent 节点内部跑完整的 plan→execute→observe 循环，跑完才交给你验收，冷启动只付一次。

---

## 四、机器与账单（三个独立开关）

**1. 在哪台机器跑**

默认 `runs-on: ubuntu-latest`（GitHub 托管 runner，远端，你两台电脑关机也照跑）。
想用自己电脑，在 `Actions → flow → Run workflow` 里把 `runs_on` 选成 `self-hosted`，注册一次即可：

```bash
# 仓库 Settings → Actions → Runners → New self-hosted runner，按页面给的命令执行
./config.sh --url https://github.com/<你>/<仓库> --token <页面给的token>
./run.sh          # 建议配成开机自启的服务
```

什么时候必须用本地 runner：你的模型是 `http://127.0.0.1:11434/v1` 这种 Ollama / LM Studio，或节点要碰本机微信开发者工具。托管 runner 够不着你内网。

> ⚠️ **别把 self-hosted runner 挂到公有仓库上**：别人一个 fork 的 PR 就可能在你机器上执行代码。要用本地 runner，请换成私有仓库，并确保仓库不接受外部 fork PR。

**2. 烧谁的钱**

| 项目 | 谁出 |
|---|---|
| CPU 分钟 | 公有仓库免费；私有仓库每月 2000 分钟免费额度；self-hosted runner 不消耗额度、GitHub 不收分钟费 |
| LLM token | **完全取决于 `models.yml` 里的 base_url**——指你自己的 API 就烧你自己账号，指本机 Ollama 就只烧电 |
| 产物/存储 | Artifacts、Pages 免费额度内 0 元 |

GitHub 只是跑脚本，不经手推理、不加价。WorkBuddy 完全不在这条链路里，不烧它积分。

> 提醒：GitHub 曾宣布对 self-hosted runner 收 $0.002/min 平台费，后无限期推迟但未正式取消，长期预算别把「永久免费」写死。

**3. 每次换模型**

- 手机 Issue 表单里选 `fast / strong / local`
- 或评论里带 `[model:strong]`
- 或桌面 `Run workflow` 里下拉选
- 或 `flow.yml` 里给每个节点写死 `model:`

新增模型：在 `models.yml` 加一个别名；要换第二把 key，就在 `.github/workflows/flow.yml` 的 `env` 里加一行 `MY_KEY: ${{ secrets.MY_KEY }}`，然后 `key_env: MY_KEY`。

---

## 五、小程序扫码验收（可选开关）

1. 微信公众平台 `开发管理 → 开发设置 → 小程序代码上传` 下载上传密钥，把**文件内容**（不是路径）存成 Secret `WECHAT_PRIVATE_KEY`，AppID 存成 `WECHAT_APPID`；IP 白名单按官方 CI 说明配置或关闭。
2. 把 `flow.yml` 末尾注释掉的 `preview` / `ship` 两个节点取消注释。
3. 之后流程会：跑完代码 → 你验收 → 自动生成二维码 → 面板上出现二维码 → 手机扫码真机验收 → 回复「通过」即上传开发版本（`ship` 的 `on_approve`）。

Taro / uni-app 项目请把 `scripts/preview.js`、`scripts/upload.js` 里的 `projectPath` 改成构建产物目录（如 `dist/build/mp-weixin`）。上传只到「开发版本」列表，**提审和发布仍需你人工在后台点**，这是刻意留的安全闸门。

---

## 六、排错速查

| 现象 | 原因 / 动作 |
|---|---|
| Actions 没触发 | 检查 workflow 的 `if` 过滤；用 `GITHUB_TOKEN` 发的评论/Issue 不会再触发（防循环，正常） |
| `HTTP 401/404` | base_url 少 `/v1`、模型 ID 拼错、key 没配或配到了别的 Secret 名 |
| `HTTP 400 ... tools` | 模型不支持 function calling → 在 Variables 加 `AGENT_PLAIN=1`，或给该节点加 `plain: true` |
| 模型听不懂、乱改文件 | 必须支持 tool calling；`AGENT_PLAIN=1` 是降级方案，效果弱一些 |
| Mermaid 图不显示 | 等几秒；确认评论里是 ` ```mermaid ` 代码块；Pages 面板需能访问 jsdelivr CDN |
| 面板网页一直是旧图 | Pages 的 Source 必须选 **GitHub Actions**（不是「从分支发布」），且 Variables 里有 `ENABLE_PAGES=1`；看 Actions 里的 `pages` job 是否成功 |
| 评论后没反应 | 只有**黄色 waiting 节点**才吃评论；或机器人自己的评论被过滤了（正常） |
| 两条评论打架 | `concurrency` 已串行排队，等前一条跑完即可 |
| `local` 模型连不上 | 只有 `runs_on: self-hosted` + 本机 Ollama 在跑才行 |
| 私有仓库 Pages 打不开 | 部分套餐对私有仓库 Pages 有限制，此时直接看 Issue 评论里的 DAG 图即可 |
| 二维码生成失败 | 检查私钥内容是否完整粘贴、IP 白名单、AppID、projectPath 是否指向小程序产物 |

---

## 七、这套方案的边界（先说清楚）

- **状态是文件式的**：`state.json` + 仓库文件就是全部记忆，agent 每次被叫醒读档案、干完写回。适合拆得开、能验收的活；不适合需要连续几小时探索式调试的活（那种用 WorkBuddy / IDE 里的长会话更顺）。
- **图是静态的**：DAG 由你定义，节点内部才让 agent 自主。别把图拆得过细。
- **runner 没有 GUI**：不能开微信开发者工具做真机调试，验收靠 `miniprogram-ci` 二维码 + 你的手机。
- **凭据**：API key、小程序上传私钥只放 Secrets，绝不入库；`.gitignore` 已挡 `*.key` / `.env`。
- **无人值守**：agent 默认不能改 `.github/`、`state.json`、`flow.yml`、`models.yml`，命令执行有白名单，避免它给自己提权。

---

## 目录速览

| 文件 | 谁动它 |
|---|---|
| `flow.yml` | ★ 你：定义 DAG |
| `models.yml` | ★ 你：模型别名与端点 |
| `.github/ISSUE_TEMPLATE/task.yml` | 手机提需求表单 |
| `.github/workflows/flow.yml` | 一次配好：触发、机器选择、Secrets 注入 |
| `scripts/flow.py` | 调度引擎（推进 DAG / 渲染 / 贴评论） |
| `scripts/agent.py` | 零依赖 OpenAI 兼容 agent loop |
| `scripts/preview.js` `upload.js` | 小程序二维码与上传 |
| `state.json` | 机器人自动维护，**别手改** |
| `docs/index.html` | 机器人自动重绘的手机面板 |
| `docs/spec.md` | 第一个节点生成的需求清单 |
