"""Basic import + parse tests (no Chrome/API needed)."""

import pytest

from sense_use.core.backend import ActionResult
from sense_use.core.event_bus import Event, EventBus
from sense_use.core.session import Session
from sense_use.models.volc import _parse_decision


def test_action_result_defaults():
    r = ActionResult(ok=True)
    assert r.ok is True
    assert r.detail == ""
    assert r.data == {}


def test_session_id_unique():
    ids = {Session().id for _ in range(10)}
    assert len(ids) == 10


def test_parse_decision_plain_json():
    d = _parse_decision('{"thought":"t","action":"click","args":{"x":1,"y":2},"label":"btn","done":false}')
    assert d.action == "click"
    assert d.args == {"x": 1, "y": 2}
    assert d.done is False


def test_parse_decision_code_fence():
    txt = '```json\n{"thought":"t","action":"done","args":{"answer":"hello"},"done":true}\n```'
    d = _parse_decision(txt)
    assert d.done is True
    assert d.args["answer"] == "hello"


def test_parse_decision_bad_raises():
    with pytest.raises(ValueError):
        _parse_decision("no json here")


@pytest.mark.asyncio
async def test_event_bus_fanout():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    await bus.publish(Event(kind="user_msg", session_id="s1", payload={"goal": "x"}))
    ev1 = await q1.get()
    ev2 = await q2.get()
    assert ev1.kind == "user_msg" == ev2.kind
    assert ev1.payload["goal"] == "x"
