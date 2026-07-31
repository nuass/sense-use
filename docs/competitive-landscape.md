# sense-use · 竞品地图 (Competitive Landscape)

> 2026-07-31 v0.2 同步：补 Demo 视频入口 + 与 brief 口径一致 + 加 v0.3 待观察对象
> 原始 2026-07-24 扫描窗口：**最近 5 个月**（2026-02-24 ~ 2026-07-24）。
> star 与 Δ5m（近 5 个月增长）为扫描时的近似值，用于横向排序、非精确基准。

**用途**：
- 决定 sense-use 哪些模块**依赖已有轮子**、哪些**必须自研**
- 提供对外 pitch/README 的差异化对标口径
- 每季度更新一次（M2/M3/M4 完成时各刷一次）

**v0.2 对应 Demo 证据**（2026-07-31 实测）：
- 三端真机：browser+adb+desktop 3 pane 同屏（demo.mp4 0-3s）
- 闭环真答：browser 1 步答出 "Anthropic Computer Use is closed-source and desktop-only."
- 跨端并行：browser+adb 同时 dispatch 不同 goal
- 真 memory 树：归档后 sidebar 实时出现 3 条新 entry
- 优雅降级：Voice 无 mic 时显示红字 "🎙 voice unavailable"

---

## 1 · Top 25 与 sense-use 相关的开源项目

| # | Repo | Star | Δ5m | 定位 | 与 sense-use 重合 | 缺什么 |
|---|---|---:|---:|---|---|---|
| 1 | anthropics/claude-code | 138.8k | +40k | TUI 单机 agent（闭源二进制） | TUI/Memory/项目/敏感拦截/多 provider | 闭源；仅 shell，无 Android/Browser/VNC |
| 2 | **browser-use/browser-use** | 106.3k | +30k | Playwright 浏览器 agent SDK | Browser 后端 | 无 UI、无 Android/Desktop/VNC/ASR |
| 3 | All-Hands-AI/OpenHands | 81.8k | +8k | Web/VSCode 开发 agent | 项目管理、沙盒 | Web UI；无 mobile；单终端 |
| 4 | openinterpreter/open-interpreter | 67.2k | +2k | 本地 shell agent | pyautogui 桌面 | 无 Android/独立浮窗、无 TUI |
| 5 | cline/cline | 65.0k | +18k | VSCode 编码 agent | diff / 审批面板 | VSCode 内嵌 |
| 6 | block/goose | 51.5k | +25k | 桌面 agent（Rust GUI） | 多 provider / MCP | 无 mobile/browser 后端、无 memory 树 |
| 7 | Aider-AI/aider | 47.6k | +3k | TUI 编码 pair | TUI/`/command`/git diff | 编码 only |
| 8 | **bytedance/UI-TARS-desktop** | 38.2k | +12k | 桌面多模态 agent（Electron） | 桌面+浏览器 | Electron，非 TUI+PyQt；单目标；国内背景 |
| 9 | continuedev/continue | 35.1k | +4k | IDE agent | 多 provider 抽象 | IDE 内嵌 |
| 10 | Pythagora-io/gpt-pilot | 33.7k | +1k | 项目生成 | 项目管理 | 编码 only |
| 11 | RooCodeInc/Roo-Code | 24.4k | +8k | Cline fork、多角色 | 多 agent、审批 | VSCode 内嵌 |
| 12 | letta-ai/letta | 23.9k | +6k | Stateful memory 平台 | Memory 引擎 | 服务端；无 GUI 控制 |
| 13 | Skyvern-AI/skyvern | 22.6k | +5k | 浏览器工作流 | Browser 后端 | 服务端；无桌面客户端 |
| 14 | **trycua/cua** | 20.5k | +15k | 跨 OS CUA 驱动+基准 | 桌面 / 远程 VM 后端 | SDK 定位，无 UI，偏 macOS VM |
| 15 | SWE-agent/SWE-agent | 19.9k | +2k | issue→PR agent | 沙盒动作 | 编码 only |
| 16 | anthropics/anthropic-quickstarts | 17.3k | +6k | CUA 参考实现（Docker+VNC） | VNC 后端参考 | demo 级 |
| 17 | microsoft/agent-framework | 12.3k | +12k | 微软多 agent 编排 | 多 agent runtime | 无 GUI/mobile |
| 18 | simular-ai/Agent-S | 12.1k | +4k | OS 级人形 agent | 桌面/记忆 | 服务端；无 mobile |
| 19 | e2b-dev/E2B | 13.1k | +2k | 云沙盒基建 | 远程 VM 后端 | 云优先 |
| 20 | microsoft/UFO | 9.3k | +3k | Windows OS Agent | 桌面多 agent | Win only |
| 21 | X-PLUG/MobileAgent | 9.0k | +2k | Mobile GUI agent 家族 | Android 后端参考 | 研究代码 |
| 22 | **droidrun/droidrun** | 8.9k | +5k | ADB+LLM 手机 agent | Android 后端（可复用） | 无桌面/browser/UI |
| 23 | gptme/gptme | 4.4k | +2k | 本地 TUI agent | TUI / 多 provider | 无 Android/browser 后端 |
| 24 | microsoft/fara | 6.0k | +6k | CUA 前沿模型 | 可作 VLM provider | 模型而非框架 |
| 25 | byt3bl33d3r/figaro | 0.14k | +0.14k | 多设备 CC/CUA 编排 | 多目标并行 / HITL / live stream | 早期，生态薄 |

