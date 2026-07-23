# sense-use demo — 5-minute walkthrough

The script we use for recording the README GIF. Follow it step-by-step and you
get a full-loop verification of the M1→M4 stack.

## Prereqs

- Chrome running with remote debugging:
  ```bash
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
      --remote-debugging-port=9222 --remote-allow-origins='*'
  ```
- `ARK_API_KEY` in env (or fill it into `~/.sense-use/config.yaml`).
- Optional but nice: `VOLC_APP_ID` + `VOLC_ACCESS_TOKEN` for voice.

## Script

### 1. First run creates the config

```bash
sense-use
```

At first launch the TUI writes `~/.sense-use/config.yaml`. If you want to see
where it landed:

```bash
sense-use config-path
```

Point out the sidebar: **🧠 Memory** empty (no entries yet) + the "Ctrl+S
archive · Ctrl+Space voice" hint under Targets.

### 2. Type a browsing goal

In the input, paste:

```
Open arxiv.org and list the top 3 paper titles for the query "llm agents 2026".
```

You'll see:

- `👁 step 1 — screenshot NN bytes` (observe)
- `🧠 step 1 …` — model's thought + planned action
- `✔ click — success` / `✔ type — success` streaming
- Eventually `✅ DONE: <answer>`.

### 3. Voice input (optional)

Press `Ctrl+Space`. A `🎙 recording` line appears. Speak "open hacker news top
stories". The input field fills in real time; press `Ctrl+Space` again to stop.
`Enter` to send.

### 4. Sensitive-action confirm

If the model chooses `click` with a label like "确认支付" / "Pay now" /
"Delete", a modal pops up:

```
⚠ Confirm
action: click
target: Delete this workspace
args:   {"x": 812, "y": 340}

[✅ Y allow]  [❌ N reject]  [🔁 R replan]
```

Press `N` to reject and force the model to replan.

### 5. Archive to a project

Hit `Ctrl+S`. A modal lists existing projects (empty on first run). Type a new
name in the input:

```
arxiv-research
```

Press `Enter`. The bottom line prints:

```
📁 archived session <sid>… to project arxiv-research
```

Under `~/.sense-use/projects/arxiv-research.json` you'll find the project with
the session id appended.

### 6. Memory tree

Click a Memory entry in the sidebar (or add one first via
`sense_use.store.memory_store.write_memory("hello.md", "hi", title="Hello")`).
A modal opens with `TextArea.code_editor`. Edit, `Ctrl+S` saves to
`~/.sense-use/memory/<file>` and updates `MEMORY.md`. `Escape` closes.

### 7. Switch provider

```bash
sense-use -p claude
```

Or edit `default_provider: claude` in `config.yaml`. Available:

```bash
$ sense-use providers
volc         — Volc doubao-seed-vision
claude       — Anthropic Claude (vision)
openai       — OpenAI GPT-4o (vision)
qwen_local   — Qwen2.5-VL (local Ollama)
```

## Recording the GIF

Use `terminalizer` or `asciinema` + `agg`:

```bash
brew install asciinema agg
asciinema rec demo.cast
# run the script above, then Ctrl+D
agg demo.cast demo.gif --theme monokai --font-size 14
```

Trim to ~90s. Drop `demo.gif` at the top of README (before `## Why`).

## Troubleshooting

- **`failed to connect CDP`** — Chrome not started, or missing
  `--remote-allow-origins='*'` (Chrome 113+ blocks cross-origin CDP).
- **`ARK_API_KEY` missing** — either export it or edit config.yaml.
- **PyQt viewer crashes on macOS** — the spawn helper injects
  `QT_QPA_PLATFORM_PLUGIN_PATH`; if you still hit "no qt platform plugin",
  reinstall `PyQt6` in the same venv as `sense-use`.
- **`sense-use` command not found after `pip install -e .`** — check your PATH;
  fall back to `python -m sense_use`.
