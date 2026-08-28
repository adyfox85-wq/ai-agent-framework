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
    # Phase F / TASK-006（RW-003，设计 §9.2.3）：最近使用项目列表（schema 提案落地）。
    # 每条 {"name", "workspace", "last_used"}；按 last_used 倒序，上限 RECENT_PROJECTS_LIMIT。
    # 作用：① 已知 workspace 判定（候选只来自 recent_projects + TASK 声明，不扫描磁盘 §9.2.4）；
    # ② 切换确认窗展示目标项目名。
    "recent_projects": [],
}

# 设计 §9.2.3：第一版上限 5 条，按 last_used 倒序。
RECENT_PROJECTS_LIMIT = 5

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


# ---------- Phase F / TASK-006（RW-003）：项目切换与持久化 ----------

def normalize_workspace(ws: str) -> str:
    """workspace 规范化（比较用）：normpath + normcase（Windows 大小写不敏感）。"""
    return os.path.normcase(os.path.normpath(ws))


def same_workspace(a: str, b: str) -> bool:
    """两个 workspace 是否同一（规范化比较）。空值永不相等。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    return normalize_workspace(a) == normalize_workspace(b)


def project_name_for(workspace: str) -> str:
    """从路径派生展示用项目名（无 recent_projects 记录时）。空/非法 → 空串。"""
    ws = (workspace or "").strip()
    if not ws:
        return ""
    return Path(ws).name


def known_workspaces(path: Path | None = None) -> list[str]:
    """已知 workspace 列表 = recent_projects 中全部 workspace（按 last_used 倒序）。

    注意：可能包含 current（切换过的项目都在 recent_projects 中）；分类时
    SAME 优先判定（classify_workspace 先比 current 再查 known），故无冲突。
    """
    cfg = load_config(path)
    out: list[str] = []
    for entry in cfg.get("recent_projects") or []:
        if not isinstance(entry, dict):
            continue
        ws = str(entry.get("workspace") or "").strip()
        if ws and not any(same_workspace(ws, w) for w in out):
            out.append(ws)
    return out


def update_project(project_name: str, workspace: str, path: Path | None = None) -> dict:
    """确认切换后持久化当前项目（设计 §9.2.2/§9.2.5；唯一写入点）。

    - 更新 current_project / current_workspace
    - 更新 recent_projects：去重（按规范化 workspace）→ 置顶 → 上限 RECENT_PROJECTS_LIMIT
    - 原子保存（tmp + os.replace）；失败抛 ConfigError
    - 返回更新后的完整配置 dict
    """
    cfg = load_config(path)
    ws = (workspace or "").strip()
    cfg["current_project"] = (project_name or project_name_for(ws) or "").strip()
    cfg["current_workspace"] = ws

    now = datetime_now_iso()
    entries: list[dict] = []
    seen: list[str] = []
    for entry in cfg.get("recent_projects") or []:
        if not isinstance(entry, dict):
            continue
        ews = str(entry.get("workspace") or "").strip()
        # 去重：与本次目标 workspace 相同（旧记录被新记录取代）或已在保留列表
        if not ews or same_workspace(ews, ws) or any(same_workspace(ews, s) for s in seen):
            continue
        seen.append(ews)
        entries.append(dict(entry))
    entries.insert(0, {"name": cfg["current_project"], "workspace": ws, "last_used": now})
    cfg["recent_projects"] = entries[:RECENT_PROJECTS_LIMIT]
    save_config(cfg, path)
    return cfg


def datetime_now_iso() -> str:
    """recent_projects.last_used 时间戳（本地时间 ISO，无时区后缀——与既有 config 契约一致）。"""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")
