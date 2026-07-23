# sense-use · 开发章程 (Development Charter)

> 本文件是 **sense-use 全局开发指南**，指导所有贡献者（含 AI agent 与人类协作者）在写代码、加特性、评审 PR 时的判断依据。
> 变更此文档需在 issue 或 RFC 里讨论。

**版本**：v1.0 · 2026-07-24
**适用**：M1 完成后（当前）→ M2/M3/M4 全部开发
**受众**：核心作者、外部贡献者、AI 协作者

---

## 1. 项目边界（What sense-use IS / IS NOT）

### 1.1 IS —— 我们做什么

| 定位 | 具体含义 |
|---|---|
| **本地桌面客户端** | 用户 `pip install` 到自己机器上运行的一个 Python 进程，不是 SaaS、不是 web app |
| **多目标 Agent 控制台** | 一个 TUI 同时驱动手机 / 浏览器 / 桌面 / 远程机 —— 目标数 ≥ 4 |
| **观察-思考-执行 (Observe-Think-Act) 循环** | 每步 = 截图 → VLM 决策 → 后端执行；用户可随时打断/接管 |
| **可组合的骨架** | Backend、Provider、Voice 三层都是可替换插件；核心稳定，扩展点清晰 |
| **完全透明** | 会话 = jsonl，memory = md，配置 = yaml，任何 LLM 决策可回放 |
| **面向"能用命令行的人"** | 目标用户：开发者、极客、安全工程师、爬虫写手；不做"给外婆用"的封装 |

### 1.2 IS NOT —— 我们坚决不做

| 拒绝做 | 理由 |
|---|---|
| ❌ 云托管 / 账号系统 / SaaS 后端 | 违背 self-host 卖点；任何"注册-登录"是死线 |
| ❌ 把 API key 上传到我方服务器 | 所有 key 只落用户 `~/.sense-use/config.yaml` |
| ❌ 内置数据库（PostgreSQL / MySQL / MongoDB） | SQLite 都算重；本地文件态优先 |
| ❌ 端到端加密 / 用户体系 / 多租户 | 单机单用户，不做企业化 |
| ❌ 训练自己的 VLM | 我们是**编排器**，不是模型公司；只做 Provider 接入 |
| ❌ 提供越权/绕过验证码/爬敏感数据的默认能力 | 责任在用户；核心工具中立 |
| ❌ 依赖只在中国可用的服务（作默认） | 默认 Provider 火山可切换，README 展示 Claude/GPT 也能跑 |
| ❌ Electron / Web 前端主界面 | TUI + 独立 PyQt 观察窗是核心差异，不背离 |
| ❌ 需要 sudo / root / IME hack 才能跑起来 | 首次运行要能纯用户权限跑通至少一个 Backend |

**判断黄金问题**：*"如果一个开发者 clone 后 5 分钟内跑不起来，是不是我们的错？"* —— 是。

### 1.3 Fleet-Ready 原则（v0.x 只跑本机，但设计上必须能远程）

即使 v0.x 只支持本机 3-4 个目标，以下三点在架构层**必须预留**：

- **Backend 抽象**：`start()` 可接受远程连接串（`ssh://` / `vnc://` / cua fleet handle），不假设本地
- **Session**：不 hardcode `localhost`；`~/.sense-use/` 路径可被覆盖为共享位置
- **EventBus**：pub-sub 语义可无缝改跨进程（现在 asyncio.Queue，未来可换 zmq/nats）

**原因**：trycua/cua、e2b-dev、figaro 都在做「一 agent N 机」编排层；架构不预留 fleet，v0.2 就会被拉开。见 `docs/competitive-landscape.md` §6.1。

### 1.4 Benchmark-Ready 原则（v0.2 起自带跑分）

**v0.2 目标**：`sense-use bench osworld` / `sense-use bench weavebench` 一行跑分并落 markdown 报告。

**原因**：OSWorld-V2 / WeaveBench / mobilegym 会在 2026 Q3-Q4 成事实基准 —— 自带跑分是**站位差异**，比堆功能更容易被引用（比如 HN "Show HN" 帖里能直接贴分数）。见 `docs/competitive-landscape.md` §6.2。

**对 Backend 契约的影响**：所有 Backend 必须能被 headless 驱动（无 TUI 参与），因为 benchmark 是脚本调用。

---

## 2. 模块定义（Module Contract）

### 2.1 分层与依赖方向

