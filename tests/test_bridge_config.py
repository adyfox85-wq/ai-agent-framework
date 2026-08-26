"""AAF Bridge — config 读写 + 热键解析测试。"""
from pathlib import Path
import pytest

from bridge.config import (
    default_config,
    load_config,
    save_config,
    parse_hotkey,
    describe_hotkey,
    ConfigError,
    MOD_CONTROL,
    MOD_ALT,
    MOD_SHIFT,
    MOD_WIN,
)


def test_default_config():
    cfg = default_config()
    assert cfg["hotkey"] == "ctrl+alt+a"
    assert cfg["current_project"] == ""
    assert cfg["current_workspace"] == ""


def test_load_missing_returns_default(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg == default_config()


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    save_config({"hotkey": "ctrl+shift+b", "current_project": "P", "current_workspace": "W"}, p)
    cfg = load_config(p)
    assert cfg["hotkey"] == "ctrl+shift+b"
    assert cfg["current_project"] == "P"
    assert cfg["current_workspace"] == "W"


def test_load_invalid_json_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_parse_hotkey_default():
    assert parse_hotkey("ctrl+alt+a") == (MOD_CONTROL | MOD_ALT, ord("A"))


def test_parse_hotkey_variants():
    assert parse_hotkey("Ctrl+Shift+B") == (MOD_CONTROL | MOD_SHIFT, ord("B"))
    assert parse_hotkey("alt+F1") == (MOD_ALT, 0x70)
    assert parse_hotkey("win+9") == (MOD_WIN, ord("9"))


def test_parse_hotkey_invalid():
    assert parse_hotkey("") is None
    assert parse_hotkey("a+b") is None  # 多个非修饰键不支持
    assert parse_hotkey("ctrl+") is None
    assert parse_hotkey("ctrl+shift+alt+win+") is None  # 无键
    assert parse_hotkey(None) is None


def test_parse_hotkey_duplicate_modifier_ok():
    # 重复修饰键无害：ctrl+ctrl+a == ctrl+a
    assert parse_hotkey("ctrl+ctrl+a") == (MOD_CONTROL, ord("A"))


def test_describe_hotkey():
    assert describe_hotkey(MOD_CONTROL | MOD_ALT, ord("A")) == "Ctrl+Alt+A"
    assert describe_hotkey(MOD_ALT, 0x70) == "Alt+F1"
    assert describe_hotkey(MOD_SHIFT, 0x7B) == "Shift+F12"
