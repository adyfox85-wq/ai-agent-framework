"""AI Agent Framework — 最小、正式、可复用 Session Continuity。

目标：
同一个项目内的长会话切换时，基于正式项目状态与近期任务结果，
生成一套"新 Session 承接材料"（SESSION_SUMMARY.md + NEXT_SESSION_START.md）。

边界：
- 显式 rollover 触发（不在每个 TASK 后自动生成）
- 确定性模板 + 正式状态数据（不调用 LLM / Agent）
- 有界上下文（近期相关任务，不扫描全部历史）
- 缺少数据明确写 UNKNOWN，不猜测
- 不修改 task.json.status；不自动创建下一 TASK / ChatGPT 会话

目录：
<Workspace>\.aaf\sessions\current\        ← 当前 Session artifact
<Workspace>\.aaf\sessions\archive\<sid>\  ← 历史 Session artifact
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .git_status import GitClosure, git_snapshot
from .task_archive import find_report_path

SESSION_DIR = "sessions"
CURRENT_DIR = "current"
ARCHIVE_DIR = "archive"
MAX_RECENT_TASKS = 3  # 有界上下文：最多纳入最近 N 个任务

UNKNOWN = "UNKNOWN"


class SessionError(RuntimeError):
    """rollover 失败（不静默）。"""


def session_id(now: datetime | None = None) -> str:
    """稳定、可排序的 Session ID：YYYYMMDD-HHMMSS。"""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def sessions_root(workspace: Path | str) -> Path:
    return Path(workspace) / ".aaf" / SESSION_DIR


def current_dir(workspace: Path | str) -> Path:
    return sessions_root(workspace) / CURRENT_DIR


def session_archive_dir(workspace: Path | str) -> Path:
    return sessions_root(workspace) / ARCHIVE_DIR


def meta_path(workspace: Path | str) -> Path:
    return current_dir(workspace) / "session.json"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _section(project_state: str, heading: str) -> str:
    """从 PROJECT_STATE.md 提取指定节（## 或 # 标题 + 后续非空行）；缺失 → ''。"""
    pat = re.compile(
        r"(?im)^[ \t]*(?:#{1,3}[ \t]+)" + re.escape(heading) + r"[ \t]*$"
    )
    m = pat.search(project_state)
    if not m:
        return ""
    lines = []
    for line in project_state[m.end():].splitlines():
        if re.match(r"^[ \t]*#{1,3}[ \t]+\S", line):
            break
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def _recent_task_context(workspace: Path, limit: int = MAX_RECENT_TASKS) -> list[dict]:
    """有界上下文：按 task.json.updated_at 取最近 limit 个任务（active + archive）。

    每个任务：task_id / status / report 摘要（经 resolver 定位 active 或 archive）。
    不扫描全部历史（只取最近 N 个）。
    """
    candidates: list[tuple[str, Path, dict]] = []
    for base in (workspace / ".aaf", workspace / ".aaf" / "archive"):
        if not base.is_dir():
            continue
        for pkg in base.iterdir():
            tj = pkg / "task.json"
            if not tj.is_file():
                continue
            try:
                import json

                data = json.loads(tj.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not data.get("task_id"):
                continue
            candidates.append((data.get("updated_at") or "", pkg, data))
    candidates.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, pkg, data in candidates[:limit]:
        report = find_report_path(data["task_id"], workspace)
        summary = ""
        if report is not None and report.exists():
            text = _read_text(report) or ""
            first = [ln.strip() for ln in text.splitlines() if ln.strip()][:6]
            summary = " | ".join(first[:3])
        out.append({
            "task_id": data["task_id"],
            "status": data.get("status", UNKNOWN),
            "report": summary or UNKNOWN,
        })
    return out


@dataclass
class RolloverResult:
    session_id: str
    summary_path: str
    next_start_path: str
    archived_previous: str | None
    recent_tasks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "summary_path": self.summary_path,
            "next_start_path": self.next_start_path,
            "archived_previous": self.archived_previous,
            "recent_tasks": self.recent_tasks,
        }


