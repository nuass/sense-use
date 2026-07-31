"""Agent main loop — observe → think → act, driven by (Backend, ModelProvider)."""

from __future__ import annotations

import asyncio

from sense_use.core.backend import Backend
from sense_use.core.event_bus import Event, EventBus
from sense_use.core.session import Session
from sense_use.models.base import ModelDecision, ModelProvider


GuardianCheckFn = object


class TaskRunner:
    def __init__(
        self,
        session: Session,
        backend: Backend,
        provider: ModelProvider,
        bus: EventBus,
    ) -> None:
        self.session = session
        self.backend = backend
        self.provider = provider
        self.bus = bus
        self._history: list[dict] = []
        self._pending_confirm: asyncio.Future[bool] | None = None
        # v0.3.4 Guardian split: if set, use this async fn instead
        # of backend.is_sensitive() + local confirm. Signature:
        # async def guardian_check(action: str, args: dict, label: str,
        #                          sess: Session) -> tuple[allow: bool, reason: str]
        self.guardian_check: GuardianCheckFn | None = None

    async def resolve_confirm(self, ok: bool) -> None:
        if self._pending_confirm and not self._pending_confirm.done():
            self._pending_confirm.set_result(ok)

    async def run(self) -> str:
        sess = self.session
        sess.step = 0
        await self._emit("user_msg", {"goal": sess.goal})

        try:
            while sess.step < sess.max_steps and not sess.done:
                sess.step += 1

                shot = await self.backend.screenshot()
                await self._emit("observe", {"step": sess.step, "screenshot_bytes": shot})

                page_text = None
                if hasattr(self.backend, "read_text"):
                    try:
                        page_text = await self.backend.read_text()  # type: ignore[attr-defined]
                    except Exception:
                        page_text = None

                decision = await self.provider.decide(
                    goal=sess.goal,
                    history=self._history,
                    screenshot_png=shot,
                    page_text=page_text,
                )
                await self._emit(
                    "think",
                    {"step": sess.step, "thought": decision.thought,
                     "action": decision.action, "args": decision.args,
                     "label": decision.label, "done": decision.done},
                )

                if decision.done or decision.action == "done":
                    sess.done = True
                    answer = decision.args.get("answer", decision.thought)
                    await self._emit("done", {"answer": answer})
                    return str(answer)

                sensitive_args = {**decision.args, "label": decision.label}
                if self.guardian_check is not None:
                    # v0.3.4 Guardian Gateway: HTTP round-trip
                    ok, reason = await self.guardian_check(
                        decision.action, sensitive_args, decision.label, self.session
                    )
                else:
                    # Pre-v0.3.4: backend-local rule + TUI confirm
                    ok = True
                    if self.backend.is_sensitive(decision.action, sensitive_args):
                        self._pending_confirm = asyncio.get_event_loop().create_future()
                        await self._emit("confirm_needed", {
                            "action": decision.action, "args": decision.args, "label": decision.label,
                        })
                        ok = await self._pending_confirm
                        await self._emit("confirm_result", {"ok": ok})
                if not ok:
                    self._history.append(
                        {"action": decision.action, "args": decision.args, "result": "user_rejected"}
                    )
                    continue

                result = await self._dispatch(decision)
                await self._emit("act_result", {
                    "step": sess.step, "action": decision.action,
                    "ok": result.ok, "detail": result.detail,
                })
                self._history.append({
                    "action": decision.action, "args": decision.args,
                    "result": "ok" if result.ok else f"fail:{result.detail}",
                })

            if not sess.done:
                await self._emit("error", {"reason": "max_steps_exhausted", "steps": sess.step})
                return "max_steps_exhausted"
            return "done"

        except Exception as e:  # noqa: BLE001
            await self._emit("error", {"reason": repr(e)})
            raise

    async def _dispatch(self, d: ModelDecision):
        b = self.backend
        args = d.args
        from sense_use.core.backend import ActionResult

        def _missing(*keys: str) -> ActionResult | None:
            missing = [k for k in keys if k not in args]
            if missing:
                return ActionResult(
                    ok=False,
                    detail=f"missing args {missing} for {d.action}; got {list(args.keys())}",
                )
            return None

        match d.action:
            case "click":
                miss = _missing("x", "y")
                if miss:
                    return miss
                return await b.click(int(args["x"]), int(args["y"]))
            case "type":
                miss = _missing("text")
                if miss:
                    return miss
                return await b.type_text(str(args["text"]))
            case "swipe":
                miss = _missing("x1", "y1", "x2", "y2")
                if miss:
                    return miss
                return await b.swipe(
                    int(args["x1"]), int(args["y1"]),
                    int(args["x2"]), int(args["y2"]),
                    int(args.get("duration_ms", 300)),
                )
            case "key":
                miss = _missing("name")
                if miss:
                    return miss
                try:
                    return await b.key(str(args["name"]))
                except Exception as exc:  # noqa: BLE001
                    return ActionResult(ok=False, detail=f"key press failed: {exc}")
            case "goto":
                miss = _missing("url")
                if miss:
                    return miss
                if hasattr(b, "goto"):
                    return await b.goto(str(args["url"]))  # type: ignore[attr-defined]
                return ActionResult(ok=False, detail="backend does not support goto")
            case "read":
                if hasattr(b, "read_text"):
                    text = await b.read_text()  # type: ignore[attr-defined]
                    return ActionResult(ok=True, detail=f"read {len(text)} chars", data={"text": text[:4000]})
                return ActionResult(ok=False, detail="backend does not support read")
            case _:
                return ActionResult(ok=False, detail=f"unknown action {d.action}")

    async def _emit(self, kind, payload):
        await self.bus.publish(Event(kind=kind, session_id=self.session.id, payload=payload))
