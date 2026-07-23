# sense-use

> 开源、自托管的 **Computer + Mobile + Browser Use** —— 一个 TUI，多个悬浮观察窗，语音输入，全本地。

**中文 · [English](README.md)**

Anthropic 的 Computer Use 是闭源 SaaS 且只控桌面。`sense-use` 是开源自托管替代：一个 TUI 主界面同时驱动手机（ADB）、浏览器（CDP）、本机桌面（pyautogui）、远程机（VNC）；每个被控目标弹一个独立 PyQt 浮动窗看画面、鼠标可回传接管；输入框支持 `Ctrl+Space` 火山实时语音；会话可归档到项目、memory 全部 Markdown 可读可编辑；敏感动作强制 ✅/❌ 确认。全本地，无账号，`pip install` 就能跑。

## 特性

- **四种后端一个 CLI**：ADB / Playwright over CDP / pyautogui / VNC
- **每个目标一个 PyQt 悬浮观察窗**（可拖拽、缩放、置顶），不覆盖终端
- **`Ctrl+Space` 触发火山实时语音输入**
- **可视 Memory 树**（Markdown、git 友好、点开可编辑，`Ctrl+S` 保存）
- **敏感动作强制确认**（付款/删除/发送 → ✅/❌/🔁）
- **项目归档 `Ctrl+S`**：会话可存到已有项目或新建项目
- **多模型 provider**：火山 doubao、Anthropic Claude、OpenAI GPT-4o、本地 Qwen2.5-VL over Ollama
- **全本地存储** `~/.sense-use/`，无云无账号

## 架构

```
┌────────────────────────────────────────────────────────────────┐
│                        Textual TUI 主进程                       │
│  ┌──────────────┐   ┌──────────────────────────────────────┐   │
│  │  🧠 Memory   │   │  chat / think / act 事件流            │   │
│  │  树          │   │  Y/N 确认模态 · Ctrl+Space 语音       │   │
│  └──────────────┘   └──────────────────────────────────────┘   │
└──────────────┬─────────────────────┬───────────────────────────┘
        events │             frames  │  overlay
               ▼                     ▼
      ┌─────────────────┐   ┌──────────────────────────────┐
      │  TaskRunner     │   │  PyQt 观察窗子进程            │
      │  (asyncio)      │   │  （每目标一个 unix-socket）    │
      └─┬───────────────┘   └──────────────────────────────┘
        │                    ▲
        ▼                    │  screenshot bytes
      ┌──────────────────────┴──────────────────────────────┐
      │  Backend (screenshot / click / type / swipe / key)   │
      │  ─ adb · desktop · browser (CDP) · vnc              │
      └──────────────────────────────────────────────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │  Provider   │  volc · claude · openai · qwen_local
                    └─────────────┘
```

## 安装

```bash
pip install sense-use[all]
playwright install chromium   # 仅浏览器后端需要
sense-use
```

可选安装（挑需要的）：

| Extra      | 装什么                             |
|------------|-----------------------------------|
| `desktop`  | `pyautogui` + `mss`               |
| `mobile`   | `mobile-use-agent`（ADB 工具）    |
| `vnc`      | `vncdotool`                       |
| `viewer`   | `PyQt6` 悬浮观察窗                 |
| `voice`    | `sounddevice` + `numpy`（ASR）    |
| `all`      | 全部                               |

## 快速开始

```bash
# 1. 以调试模式启动 Chrome（一次即可）：
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 --remote-allow-origins='*'

# 2. 起 sense-use：
sense-use --provider volc
```

首次运行会生成 `~/.sense-use/config.yaml`，把 API key 填进去（或设环境变量：
`ARK_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`；语音要
`VOLC_APP_ID` + `VOLC_ACCESS_TOKEN`）。

TUI 里：

- 输入目标，回车执行
- `Ctrl+Space` — 开始/停止语音录音
- `Y` / `N` — 通过/拒绝敏感动作确认
- `Ctrl+S` — 把当前会话归档到项目
- 点击左侧 Memory 项 → 弹编辑器（`Ctrl+S` 保存）

## Provider 列表

```
$ sense-use providers
volc         — Volc doubao-seed-vision
claude       — Anthropic Claude (vision)
openai       — OpenAI GPT-4o (vision)
qwen_local   — Qwen2.5-VL (local Ollama)
```

启动时切换：`sense-use -p claude`；或改 `config.yaml` 里的 `default_provider:`。
只有装了对应 SDK 的 provider 才会显示（`anthropic` / `openai`；qwen_local 纯
httpx，无需 SDK）。

## 路线图

- [x] M1 · 骨架 + Browser 后端 + Textual TUI
- [x] M2 · ADB / Desktop / VNC 后端 + PyQt 悬浮观察窗
- [x] M3 · 项目归档 + Memory 树 + 语音输入 + 确认模态
- [x] M4 · 多 provider 打磨 + config + CI + pypi 发布

## 贡献

提 PR 前请先读 [`docs/development-charter.md`](docs/development-charter.md) —— 里面定义了项目边界、模块契约、用户体验预期、反模式清单。风格/测试/快捷键/存储布局的一切约定都以此章程为准。

想了解 sense-use 与其他 agent 框架（browser-use、UI-TARS、cua、OpenHands、Cline、Aider…）的差异对比，见 [`docs/competitive-landscape.md`](docs/competitive-landscape.md)。

## License

MIT © senseone
