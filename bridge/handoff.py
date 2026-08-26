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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as cfg_mod
from .launcher import RunInfo

from ai_agent_framework.task_archive import archived_report_path

HANDOFF_BEGIN = "AAF_PLANNER_HANDOFF_BEGIN"
HANDOFF_END = "AAF_PLANNER_HANDOFF_END"

NO_LAST_RUN = "NO_LAST_RUN"
REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
GIT_NOT_APPLICABLE = "NOT_APPLICABLE"
SYNC_UNKNOWN = "UNKNOWN"
SYNC_SYNCED = "SYNCED"
SYNC_AHEAD = "AHEAD"
SYNC_BEHIND = "BEHIND"
SYNC_DIVERGED = "DIVERGED"


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


# ---------- Git 只读快照 ----------

def _git(args: list[str], workspace: str, timeout: float = 10.0) -> str:
    """执行只读 git 命令，返回 stdout（strip）；失败返回 ''。"""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if r.returncode != 0:
            return ""
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def compute_sync(ahead: int, behind: int, has_upstream: bool) -> str:
    """纯判定：ahead/behind → SYNCED / AHEAD / BEHIND / DIVERGED / UNKNOWN。"""
    if not has_upstream:
        return SYNC_UNKNOWN
    if ahead == 0 and behind == 0:
        return SYNC_SYNCED
    if ahead > 0 and behind == 0:
        return SYNC_AHEAD
    if behind > 0 and ahead == 0:
        return SYNC_BEHIND
    return SYNC_DIVERGED


@dataclass
class GitClosure:
    is_git_repo: bool
    branch: str = ""
    local_head: str = ""
    remote_head: str = ""
    ahead: int = 0
    behind: int = 0
    working_tree: str = ""
    remote_sync: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_git_repo": self.is_git_repo,
            "branch": self.branch,
            "local_head": self.local_head,
            "remote_head": self.remote_head,
            "ahead": self.ahead,
            "behind": self.behind,
            "working_tree": self.working_tree,
            "remote_sync": self.remote_sync,
        }


def git_snapshot(workspace: str) -> GitClosure:
    """只读 Git 状态快照。非 git 仓库 → is_git_repo=False（调用方标记 NOT_APPLICABLE）。

    只读命令：rev-parse / branch --show-current / status --porcelain /
    rev-list --left-right --count / rev-parse @{u} / rev-parse <upstream>。
    不执行 fetch / 任何写操作。
    """
    is_git = _git(["rev-parse", "--is-inside-work-tree"], workspace) == "true"
    if not is_git:
        return GitClosure(is_git_repo=False, remote_sync=SYNC_UNKNOWN)

    branch = _git(["branch", "--show-current"], workspace)
    local_head = _git(["rev-parse", "HEAD"], workspace)
    working_tree = "clean" if _git(["status", "--porcelain"], workspace) == "" else "dirty"

    upstream = _git(["rev-parse", "--abbrev-ref", "@{u}"], workspace)
    has_upstream = bool(upstream)
    remote_head = ""
    ahead = behind = 0
    if has_upstream:
        # 本地已知的 remote-tracking 引用（不访问网络）
        remote_head = _git(["rev-parse", upstream], workspace)
        counts = _git(["rev-list", "--left-right", "--count", "HEAD...@{u}"], workspace)
        parts = counts.split()
        if len(parts) == 2:
            try:
                ahead, behind = int(parts[0]), int(parts[1])
            except ValueError:
                ahead = behind = 0
    return GitClosure(
        is_git_repo=True,
        branch=branch,
        local_head=local_head,
        remote_head=remote_head,
        ahead=ahead,
        behind=behind,
        working_tree=working_tree,
        remote_sync=compute_sync(ahead, behind, has_upstream),
    )


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