```
┌─────────────────────────────────────────────────────────────┐
│  tui/            ← 用户直接感知的一切；只依赖 core 与 store  │
│  viewer/         ← PyQt 子进程；只依赖 core.event 与 IPC     │
│  voice/          ← ASR 客户端；输出文本给 tui                │
├─────────────────────────────────────────────────────────────┤
│  core/           ← 骨架，无外部服务依赖，可离线纯测试         │
│    ├─ backend.py     Backend 抽象基类                        │
│    ├─ session.py     Session dataclass                       │
│    ├─ event_bus.py   asyncio Pub-Sub                         │
│    └─ task_runner.py Observe-Think-Act 主循环                │
├─────────────────────────────────────────────────────────────┤
│  backends/       ← 每文件一个 Backend；只依赖 core.backend    │
│  models/         ← 每文件一个 Provider；只依赖 models.base    │
│  store/          ← 只读写 ~/.sense-use/ 文件；无网络          │
└─────────────────────────────────────────────────────────────┘
```

**依赖铁律**：
- `core/` 不 import `backends/` / `models/` / `tui/` / `viewer/` / `voice/`
- `backends/` 不 import 其他 `backends/` 也不 import `models/`
- `models/` 不 import `backends/` 也不 import 其他 `models/`
- `tui/` 可以调所有下层；`viewer/` 只跨 IPC 说话
- 循环 import = 拒绝合入

### 2.2 每个模块必须交付的四件套

任何新增模块（如新 Backend、新 Provider、新 TUI 屏幕）在 PR 里必须包含：

1. **契约代码**：实现基类的全部抽象方法，缺一个方法必须 `raise NotImplementedError` 而不是 `pass`
2. **一个可跑 example**：`examples/<module>-quickstart.md` 或 `examples/<module>.py`，从零装机 5 分钟内跑通
3. **一个 smoke test**：`tests/test_<module>.py`，不需要真外设也能跑（用 mock/fake）
4. **README 一句话**：更新根 README 的 "Features" 表格里对应行

### 2.3 三大扩展点及其契约

#### Backend 契约（`core/backend.py::Backend`）

一个 Backend 是 **"一台可被点击的设备/软件"** 的抽象。必须实现：

| 方法 | 语义 | 必须真做 vs 可 raise NotImplementedError |
|---|---|---|
| `start / stop` | 建立/释放连接 | 必须 |
| `screenshot() -> bytes` | 返回 PNG | 必须 |
| `get_size() -> (w,h)` | 视口像素 | 必须 |
| `click(x,y,button)` | 单击 | 必须 |
| `type_text(text)` | 输入文本 | 必须 |
| `swipe(x1,y1,x2,y2,dur)` | 拖拽/滑动 | 必须（VNC 可退化为多次 move） |
| `key(name)` | 命名键 | 必须 |
| `is_sensitive(action, payload)` | 敏感判断 | 有默认；建议覆盖 |
| `goto(url)` *可选* | 只 browser 有 | 用 `hasattr` 检查 |
| `read_text()` *可选* | 只 browser/mobile 有 | 用 `hasattr` 检查 |

**新增 Backend 的 checklist**：
- [ ] `kind` 类属性设为 snake_case 唯一名（例如 `"adb"` / `"desktop"` / `"vnc"`）
- [ ] 支持在没有实机时 raise 明确错误（不 hang）
- [ ] 敏感白名单至少覆盖：删除、发送、支付、关机、退出登录
- [ ] 单测：mock 一个 client，验证接口都能被调用

#### Provider 契约（`models/base.py::ModelProvider`）

一个 Provider 是 **"能看图能出决策 JSON 的模型"** 的抽象。必须实现：

```python
async def decide(goal, history, screenshot_png, page_text=None) -> ModelDecision
```

**新增 Provider 的 checklist**：
- [ ] 支持从环境变量 或 config.yaml 加载 key（不硬编码）
- [ ] 兼容 `ModelDecision` schema（thought / action / args / done / label）
- [ ] 解析容错：模型输出带代码块 / 前后废话都能救回来
- [ ] 单测：给一个固定字符串验证 parse 正确；不打真 API

#### Voice 契约（`voice/*.py`）

一个 Voice 客户端是 **"音频流 → 文本"** 的抽象。契约：

```python
async def stream(chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
    """yield partial transcripts; last yield is final."""
```

- 输入：16kHz mono PCM 或 float32 chunk
- 输出：先若干 partial（前面渲染灰色），最后一个 final（渲染黑色）

### 2.4 存储契约（`~/.sense-use/`）

**绝对不能踩的坑**：
- 任何写操作前必须 `mkdir(parents=True, exist_ok=True)`
- 任何读操作要 tolerate 文件不存在（首次运行）
- JSON / YAML 用 `ensure_ascii=False` 保留中文
- jsonl 每行独立 valid JSON，不允许多行

