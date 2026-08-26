"""AAF Bridge — Copy Last Report + Planner Handoff（纯逻辑，可单测）。

设计：
- REPORT.md = 执行结果 Source of Truth（Bridge 不改写任务结论）
- Latest Closure Snapshot = 当前机器 Git/交付状态快照（只读，实时）
- Planner Handoff = REPORT 原文 + Closure Snapshot

数据入口：~/.aaf-bridge/last_run.json（由 launcher 持久化）。
Git 检查全部只读；禁止 fetch/写操作（避免网络副作用）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config as cfg_mod
from .launcher import RunInfo

from ai_agent_framework.git_status import (  # re-export（实现移到 framework 层，Session 共用）
    GIT_NOT_APPLICABLE,
    SYNC_AHEAD,
    SYNC_BEHIND,
    SYNC_DIVERGED,
    SYNC_SYNCED,
    SYNC_UNKNOWN,
    GitClosure,
    compute_sync,
    git_snapshot,
)
from ai_agent_framework.task_archive import archived_report_path

HANDOFF_BEGIN = "AAF_PLANNER_HANDOFF_BEGIN"
HANDOFF_END = "AAF_PLANNER_HANDOFF_END"

NO_LAST_RUN = "NO_LAST_RUN"
REPORT_NOT_FOUND = "REPORT_NOT_FOUND"


# ---------- last_run / REPORT ----------

def last_run_path() -> Path:
    return cfg_mod.CONFIG_DIR / "last_run.json"


def load_last_run() -> RunInfo | None:
    """读取 last_run.json；缺失/损坏返回 None（调用方提示 NO_LAST_RUN）。"""
    p = last_run_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return RunInfo(**data)
    except (json.JSONDecodeError, TypeError, OSError):
        return None


def read_report(report_path: str | None) -> str | None:
    """读取正式 REPORT.md 正文；缺失返回 None（调用方提示 REPORT_NOT_FOUND）。

    兼容归档：原路径不存在时，尝试 .aaf/archive/<Task-ID>/ 变体兜底
    （任务归档后 Bridge Copy Last Report 仍然有效，不修改 last_run.json）。
    """
    if not report_path:
        return None
    p = Path(report_path)
    if not p.exists():
        archived = archived_report_path(p)
        if archived is not None and archived.exists():
            p = archived
        else:
            return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------- Git 只读快照（实现位于 ai_agent_framework/git_status.py，此处 re-export） ----------

# ---------- Handoff 构建 ----------

def build_handoff(last: RunInfo, report_text: str, closure: GitClosure) -> str:
    """组合 Planner Handoff 文本（REPORT 原文 + Latest Closure Snapshot）。"""
    if closure.is_git_repo:
        git_section = (
            f"Git Repository: yes\n"
            f"Git Branch: {closure.branch or '(detached)'}\n"
            f"Local HEAD: {closure.local_head or 'n/a'}\n"
            f"Remote HEAD: {closure.remote_head or 'n/a'}\n"
            f"Ahead/Behind: {closure.ahead}/{closure.behind}\n"
            f"Working Tree: {closure.working_tree}\n"
            f"Remote Sync: {closure.remote_sync}"
        )
    else:
        git_section = "Git Status: NOT_APPLICABLE"

    parts = [
        HANDOFF_BEGIN,
        "",
        f"Task: {last.task_id}",
        f"Report Path: {last.report_path or REPORT_NOT_FOUND}",
        f"Framework Result: {last.result}",
        f"Exit Code: {last.exit_code if last.exit_code is not None else 'n/a'}",
        "",
        "## Execution Report",
        report_text,
        "",
        "## Latest Closure State",
        git_section,
        HANDOFF_END,
    ]
    return "\n".join(parts)
