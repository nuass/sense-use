"""Backend contract tests: coordinate space equality and sensitive payload keys."""

from sense_use.backends.adb_backend import AdbBackend
from sense_use.backends.desktop_backend import DesktopBackend
from sense_use.backends.vnc_backend import VncBackend


def test_desktop_sensitive_payload_keys():
    b = DesktopBackend()
    # x/y contract
    assert b.is_sensitive("click", {"x": 100, "y": 10}) is True
    assert b.is_sensitive("click", {"x": 100, "y": 500}) is False
    # label contract
    assert b.is_sensitive("click", {"label": "关机", "y": 500}) is True
    assert b.is_sensitive("click", {"label": "OK", "y": 500}) is False
    # text contract
    assert b.is_sensitive("type", {"text": "logout the user"}) is True
    # missing keys -> safe
    assert b.is_sensitive("click", {}) is False


def test_adb_sensitive_payload_keys():
    b = AdbBackend()
    assert b.is_sensitive("click", {"label": "支付宝支付"}) is True
    assert b.is_sensitive("click", {"text": "delete account"}) is True
    assert b.is_sensitive("click", {"label": "首页"}) is False
    assert b.is_sensitive("click", {}) is False


def test_vnc_sensitive_payload_keys():
    # Bypass __init__ since we don't want to instantiate a real VNC connection
    b = VncBackend.__new__(VncBackend)
    assert b.is_sensitive("click", {"label": "shutdown"}) is True
    assert b.is_sensitive("click", {"label": "格式化"}) is True
    assert b.is_sensitive("click", {"label": "Save"}) is False