**补充观察**：
- livekit/agents (11.5k) + TEN-framework (11.0k) 在**实时 ASR + 语音 agent** 方向暴涨 → sense-use M3 语音输入可参考
- microsoft/OmniParser (25.2k) 是所有 CUA 项目的 **UI 元素解析共同底座** → 可考虑作 VLM 兜底
- xlang-ai/OSWorld-V2、weavebench/WeaveBench 是新一代 **computer-use benchmark**，Q3 会成事实基准

---

## 2 · 三个最相似项目深度对比

评分维度：① TUI+浮窗 ② 四 Backend 并存 ③ 多目标并行 ④ 空格 ASR ⑤ Memory 树 ⑥ 敏感拦截 ⑦ 项目管理 ⑧ 全本地 ⑨ 多 VLM ⑩ MIT/Apache

### 2.1 bytedance/UI-TARS-desktop（38.2k · Apache-2.0）—— **主要竞品**

- ✅ ②（桌面+浏览器）⑥ ⑨（自家 UI-TARS + OpenAI/Claude）⑩
- ❌ ①（Electron，非 TUI+PyQt）③（单目标为主）④ ⑤ ⑦ ⑧（依赖云端模型）

**结论**：**竞品，不是依赖**。栈完全走 Electron/TS，架构无法复用。
**该抄**：敏感动作 confirm 弹窗 UX + agent-tars 双列 trajectory 视图（思考｜截图并排）。

### 2.2 trycua/cua（20.5k · MIT）—— **应作为 Remote/Desktop 依赖引入**

- ✅ ②（macOS VM / Docker / Linux 桌面完整）⑥ ⑨ ⑩
- ❌ ①（无 GUI）③（fleet 概念偏 headless）④ ⑤ ⑦ ⑧（部分组件走云）

**结论**：**Desktop 与 VNC/远程 Backend 直接依赖 cua**。`pylume`（Mac VM）+ `computer` SDK 恰好补齐 sense-use 的远程后端能力，不必重写。

### 2.3 byt3bl33d3r/figaro（0.14k · MIT）—— **同思想 sibling，可借鉴不宜依赖**

- ✅ ②（容器+VM+物理设备）③（fleet 多目标）⑥（HITL gateway）⑦
- ❌ ①（无 TUI）④ ⑤ ⑧（Anthropic 深绑）⑨（Claude 中心）⑩

**结论**：思想上最接近 sense-use「多目标 + HITL」，但生态薄、Anthropic 深绑，**不宜依赖**。
**该抄**：live desktop streaming + 多 channel HITL gateway 三段式架构图。

---

## 3 · 是否有一个能"开箱替代 sense-use"？

**否**。10 条特性组合的交集在所有项目上都只覆盖 2-4 条：

| 特性 | 覆盖它的最好项目 | 是否需自研 |
|---|---|---|
| ①TUI+PyQt 浮窗 | 无（Aider/claude-code 只 TUI，无浮窗） | ✅ 自研 |
| ②四 Backend 并存 | 无（各自散布） | ✅ 组合 |
| ③多目标并行 | figaro（早期）/ cua fleet | ✅ 自研 + cua fleet 接口 |
| ④空格 ASR | 无 | ✅ 自研（可用 livekit/agents 组件） |
| ⑤可视 Memory 树 | claude-code（闭源）/ Letta（服务端） | ✅ 自研 |
| ⑥敏感拦截 | UI-TARS / Cline | ✅ 自研（抄 UX） |
| ⑦项目管理 | claude-code / gpt-pilot | ✅ 自研（简单） |
| ⑧全本地 | Aider / gptme | ✅ 自研（本地文件态） |
| ⑨多 VLM | goose / continue | ✅ 自研 provider 层 |
| ⑩MIT/Apache | cua / browser-use | ✅ MIT |

