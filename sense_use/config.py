"""sense-use config — `~/.sense-use/config.yaml`.

First-run: writes a default template. Later loads: env vars > CLI flag > file value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(os.environ.get("SENSE_USE_HOME", str(Path.home() / ".sense-use")))
CONFIG_PATH = CONFIG_DIR / "config.yaml"


DEFAULT_CONFIG_TEMPLATE = """\
# sense-use config — edit and re-run `sense-use`.
# Env vars listed on each line override the value here.

# Which VLM provider to use by default.
# Options: volc / claude / openai / qwen_local
default_provider: volc

# Default browser CDP endpoint (Chrome must be started with --remote-debugging-port).
cdp_url: http://127.0.0.1:9222

# Per-provider settings. Only the section for your `default_provider` is required.
providers:
  volc:
    # ARK_API_KEY env var overrides this.
    api_key: ""
    model: doubao-seed-1-6-flash-250615
  claude:
    # ANTHROPIC_API_KEY env var overrides this.
    api_key: ""
    model: claude-sonnet-4-6
  openai:
    # OPENAI_API_KEY env var overrides this.
    api_key: ""
    model: gpt-4o
    base_url: ""       # optional; e.g. azure gateway
  qwen_local:
    endpoint: http://localhost:11434/api/chat
    model: qwen2.5-vl:7b

# Voice (Volc ASR). VOLC_APP_ID / VOLC_ACCESS_TOKEN env vars override these.
voice:
  app_id: ""
  access_token: ""
  language: zh-CN
"""


@dataclass
class Config:
    default_provider: str = "volc"
    cdp_url: str = "http://127.0.0.1:9222"
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    voice: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        return cls(
            default_provider=str(d.get("default_provider", "volc")),
            cdp_url=str(d.get("cdp_url", "http://127.0.0.1:9222")),
            providers=dict(d.get("providers") or {}),
            voice=dict(d.get("voice") or {}),
        )

    def provider_kwargs(self, key: str) -> dict[str, Any]:
        """Return kwargs for building `key` provider, with env vars taking precedence."""
        base = dict(self.providers.get(key) or {})
        # drop empty-string secrets so provider ctor falls back to env / raises helpfully.
        return {k: v for k, v in base.items() if v not in ("", None)}

    def apply_voice_env(self) -> None:
        """Push voice creds into os.environ if not already set."""
        for src_key, env_key in (
            ("app_id", "VOLC_APP_ID"),
            ("access_token", "VOLC_ACCESS_TOKEN"),
        ):
            v = self.voice.get(src_key) or ""
            if v and not os.environ.get(env_key):
                os.environ[env_key] = v


def ensure_config_exists() -> Path:
    """Write default template if config file doesn't exist. Returns config path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    return CONFIG_PATH


def load_config(path: Path | None = None) -> Config:
    p = path or CONFIG_PATH
    if not p.exists():
        return Config()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config at {p} must be a mapping, got {type(raw).__name__}")
    return Config.from_dict(raw)