**目录结构（首次运行时按需生成）**：
```
~/.sense-use/
├── config.yaml                  # 全局配置（模型 key / 默认 backend / 快捷键）
├── projects/<slug>.json         # 项目元数据
├── sessions/YYYY-MM-DD/<id>.jsonl
├── memory/
│   ├── MEMORY.md                # 索引
│   └── <slug>.md                # 单条 memory
├── sockets/                     # PyQt IPC unix socket（M2+）
└── logs/sense-use.log
```

---

## 3. 效果（Behavioral Contract）—— 用户视角的"该是什么样"

### 3.1 从零到跑通（Time-to-First-Success）

- **T ≤ 5 分钟**：`pip install sense-use[all] && sense-use` → 第一次任务跑通
- **T ≤ 30 秒**：`sense-use` 起来到 TUI 出现
- **T ≤ 3 秒**：TUI 内敲第一个字符后有反馈
- **T ≤ 200ms**：TUI 内任何按键的视觉反馈

### 3.2 观察-思考-执行 每步的最小反馈

用户敲 goal 回车后，必须**每一步**能在 TUI 看到：
```
👁 step N — screenshot 17193 bytes
🧠 step N thought: ...
   → click {x: 300, y: 400} target: "搜索按钮"
✔ click — clicked (300,400)
```

**没有这四条中任何一条 = bug**。

### 3.3 敏感动作必须拦

Agent 只要触发以下类型动作**必须**弹 `⚠ CONFIRM`：
- Label 含"pay / checkout / delete / logout / 支付 / 删除 / 退出登录"（正则）
- 鼠标坐标落在系统菜单栏 / 关机按钮附近（Desktop Backend）
- 提交表单前 URL 含 `/pay` `/checkout` `/api/delete`（Browser Backend）
- ADB 触发 `am force-stop` 或 `pm uninstall`（Mobile Backend）

用户按 Y 前 agent 阻塞；按 N 立即回退，本步计入 history 但标记 `user_rejected`。

### 3.4 失败模式必须有出路

| 场景 | 期望行为 |
|---|---|
| Chrome 9222 没起 | 明确错误 + 提示"how to launch Chrome with CDP" 命令行 |
| ARK_API_KEY 没配 | 明确错误 + 指向 config.yaml + 官网 URL |
| VLM 返回垃圾 | 解析失败不崩，打印原文，让 agent 重试或用户接管 |
| Agent 陷入循环 | 25 步无进展自动停 + 提示"do you want +25 steps?" |
| 后端断线（Chrome 关了、手机拔了） | 优雅停当前 session，其他 session 不受影响 |

### 3.5 可回放 / 可审计

- 每个 session 的 jsonl 可以离线重放：`sense-use replay <session_id>`（M4 交付）
- 每个 memory 变更留 git-friendly diff
- 敏感确认结果记录在 jsonl 里，事后可查"哪一步是人拒了"

---

## 4. 习惯性（Ergonomics & Conventions）—— 开发时的默认

### 4.1 代码风格

- Python **3.10+**，`from __future__ import annotations` 顶行
- 类型注解**全量**：函数签名必写，模块级变量写关键类型
- 异步：I/O 一律 `async`；CPU 密集切进 `asyncio.to_thread`
- Ruff 默认规则；行宽 100
- 命名：类 `CamelCase`，函数/变量 `snake_case`，常量 `UPPER_SNAKE`
- 中文注释和字符串可以（README 双语），但**标识符全英**

### 4.2 错误处理

- 用户级错误 → 抛清晰异常 + TUI 打印可读中文/英文提示
- 内部 bug → 直接抛，让 stack trace 出来（不吞异常）
- 网络错误 → 不 retry loop；一次失败即报，让用户决定重试
- **禁止** `except Exception: pass`；至少 `logging.exception`

### 4.3 依赖引入的门槛

新增一个 pip 依赖必须回答 3 问：
1. **不装能不能跑核心？** —— 如果不能，放 `[project.dependencies]`；如果可以，放 `[project.optional-dependencies]`
2. **有没有轻量替代？** —— 例：httpx 而不是 requests；stdlib logging 而不是 loguru
3. **License 是否 MIT/Apache/BSD？** —— GPL/AGPL 直接拒（会污染 MIT 项目）

### 4.4 命令行 & 快捷键约定

