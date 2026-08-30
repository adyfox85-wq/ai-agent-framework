"""AI Agent Framework — 只读 Git 状态快照（Bridge handoff 与 Session Continuity 共用）。

只读命令：rev-parse / branch --show-current / status --porcelain /
rev-list --left-right --count / rev-parse @{u} / rev-parse <upstream>。
不执行 fetch / 任何写操作（避免网络副作用）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from .subprocess_utils import no_console_kwargs

GIT_NOT_APPLICABLE = "NOT_APPLICABLE"
SYNC_UNKNOWN = "UNKNOWN"
SYNC_SYNCED = "SYNCED"
SYNC_AHEAD = "AHEAD"
SYNC_BEHIND = "BEHIND"
SYNC_DIVERGED = "DIVERGED"


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
            **no_console_kwargs(),
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
    """只读 Git 状态快照。非 git 仓库 → is_git_repo=False（调用方标记 NOT_APPLICABLE）。"""
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
