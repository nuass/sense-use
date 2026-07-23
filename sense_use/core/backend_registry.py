"""Backend registry — the TUI's `new_target` modal reads this list."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sense_use.core.backend import Backend


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    label: str
    description: str
    factory: Callable[..., Awaitable[Backend]]
    params: list["ParamSpec"] = field(default_factory=list)


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    kind: str = "str"  # str / int / secret / choice
    default: Any = None
    required: bool = False
    choices: tuple[str, ...] = ()


_REGISTRY: dict[str, BackendSpec] = {}


def register(spec: BackendSpec) -> None:
    if spec.kind in _REGISTRY:
        raise ValueError(f"backend {spec.kind!r} already registered")
    _REGISTRY[spec.kind] = spec


def get(kind: str) -> BackendSpec:
    if kind not in _REGISTRY:
        raise KeyError(f"backend {kind!r} not registered; known: {list(_REGISTRY)}")
    return _REGISTRY[kind]


def all_specs() -> list[BackendSpec]:
    return list(_REGISTRY.values())


def _register_builtins() -> None:
    from sense_use.backends.browser_backend import BrowserBackend

    async def _browser_factory(cdp_url: str = "http://127.0.0.1:9222") -> Backend:
        b = BrowserBackend(cdp_url=cdp_url)
        await b.start()
        return b

    register(
        BackendSpec(
            kind="browser",
            label="Browser (Chrome CDP)",
            description="Connect to a running Chrome with --remote-debugging-port. Reuses your logged-in session.",
            factory=_browser_factory,
            params=[
                ParamSpec("cdp_url", "CDP URL", default="http://127.0.0.1:9222", required=True),
            ],
        )
    )

    try:
        # Only expose when browser-use actually imports.
        import browser_use  # noqa: F401  # type: ignore
        from sense_use.backends.browser_use_backend import BrowserUseBackend

        async def _browser_use_factory(cdp_url: str = "http://127.0.0.1:9222") -> Backend:
            b = BrowserUseBackend(cdp_url=cdp_url)
            await b.start()
            return b

        register(
            BackendSpec(
                kind="browser-use",
                label="Browser (browser-use, DOM-aware)",
                description="Wraps the browser-use library for DOM-aware click_by_index and content extraction. Requires `pip install browser-use`.",
                factory=_browser_use_factory,
                params=[
                    ParamSpec("cdp_url", "CDP URL", default="http://127.0.0.1:9222", required=True),
                ],
            )
        )
    except ImportError:
        pass

    try:
        from sense_use.backends.adb_backend import AdbBackend

        async def _adb_factory(serial: str | None = None) -> Backend:
            b = AdbBackend(serial=serial)
            await b.start()
            return b

        register(
            BackendSpec(
                kind="adb",
                label="Android (ADB)",
                description="USB or wireless Android device. Requires adb on PATH.",
                factory=_adb_factory,
                params=[
                    ParamSpec("serial", "Device serial (optional)", default=None),
                ],
            )
        )
    except ImportError:
        pass

    try:
        from sense_use.backends.desktop_backend import DesktopBackend

        async def _desktop_factory() -> Backend:
            b = DesktopBackend()
            await b.start()
            return b

        register(
            BackendSpec(
                kind="desktop",
                label="Local Desktop (pyautogui)",
                description="Control this machine's screen and keyboard. Grant Accessibility permission on macOS.",
                factory=_desktop_factory,
            )
        )
    except ImportError:
        pass

    try:
        from sense_use.backends.vnc_backend import VncBackend

        async def _vnc_factory(host: str, port: int = 5900, password: str = "") -> Backend:
            b = VncBackend(host=host, port=port, password=password)
            await b.start()
            return b

        register(
            BackendSpec(
                kind="vnc",
                label="Remote (VNC)",
                description="Any VNC-reachable machine. host:port + optional password.",
                factory=_vnc_factory,
                params=[
                    ParamSpec("host", "Host", required=True),
                    ParamSpec("port", "Port", kind="int", default=5900),
                    ParamSpec("password", "Password", kind="secret", default=""),
                ],
            )
        )
    except ImportError:
        pass


_register_builtins()