| 键 | 功能 | 阶段 |
|---|---|---|
| `Enter` | 提交输入 | M1 |
| `Ctrl+C` | 退出应用 | M1 |
| `Y` / `N` | 敏感确认 | M1 |
| `Space` (长按) | 语音输入 | M3 |
| `Ctrl+S` | 会话归档 | M3 |
| `Ctrl+N` | 新建目标 | M2 |
| `Ctrl+T` | 切换目标 | M2 |
| `Ctrl+M` | 打开 memory 树 | M3 |
| `Esc` | 取消当前操作 / 关模态 | M1 |

**修改快捷键 = 需要 issue 讨论**，因为这是"肌肉记忆"，最不能悄悄改。

### 4.5 提交约定（Commits）

- 用 [Conventional Commits](https://www.conventionalcommits.org/) 前缀：`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`
- 一个 commit 只做一件事；跨模块改要拆
- Commit message 前 50 字符必须能独立看懂

### 4.6 PR 门槛

合入 main 之前必须过：
- [ ] `pytest tests/` 全绿
- [ ] `ruff check .` 无错
- [ ] `python -c "import sense_use; ..."` 全模块可 import
- [ ] 涉及 Backend/Provider/Voice → 新增单测
- [ ] 涉及用户可见行为 → 更新 README 或 examples
- [ ] 涉及快捷键/存储路径/配置格式 → 更新本 Charter

---

## 5. 好用性（Usability Principles）—— 拿在手里的手感

### 5.1 三条最高优先级原则

1. **可预测 > 便利**
   Agent 该弹确认就弹，不为了"看起来顺"跳过。用户宁可多按 Y，也不要遭遇"agent 无预警下单"。

2. **一屏 > 折叠**
   TUI 首屏能同时看到：**目标列表**（左）· **对话流**（中）· **输入框**（下）· **快捷键提示**（Footer）。任何核心操作不需要滚屏找。

3. **透明 > 魔法**
   VLM 每步的 thought 和 action 参数**永远展示**。不要为了"看起来聪明"隐藏。

### 5.2 观察窗（M2 关键）的手感

- **默认开**（除非用户 config 关）
- **左上角吸附**（可拖走，位置记忆到 config.yaml）
- **置顶**（可切）
- **鼠标点画面 = 把该点回传给 agent 作为 hint**（不是替 agent 点）
- **右键 = 弹菜单**：暂停 agent / 截图存文件 / 关闭观察窗
- **关掉观察窗 ≠ 停 session**（session 在后台继续，日志走 TUI）

### 5.3 输入框的手感

- **多行**：`Alt+Enter` 换行，`Enter` 提交
- **历史**：`↑/↓` 翻上一次输入
- **补全**：`/` 前缀触发命令补全（`/help /new /switch /archive /memory`）
- **粘贴大段** → 自动折叠为 "📄 pasted 47 lines" 摘要，agent 收到全文
- **正在运行** 时不禁用输入（可以随时打断，`Esc` 立即停当前 session）

### 5.4 Memory 树的手感

- 树节点点击 = 弹 modal 显示 md 内容
- Modal 内 `E` 键 = 进入编辑（vim/nano 或 in-TUI textarea）
- 编辑保存 = 立刻 diff 显示在对话流（"memory updated: xxx.md +3 -1"）
- 每个 session 结束时 agent 主动问 "是否记录 1-2 条 memory？"

### 5.5 感觉像 Claude Code / Aider 的"AI 命令行"

- 输入即发送（不需要点按钮）
- 每条 agent 输出前有 emoji + 步号，方便扫读
- 颜色语义稳定：**黄=思考、绿=成功、红=失败、紫=需确认、灰=元信息**
- 不用 emoji 也能看懂（无障碍 friendly）

### 5.6 "开源手感" 的额外约束

- 首次运行 `sense-use` 自动生成 `~/.sense-use/config.yaml` 模板 + 一句话引导
- `README.md` 首屏 30 秒能看懂"这是啥、装咋装、跑啥样"
- Demo GIF **必须**放 README 第一屏
- 中文/英文文档同步（不能只有中文/只有英文）
- Issue 模板：bug / feature / backend-request / provider-request

---

## 6. 里程碑与验收（Milestones Reprise）

| 里程碑 | 主要新增 | 验收标准 |
|---|---|---|
| **M1** ✅ | 骨架 + Browser Backend + Volc Provider + Textual TUI + jsonl session | `sense-use` 起来说"打开 arxiv 搜 xxx"能跑完 |
| **M2** | ADB / Desktop / VNC + **PyQt 观察窗子进程** | 一个 TUI 同时开三个观察窗，三 agent 并行 |
| **M3** | Project 归档 + Memory 树 + 火山 ASR 语音 + 敏感 modal 完善 | 语音输入 → agent 跑 → 敏感确认 → 归档到项目 → 明天回来 memory 更新可见 |
| **M4** | 多 Provider（Claude / GPT / Qwen 本地） + Replay + CI + pypi | `pip install sense-use && sense-use` 从零装机跑通 |
| **v0.2** | Fleet-mode（远程 target via cua/e2b）+ MCP tool 支持 + Benchmark 跑分 | `sense-use bench osworld` 出分并落 markdown 报告 |

每个 M 之间不留半成品：**上个 M 未验收，不启动下个 M**。

---

## 7. 反模式（Anti-patterns）—— 见到必拒

- **在 core/ 里 import 具体 Backend** —— 违反依赖方向
- **一个 PR 改超过 3 个模块** —— 拆
- **TUI 里同步阻塞（`time.sleep` / `input()`）** —— 全 async
- **在 Backend 内起子进程做长任务** —— 交给 asyncio task
- **配置写在代码常量里** —— 除非是纯技术常量（如正则）
- **测试要真实网络/真实设备才能过** —— 必须能纯 mock 跑
- **加个"just this once" 的临时开关** —— 一定会永久留下
- **随手 print** —— 用 `logging` 或 event_bus
- **忽略用户输入的 goal 直接调 hardcode 流程** —— 我们是**通用 agent**，不是脚本集合
- **重造轮子**：自写浏览器 CDP 编排（用 `browser-use`）、自写 macOS VM 驱动（用 `trycua/cua`）、自写 UI 元素解析（用 `microsoft/OmniParser`）—— 只做**装配和差异化**，不做**基础设施**
- **Backend hardcode 本地路径 / localhost** —— 违反 fleet-ready 原则（§1.3）；总假设可能是远程

---

## 8. 决策日志（Decisions of Record）

> 关键架构决定记录在此，未来推翻要说明 why。

| # | 日期 | 决定 | 原因 |
|---|---|---|---|
| D1 | 2026-07-24 | TUI 用 Textual 而非 Bubbletea | Python 生态、可复用 mobile-use-agent 内核、无跨语言 IPC |
| D2 | 2026-07-24 | 观察窗用 PyQt6 独立子进程 + Unix socket | 避免 asyncio/Qt eventloop 打架；关观察窗不影响主进程 |
| D3 | 2026-07-24 | 存储用文件态（JSON+MD+jsonl），拒 SQLite | git 友好、可 diff、无 schema 迁移负担 |
| D4 | 2026-07-24 | Backend 抽象直接建在 sense-use 侧，不上游改 mobile-use-agent | 快速迭代不阻塞；稳定后再 PR 回上游 |
| D5 | 2026-07-24 | 默认 Provider = 火山 doubao，但 M4 强制多 Provider 并列 | 中国用户零门槛，同时对外证明"不锁定" |
| **D6** | 2026-07-24 | **Browser Backend 改依赖 `browser-use` (106k star)**，自写代码降级为 fallback | 事实标准；DOM 语义/防重复/错误恢复已成熟；蹭生态认可度 |
| **D7** | 2026-07-24 | **Desktop / VNC / 远程 Backend 依赖 `trycua/cua` (MIT)** | 现成 macOS VM + Linux 桌面驱动；省两周开发 |
| **D8** | 2026-07-24 | **Backend / Session / EventBus 设计上必须 fleet-ready** —— 即使 v0.x 只跑本机 | trycua/cua、e2b、figaro 都在做 fleet，架构预留才不被拉开 |
| **D9** | 2026-07-24 | **v0.2 目标：自带 `sense-use bench osworld` 出分能力** | OSWorld-V2 / WeaveBench 会成事实基准，自带跑分是最强站位差异 |

---

## 9. 需要外部裁定的问题（Open Questions）

- **Q1**：远程桌面 backend 用 VNC 还是 RDP？RDP 在 Windows 上更原生但需要 pyfreerdp（GPL），VNC 用 vncdotool 可行但慢。→ 默认 VNC，Windows 目标另出 RDP 可选。
- **Q2**：语音输入火山 ASR token 是否放在 default config？还是首次运行让用户填？→ **让用户填**，README 提供获取指引。
- **Q3**：观察窗鼠标点是否直接接管 agent？→ M2 用"hint 模式"（发给 agent 作为提示）；M3 加"接管模式"开关。
- **Q4**：Memory 是否要 embedding 检索？→ M4 后再评估，不进 v0.x。

---

_章程 v1.0 · 2026-07-24 · 作者：sense-use core_
_下次修订触发：M2 完成 或 出现与本文件冲突的 PR_
