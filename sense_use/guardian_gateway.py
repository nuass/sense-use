"""Guardian HTTP Gateway — v0.3.4 企业级敏感操作审批前置层。

抽离自 TaskRunner.is_sensitive() + confirm_needed 内联逻辑。作为独立
HTTP 服务，worker 通过 POST /guardian/check 查询是否允许执行敏感
操作。支持 3 种模式：

1. **local**（默认）：Gateway 内嵌在 Planner 进程里通过 `asyncio.Queue`
   直通 TUI 弹框。用户 Y/N → 实时返回给 worker。

2. **sso**（企业版）：通过 OIDC/JWT 调用公司内部审批系统，支持
   审批流、审计日志、分级权限。

3. **queue**（异步工单）：对高危操作生成 JIRA/飞书工单，轮询直到
   审批完成或超时。

Wire Protocol (HTTP)
--------------------
Request:
```json
{
    "session_id": "abc123",
    "pane_id": "pane-0",
    "action": "click",
    "label": "Delete All button",
    "args": {"x": 120, "y": 340, "selector": "[data-testid='delete-all']"},
    "backend_kind": "browser",
    "screenshot_b64": "iVBORw0KGgoAAAANSUh..." (optional)
}
```

Response:
```json
{"allow": true, "reason": "local user confirmed", "approved_by": "tui:john"}
{"allow": false, "reason": "automatically blocked: delete_all is sensitive", "approved_by": "rule:default"}
```
"""

from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class CheckRequest(BaseModel):
    session_id: str
    pane_id: str
    action: str
    label: str
    args: dict[str, Any]
    backend_kind: str
    screenshot_b64: str | None = None


class CheckResponse(BaseModel):
    allow: bool
    reason: str
    approved_by: str


# ---- local mode callback ---------------------------------------------------

@dataclass
class PendingConfirm:
    session_id: str
    pane_id: str
    action: str
    label: str
    args: dict[str, Any]
    backend_kind: str
    screenshot_bytes: bytes | None
    future: asyncio.Future[tuple[bool, str]]


ConfirmCallback = Callable[[PendingConfirm], None]


# Actions that are refused outright — no human is asked, because there is no
# legitimate reason for the model to reach for them.
_DESTRUCTIVE_ACTIONS = ("delete", "drop", "truncate")

# A label matching this is worth a human's attention: money movement,
# irreversible removal, or losing the session. Mirrors the union of the
# per-backend patterns these rules were centralized from.
_SENSITIVE_LABEL = re.compile(
    r"(pay|checkout|purchase|delete|remove|uninstall|wipe|logout|sign\s?out|"
    r"confirm\s?order|transfer|"
    r"支付|付款|转账|删除|卸载|注销|退出登录|确认下单|确认支付)",
    re.IGNORECASE,
)


def _needs_human(action: str, args: dict[str, Any], label: str) -> bool:
    """Whether this action should block on a human decision.

    Everything else runs unattended. Prompting on every click would train
    the operator to reflexively approve, which defeats the point of asking.
    """
    if _SENSITIVE_LABEL.search(label or ""):
        return True
    if _SENSITIVE_LABEL.search(str(args.get("text", "") or "")):
        return True
    # macOS menu bar strip — a stray click here can hit system-level items.
    if action == "click" and int(args.get("y", 9999) or 9999) <= 30:
        return True
    return False


def _blocked_by_default(action: str) -> tuple[bool, str]:
    """Built-in safety rules: block actions known to be destructive."""
    if action in _DESTRUCTIVE_ACTIONS:
        return False, "automatically blocked: destructive database action"
    return True, "no matching rule — default allow"


def create_app(
    mode: str = "local",
    confirm_callback: ConfirmCallback | None = None,
) -> FastAPI:
    """Create the Guardian Gateway FastAPI app.

    Parameters
    ----------
    mode:
        - "local": use in-process callback queue, TUI pops modal
        - "sso": enterprise SSO approval (stub)
        - "queue": async ticket-based approval (stub)
    confirm_callback:
        Called when mode == "local" and user confirmation is required.
        Callback MUST resolve `PendingConfirm.future` with (ok, reason).
    """
    app = FastAPI(title="Guardian Gateway", version="0.3.4")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "mode": mode}

    @app.post("/guardian/check", response_model=CheckResponse)
    async def guardian_check(req: CheckRequest) -> CheckResponse:
        # First apply built-in rules.
        allowed, rule_reason = _blocked_by_default(req.action)
        if not allowed:
            return CheckResponse(
                allow=False,
                reason=rule_reason,
                approved_by="rule:default",
            )

        if mode == "local":
            if not _needs_human(req.action, req.args, req.label):
                return CheckResponse(
                    allow=True,
                    reason="not sensitive — auto-approved",
                    approved_by="rule:auto",
                )
            if confirm_callback is None:
                raise HTTPException(status_code=500, detail="local mode requires confirm_callback")
            screenshot_bytes = (
                base64.b64decode(req.screenshot_b64) if req.screenshot_b64 else None
            )
            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            pc = PendingConfirm(
                session_id=req.session_id,
                pane_id=req.pane_id,
                action=req.action,
                label=req.label,
                args=req.args,
                backend_kind=req.backend_kind,
                screenshot_bytes=screenshot_bytes,
                future=fut,
            )
            confirm_callback(pc)
            ok, reason = await fut
            return CheckResponse(
                allow=ok,
                reason=reason,
                approved_by="tui:local_user" if ok else "tui:local_rejected",
            )

        elif mode in ("sso", "queue"):
            # Enterprise stubs — implement in v0.4+ with actual SSO client.
            return CheckResponse(
                allow=True,
                reason=f"{mode} mode is stub — always allow",
                approved_by=f"gateway:{mode}_stub",
            )

        raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")

    return app


# ---- Standalone server CLI -------------------------------------------------


def _start_standalone_server(port: int = 8775, mode: str = "local") -> None:
    """Start Uvicorn server for enterprise deployment."""
    import uvicorn

    app = create_app(mode=mode)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8775
    mode = sys.argv[2] if len(sys.argv) > 2 else "local"
    _start_standalone_server(port, mode)
