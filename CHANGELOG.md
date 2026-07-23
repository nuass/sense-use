# Changelog

All notable changes to `sense-use` are documented here. Follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[SemVer](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-07-24

First public release.

### Added

- **Textual TUI** — main chat / think / act event stream, sidebar memory tree,
  bottom Input, keyboard bindings for archive (`Ctrl+S`), voice (`Ctrl+Space`),
  and Y/N confirm.
- **Backends** — Playwright/CDP browser, ADB (via `mobile-use-agent`),
  pyautogui + mss desktop, vncdotool VNC. All expose the same
  `Backend` interface (`screenshot / click / type_text / swipe / key /
  get_size / is_sensitive`). Optional deps are try-imported.
- **Backend registry** — TUI enumerates the backends whose deps are installed.
- **PyQt6 floating viewer** — one subprocess per target, unix-socket IPC with
  length-prefixed JSON, always-on-top, aspect-preserving overlay for the
  agent's tap circles.
- **Multi-provider VLM** — `volc` (火山 doubao-seed-vision), `claude`
  (Anthropic Messages), `openai` (Chat Completions with vision), `qwen_local`
  (Ollama compatible). All share one JSON action schema.
- **Provider registry + `sense-use providers` command**.
- **Config** — `~/.sense-use/config.yaml` written on first run;
  `--provider` / `--cdp` / `--config` CLI flags; env vars override config.
- **Local storage** — `~/.sense-use/projects/*.json`,
  `memory/*.md + MEMORY.md`, `sessions/YYYY-MM-DD/*.jsonl`.
- **Volc real-time ASR voice input** via `Ctrl+Space` toggle.
- **Sensitive-action confirm modal** — Y/N/R hotkeys and inline args display.
- **Project archive modal** — pick an existing project or type a new name.
- **Memory tree widget + memory editor modal** with `Ctrl+S` save.
- **CI** — pytest + ruff + build wheel matrix across Python 3.10-3.12 on
  Ubuntu + macOS.

### Docs

- `README.md` / `README-zh.md` bilingual.
- `docs/demo.md` — recording script for the README GIF.
- `docs/development-charter.md`, `docs/competitive-landscape.md` — kept from M0.