结论：**sense-use 独特组合成立**，市场空白足够开一款产品。

---

## 4 · 依赖决策（Vendor vs Build）

| 层 | 决策 | 原因 |
|---|---|---|
| **Browser Backend** | **改用 `browser-use` 依赖**（当前 M1 自写代码降级为 fallback） | 106k star 事实标准，DOM 语义/防重复/错误恢复已成熟 |
| **Mobile Backend** | 继续用 `mobile-use-agent`（自家） + 可选 `droidrun` 桥 | 自家可控；droidrun 未来做多手机并行时可切 |
| **Desktop / VNC Backend** | **引入 `trycua/cua`** | 现成 macOS VM + Linux 桌面驱动 |
| **VLM Provider 层** | 自研（火山 doubao 默认，Claude/GPT/Qwen 插件） | 简单、可控、无锁定 |
| **UI 元素解析兜底** | 可选 `microsoft/OmniParser` | 当 VLM 不出坐标时兜底 |
| **实时 ASR** | 火山 ASR + livekit/agents 参考 | 已有 volc token 生态 |
| **Fleet 编排（M4+）** | 依赖 `cua` fleet 接口 或 `e2b-dev` 云沙盒 | 别重造 |

---

## 5 · 值得抄的 UX / 架构决策

| 抄谁 | 抄什么 | 落到 |
|---|---|---|
| Cline / Roo Code | tool-call 逐步 approve 面板 + diff 视图 | M3 confirm modal |
| Aider / claude-code | TUI 历史命令 `↑↓` + `/command` 语义 | M2 输入框 |
| Letta | Memory Block 分层（core / archival） | M3 memory 树 |
| UI-TARS-desktop | 双列 trajectory（思考\|截图并排） | M2 观察窗 |
| figaro | fleet + HITL gateway 三段式架构 | M4 fleet mode |
| block/goose | MCP tool 一键接入 | v0.2 MCP 支持 |
| livekit/agents | 实时音频流 pipeline 结构 | M3 ASR |

---

## 6 · 盲区（本次扫描才发现）

### 6.1 Fleet / VM 沙盒方向正在爆红

trycua/cua、e2b-dev、wide-moat/open-computer-use、opendesk 都在做「一 agent N 机」编排层。

**对 sense-use 的影响**：多目标如果只做本机 3-4 个会被拉开。**必须在 charter 里预留 fleet-ready 接口**（哪怕 v0.x 只跑本机，Backend / Session / EventBus 设计上要能 scale 到远程）。

### 6.2 Computer-Use Benchmark 起势

OSWorld-V2 / WeaveBench / mobilegym 2026 Q2 起来。**sense-use 若能自带"跑 OSWorld/WeaveBench 出分"**（`sense-use bench osworld`），会立刻在市场里有站位差异 —— **比堆功能更容易被引用**。

### 6.3 语音 agent 生态成型

livekit/agents + TEN-framework 是"语音进 → 动作出"的完整栈。sense-use 的空格 ASR 只做输入端，**未来可加"agent 说话反馈"闭环**（TTS 播报每步 thought），差异化再拉一层。

---

## 7 · 对外 pitch 差异化口径（README / HN / Twitter 复用）

> **sense-use = the only open-source TUI that drives Android + Browser + Desktop + Remote in one terminal, with floating live viewers per target, voice input, human-readable Markdown memory, and sensitive-action guardrails. Fully local. MIT.**
>
> Not another VSCode plugin. Not another Electron app. Not another cloud SaaS. Not another SDK.

### 7.1 一句怼一句（对标语）

- vs Anthropic Computer Use：*"open + self-host + also mobile + browser"*
- vs UI-TARS-desktop：*"TUI-first + true multi-target + no Electron bloat"*
- vs browser-use：*"a product, not a library — one CLI, four backends, plus a viewer"*
- vs cua：*"cua ships the driver; sense-use ships the console you use"*
- vs OpenHands：*"native TUI + phone/browser/desktop, not just a code-agent web IDE"*

---

_竞品地图 v1.0 · 2026-07-24_
_下次更新触发：M2 完成 或 出现 star ≥ 5k 的新 CUA 项目_
