"""CLI entry — `sense-use` command."""

from __future__ import annotations

from pathlib import Path

import typer

from sense_use.config import ensure_config_exists, load_config
from sense_use.tui.app import run as run_tui

app = typer.Typer(
    add_completion=False,
    help="sense-use · open-source Computer + Mobile + Browser Use",
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback()
def _root(
    ctx: typer.Context,
    cdp_url: str = typer.Option(
        None,
        "--cdp",
        help="Chrome DevTools Protocol endpoint (overrides config).",
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="Which VLM provider to use: volc / claude / openai / qwen_local.",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.sense-use/config.yaml).",
    ),
) -> None:
    """Launch the TUI when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    if config is None:
        ensure_config_exists()
    cfg = load_config(config)
    cfg.apply_voice_env()

    effective_provider = provider or cfg.default_provider
    effective_cdp = cdp_url or cfg.cdp_url
    run_tui(cdp_url=effective_cdp, provider_key=effective_provider, config=cfg)


@app.command("config-path")
def config_path_cmd() -> None:
    """Print where the config file lives, creating a default if missing."""
    p = ensure_config_exists()
    typer.echo(str(p))


@app.command("providers")
def providers_cmd() -> None:
    """List available VLM providers (only those with their SDK installed)."""
    from sense_use.models.provider_registry import all_specs

    for spec in all_specs():
        typer.echo(f"{spec.key:<12} — {spec.label}")


if __name__ == "__main__":
    app()
