"""AAF Bridge — Workspace 校验与分类（Phase F / TASK-006，RW-003；纯函数可单测）。

设计（docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md §9）：
- TASK 声明的 Workspace 是 canonical 来源（req 1）；不依赖聊天上下文或猜测路径
- 分类结果驱动 Bridge 流程：
    SAME     = 与当前 workspace 相同 → 正常继续，不加额外确认（req 2）
    KNOWN    = 非当前但属于 recent_projects → 明确确认后切换（req 3）
    UNKNOWN  = 首次出现 → fail-safe 暂停 + 明确确认（req 4）
    INVALID  = 不满足 workspace contract → 拒绝并给出明确原因（req 5，fail closed）
- 本模块只分类/校验，不写任何文件；切换持久化唯一入口 = config.update_project

本模块不实现：目录扫描器（§9.2.4：候选只来自 recent_projects + TASK 声明）。
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config as cfg_mod

SAME = "SAME"
KNOWN = "KNOWN"
UNKNOWN = "UNKNOWN"
INVALID = "INVALID"

VALID_CLASSES = (SAME, KNOWN, UNKNOWN, INVALID)

# 安全校验拒绝：workspace 不得落在 Bridge 私有目录（~/.aaf-bridge）或其子目录内，
# 也不得是另一任务的 .aaf 运行目录——防止把执行链引到 Bridge 自己的状态目录。
BRIDGE_PRIVATE_DIR_NAMES = {".aaf-bridge"}


def check_workspace(workspace: str) -> tuple[bool, str]:
    """校验 TASK Workspace 是否满足 workspace contract。返回 (ok, reason)。

    fail closed：任一检查失败 → (False, 明确中文原因)。
    """
    ws = (workspace or "").strip()
    if not ws:
        return False, "Workspace 字段为空（malformed Workspace）"
    if "\x00" in ws:
        return False, "Workspace 包含 NUL 字符（malformed Workspace）"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in ws):
        return False, "Workspace 包含控制字符（malformed Workspace）"

    # 绝对路径要求（Windows 盘符 / UNC / 根路径）
    expanded = os.path.expandvars(os.path.expanduser(ws))
    if not os.path.isabs(expanded):
        return False, f"Workspace 必须是绝对路径: {ws!r}（malformed Workspace）"

    path = Path(expanded)
    if not path.exists():
        return False, f"路径不存在: {path}"
    if not path.is_dir():
        return False, f"路径不是目录: {path}"
    if not os.access(path, os.R_OK | os.X_OK):
        return False, f"无权限/不可访问: {path}"

    # 安全校验：Bridge 私有目录边界
    try:
        resolved = path.resolve()
    except OSError as exc:
        return False, f"安全校验失败（路径解析失败）: {path} ({exc})"
    bridge_dir = (Path(os.environ.get("AAF_BRIDGE_DIR") or cfg_mod.CONFIG_DIR)).resolve()
    try:
        resolved.relative_to(bridge_dir)
        return False, f"安全校验失败：路径位于 Bridge 私有目录内: {path}"
    except ValueError:
        pass
    # 路径深层含有 .aaf-bridge 段（即使不是直接子目录）
    if any(part in BRIDGE_PRIVATE_DIR_NAMES for part in resolved.parts):
        return False, f"安全校验失败：路径包含 Bridge 私有目录段: {path}"
    return True, ""


def classify_workspace(task_workspace: str, current_workspace: str, known: list[str] | None = None) -> str:
    """分类 TASK workspace：SAME / KNOWN / UNKNOWN / INVALID。"""
    if not check_workspace(task_workspace)[0]:
        return INVALID
    if current_workspace and cfg_mod.same_workspace(task_workspace, current_workspace):
        return SAME
    for ws in known or []:
        if ws and cfg_mod.same_workspace(task_workspace, ws):
            return KNOWN
    return UNKNOWN


def target_project_name(task_workspace: str, current_project: str, current_workspace: str, known: list[dict] | None = None) -> str:
    """目标项目展示名：recent_projects 命中 → 记录名；否则路径 basename。"""
    ws = (task_workspace or "").strip()
    if ws and current_workspace and cfg_mod.same_workspace(ws, current_workspace):
        return current_project or cfg_mod.project_name_for(ws)
    for entry in known or []:
        if isinstance(entry, dict) and cfg_mod.same_workspace(str(entry.get("workspace") or ""), ws):
            return str(entry.get("name") or "") or cfg_mod.project_name_for(ws)
    return cfg_mod.project_name_for(ws)
