"""AAF Bridge — 配置读写 + 热键解析（纯函数，可单测）。

配置文件位于用户主目录 ~/.aaf-bridge/config.json（不污染公开仓库，不泄露本地路径）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".aaf-bridge"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "hotkey": "ctrl+alt+a",
    "current_project": "",
    "current_workspace": "",
    # Phase E / TASK-005-B（§6A.11 阈值配置化，默认 30s）：soft cancel 发出后等待
    # 多久才进入 force-eligible 状态。达到 timeout ≠ 自动 force kill——仍需显式
    # force 请求 + ownership verification（req 15/17）。
    "force_cancel_soft_timeout": 30,
}

# Win32 修饰键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MOD_NAMES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "meta": MOD_WIN,
}


class ConfigError(ValueError):
    pass


def default_config() -> dict:
    return dict(DEFAULT_CONFIG)


def load_config(path: Path | None = None) -> dict:
    """读取配置；文件不存在时返回默认值。"""
    p = path or CONFIG_PATH
    cfg = default_config()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in cfg:
                    if k in data:
                        cfg[k] = data[k]
        except (json.JSONDecodeError, OSError) as e:
            raise ConfigError(f"配置文件读取失败: {e}")
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> Path:
    """保存配置（创建目录）。"""
    p = path or CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def parse_hotkey(hotkey: str) -> tuple[int, int] | None:
    """解析 'ctrl+alt+a' → (modifiers, vk)。返回 None 表示无法解析。

    vk 支持单字母（A-Z、0-9）与常见键名（f1-f24 等）。
    """
    if not hotkey or not isinstance(hotkey, str):
        return None
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if len(parts) < 1:
        return None
    mods = 0
    key_part = None
    for p in parts:
        if p in _MOD_NAMES:
            mods |= _MOD_NAMES[p]
        else:
            if key_part is not None:
                return None  # 多个非修饰键 → 不支持
            key_part = p
    if key_part is None:
        return None
    if len(key_part) == 1 and key_part.isalnum():
        vk = ord(key_part.upper())
    elif re_fullmatch_key(key_part):
        vk = _FKEY_VK.get(key_part)
        if vk is None:
            return None
    else:
        return None
    return mods, vk


_FKEY_VK = {f"f{i}": 0x70 + i - 1 for i in range(1, 25)}


def re_fullmatch_key(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", name))


def describe_hotkey(mods: int, vk: int) -> str:
    names = []
    if mods & MOD_CONTROL:
        names.append("Ctrl")
    if mods & MOD_ALT:
        names.append("Alt")
    if mods & MOD_SHIFT:
        names.append("Shift")
    if mods & MOD_WIN:
        names.append("Win")
    if 0x70 <= vk <= 0x87:
        names.append(f"F{vk - 0x70 + 1}")
    else:
        ch = chr(vk)
        names.append(ch.upper() if ch.isalpha() else ch)
    return "+".join(names)
