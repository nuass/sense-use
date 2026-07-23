"""Provider registry — enumerates available VLM providers, with graceful
try-imports so optional SDK deps don't break the base install.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sense_use.models.base import ModelProvider


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    description: str
    factory: Callable[..., ModelProvider]
    params: list["ProviderParam"] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderParam:
    name: str
    label: str
    kind: str = "str"  # str / secret / int
    default: str | None = None
    env: str | None = None


_REGISTRY: dict[str, ProviderSpec] = {}


def register(spec: ProviderSpec) -> None:
    if spec.key in _REGISTRY:
        raise ValueError(f"provider {spec.key!r} already registered")
    _REGISTRY[spec.key] = spec


def get(key: str) -> ProviderSpec:
    if key not in _REGISTRY:
        raise KeyError(f"provider {key!r} not registered; known: {list(_REGISTRY)}")
    return _REGISTRY[key]


def all_specs() -> list[ProviderSpec]:
    return list(_REGISTRY.values())


def build(key: str, **kwargs) -> ModelProvider:
    return get(key).factory(**kwargs)


def _register_builtins() -> None:
    from sense_use.models.volc import VolcProvider

    register(
        ProviderSpec(
            key="volc",
            label="Volc doubao-seed-vision",
            description="火山方舟 doubao-seed 视觉推理，ARK_API_KEY.",
            factory=lambda **kw: VolcProvider(**kw),
            params=[
                ProviderParam("api_key", "ARK API key", kind="secret", env="ARK_API_KEY"),
                ProviderParam("model", "Model", default="doubao-seed-1-6-flash-250615"),
            ],
        )
    )

    try:
        import anthropic  # noqa: F401  # type: ignore
        from sense_use.models.claude import ClaudeProvider

        register(
            ProviderSpec(
                key="claude",
                label="Anthropic Claude (vision)",
                description="Anthropic Messages API. Needs `pip install anthropic` and ANTHROPIC_API_KEY.",
                factory=lambda **kw: ClaudeProvider(**kw),
                params=[
                    ProviderParam("api_key", "Anthropic API key", kind="secret", env="ANTHROPIC_API_KEY"),
                    ProviderParam("model", "Model", default="claude-sonnet-4-6"),
                ],
            )
        )
    except ImportError:
        pass

    try:
        import openai  # noqa: F401  # type: ignore
        from sense_use.models.openai import OpenAIProvider

        register(
            ProviderSpec(
                key="openai",
                label="OpenAI GPT-4o (vision)",
                description="OpenAI Chat Completions with vision. Needs `pip install openai`.",
                factory=lambda **kw: OpenAIProvider(**kw),
                params=[
                    ProviderParam("api_key", "OpenAI API key", kind="secret", env="OPENAI_API_KEY"),
                    ProviderParam("model", "Model", default="gpt-4o"),
                    ProviderParam("base_url", "Base URL (optional)", default=None, env="OPENAI_BASE_URL"),
                ],
            )
        )
    except ImportError:
        pass

    # Qwen local doesn't need an SDK (pure httpx). Always registered.
    from sense_use.models.qwen_local import QwenLocalProvider

    register(
        ProviderSpec(
            key="qwen_local",
            label="Qwen2.5-VL (local Ollama)",
            description="Local Ollama-compatible endpoint running qwen2.5-vl. Default http://localhost:11434.",
            factory=lambda **kw: QwenLocalProvider(**kw),
            params=[
                ProviderParam("endpoint", "Endpoint", default="http://localhost:11434/api/chat", env="OLLAMA_ENDPOINT"),
                ProviderParam("model", "Model", default="qwen2.5-vl:7b", env="QWEN_MODEL"),
            ],
        )
    )


_register_builtins()