def rollover(
    workspace: Path | str,
    *,
    project: str | None = None,
    phase: str | None = None,
    core_goal: str | None = None,
    frozen_boundaries: str | None = None,
    completed_work: str | None = None,
    open_items: str | None = None,
    blocking_issues: str | None = None,
    important_decisions: str | None = None,
    relevant_task_ids: str | None = None,
    next_step: str | None = None,
    do_not_reopen: str | None = None,
    project_state_file: Path | str | None = None,
) -> RolloverResult:
    """执行显式 Session rollover，生成 SESSION_SUMMARY.md + NEXT_SESSION_START.md。

    数据优先级（任务 10）：显式参数 → PROJECT_STATE.md 节 → task.json/REPORT → UNKNOWN。
    """
    ws = Path(workspace)
    sid = session_id()
    cur = current_dir(ws)
    cur.mkdir(parents=True, exist_ok=True)

    # 0) 归档前一个 current Session（如存在；避免覆盖）
    archived_previous = None
    prev_meta = meta_path(ws)
    if prev_meta.exists():
        import json

        try:
            prev = json.loads(prev_meta.read_text(encoding="utf-8"))
            prev_sid = str(prev.get("session_id") or "unknown")
        except (OSError, ValueError):
            prev_sid = "unknown"
        target = session_archive_dir(ws) / prev_sid
        if target.exists():
            raise SessionError(f"Session archive 目标已存在（禁止覆盖）: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        cur.rename(target)  # 同卷移动（current 内只有本 Session artifact）
        archived_previous = str(target)
        cur.mkdir(parents=True, exist_ok=True)

    # 1) 数据收集
    ps_text = ""
    if project_state_file is not None and Path(project_state_file).exists():
        ps_text = _read_text(Path(project_state_file)) or ""
    elif (ws / "PROJECT_STATE.md").exists():
        ps_text = _read_text(ws / "PROJECT_STATE.md") or ""

    # 正式 Boundary Source（PROJECT_SCOPE）优先继承；缺失退回 PROJECT_STATE 逻辑
    from .project_boundary import UNKNOWN as B_UNKNOWN, load_boundary

    boundary = load_boundary(ws)
    boundary_scope_items = boundary.current_scope if boundary.configured else []

    project = project or _section(ps_text, "Project") or _section(ps_text, "项目") or UNKNOWN
    phase = phase or _section(ps_text, "Current Phase") or _section(ps_text, "当前阶段") or UNKNOWN
    # 显式参数 → PROJECT_SCOPE（正式 Boundary Source 优先）→ PROJECT_STATE → UNKNOWN
    if core_goal is None:
        if boundary.configured and boundary.core_goal != B_UNKNOWN:
            core_goal = boundary.core_goal
        else:
            core_goal = _section(ps_text, "Core Goal") or _section(ps_text, "核心目标") or UNKNOWN
    if frozen_boundaries is None:
        if boundary.configured and boundary.frozen_boundaries:
            frozen_boundaries = "\n".join(boundary.frozen_boundaries)
        else:
            frozen_boundaries = _section(ps_text, "Frozen Boundaries") or _section(ps_text, "冻结边界") or UNKNOWN
    completed_work = completed_work or _section(ps_text, "Completed") or _section(ps_text, "已完成") or UNKNOWN
    open_items = open_items or _section(ps_text, "Open Items") or _section(ps_text, "未完成") or UNKNOWN
    blocking_issues = blocking_issues or _section(ps_text, "Blocking") or _section(ps_text, "阻塞") or UNKNOWN
    important_decisions = important_decisions or _section(ps_text, "Decisions") or _section(ps_text, "决策") or UNKNOWN
    next_step = next_step or _section(ps_text, "Next Step") or _section(ps_text, "下一步") or UNKNOWN
    if do_not_reopen is None:
        if boundary.configured and boundary.frozen_boundaries:
            do_not_reopen = "\n".join(boundary.frozen_boundaries)
        else:
            do_not_reopen = _section(ps_text, "Do Not Reopen") or _section(ps_text, "不要重开") or UNKNOWN

    recent = _recent_task_context(ws)
    task_ids = [t["task_id"] for t in recent]
    if relevant_task_ids:
        explicit_ids = [x.strip() for x in relevant_task_ids.split(",") if x.strip()]
        # 显式指定的任务优先显示
        by_id = {t["task_id"]: t for t in recent}
        recent = (
            [by_id[i] for i in explicit_ids if i in by_id]
            + [t for t in recent if t["task_id"] not in explicit_ids]
        )
        task_ids = explicit_ids + [t for t in task_ids if t not in explicit_ids]
    relevant_task_ids_s = ", ".join(task_ids) if task_ids else UNKNOWN

    # 2) Git 只读快照（复用 git_status；缺失字段不影响模板）
    git = git_snapshot(str(ws))
    git_line = "not a git repo"
    if git.is_git_repo:
        git_line = (
            f"branch={git.branch or '(detached)'} "
            f"head={git.local_head[:12] or 'n/a'} "
            f"sync={git.remote_sync} "
            f"ahead={git.ahead} behind={git.behind} "
            f"tree={git.working_tree}"
        )

    generated_at = datetime.now().isoformat(timespec="seconds")

    # 3) SESSION_SUMMARY.md（较完整）
    summary = f"""# SESSION SUMMARY — {sid}

- Project: {project}
- Workspace: {ws}
- Session ID: {sid}
- Generated At: {generated_at}

## Current Phase
{phase}

## Core Goal
{core_goal}

## Frozen Boundaries
{frozen_boundaries}

## Completed Work
{completed_work}

## Current State
{git_line}

## Open Items
{open_items}

## Blocking Issues
{blocking_issues}

## Important Decisions
{important_decisions}

## Relevant Task IDs
{relevant_task_ids_s}

## Recent Task Snapshot
"""
    for t in recent:
        summary += f"- {t['task_id']} [{t['status']}] {t['report']}\n"
    if not recent:
        summary += "- (none)\n"
    summary += f"""
## What NOT to Reopen
{do_not_reopen}

## Next Recommended Step
{next_step}
"""
    summary_path = cur / "SESSION_SUMMARY.md"
    summary_path.write_text(summary, encoding="utf-8")

    # 4) NEXT_SESSION_START.md（短、聚焦、最小恢复上下文）
    next_start = f"""# NEXT SESSION START

- This project is: {project}
- Current phase: {phase}
- Current objective: {core_goal}

## Frozen Boundaries
{frozen_boundaries}

## Current Scope
"""
    for item in boundary_scope_items:
        next_start += f"- {item}\n"
    if not boundary_scope_items:
        next_start += "- (not configured)\n"
    next_start += f"""
## Latest Completed Task
{task_ids[0] if task_ids else UNKNOWN}

## Current Unresolved Items
{open_items}

## Immediate Next Step
{next_step}

## Files to Read First
- {ws / 'PROJECT_STATE.md'} (if exists)
- {cur / 'SESSION_SUMMARY.md'}
- Relevant task REPORT(s): under .aaf/<Task-ID>/REPORT.md or .aaf/archive/<Task-ID>/REPORT.md

## Do NOT reopen completed scope
{do_not_reopen}
"""
    next_start_path = cur / "NEXT_SESSION_START.md"
    next_start_path.write_text(next_start, encoding="utf-8")

    # 5) meta
    import json

    meta_path(ws).write_text(
        json.dumps({
            "session_id": sid,
            "workspace": str(ws),
            "generated_at": generated_at,
            "project": project,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return RolloverResult(
        session_id=sid,
        summary_path=str(summary_path),
        next_start_path=str(next_start_path),
        archived_previous=archived_previous,
        recent_tasks=recent,
    )
