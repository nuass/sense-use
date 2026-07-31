"""Guardian Gateway client — runs in the worker subprocess.

Worker side of v0.3.4 Guardian split: instead of calling
``backend.is_sensitive()`` directly, the worker POSTs to the gateway
and waits for the allow/deny response.

This creates a clear security boundary:
- All sensitive operation decisions are centralized
- Audit logs live in one place
- Enterprise SSO approval can be added without touching agent code
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


GUARDIAN_DEFAULT_URL = "http://127.0.0.1:8775"


@dataclass
class GuardianResult:
    allow: bool
    reason: str
    approved_by: str


class GuardianClient:
    def __init__(self, base_url: str = GUARDIAN_DEFAULT_URL, timeout: float = 300.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def check(
        self,
        session_id: str,
        pane_id: str,
        action: str,
        label: str,
        args: dict,
        backend_kind: str,
        screenshot_bytes: bytes | None = None,
    ) -> GuardianResult:
        """Ask the Guardian Gateway if this action is allowed to proceed.

        Blocks until approval comes back (could be instant via rule,
        or take minutes if pending SSO / manager approval).
        """
        payload = {
            "session_id": session_id,
            "pane_id": pane_id,
            "action": action,
            "label": label,
            "args": args,
            "backend_kind": backend_kind,
        }
        if screenshot_bytes is not None:
            payload["screenshot_b64"] = base64.b64encode(screenshot_bytes).decode("ascii")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/guardian/check", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return GuardianResult(
                allow=data["allow"],
                reason=data["reason"],
                approved_by=data["approved_by"],
            )


# ---- Local-only fallback ---------------------------------------------------


class PassthroughGuardian:
    """No HTTP — just ask the backend.is_sensitive() directly.

    Fallback for when the gateway is not running (e.g. local development).
    Always approves non-sensitive actions; for sensitive ones this raises
    NotImplementedError — you MUST use the HTTP gateway with TUI callback.
    """

    def __init__(self, backend_is_sensitive_fn) -> None:
        self._is_sensitive = backend_is_sensitive_fn

    async def check(
        self,
        session_id: str,
        pane_id: str,
        action: str,
        label: str,
        args: dict,
        backend_kind: str,
        screenshot_bytes: bytes | None = None,
    ) -> GuardianResult:
        sensitive = self._is_sensitive(action, args)
        if not sensitive:
            return GuardianResult(allow=True, reason="not sensitive", approved_by="backend:rule")
        # Sensitive without HTTP gateway = don't execute.
        raise NotImplementedError(
            f"sensitive action '{action}' requires Guardian HTTP gateway "
            "(run sense_use.guardian_gateway on port 8775)"
        )
