"""AAF Bridge — Duplicate Task 状态识别（Phase F / TASK-006，RW-016；纯函数可单测）。

设计（docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md §10）：
- TASK_ALREADY_EXISTS 本身不是错误；UX 缺口是「只告诉存在，不告诉状态」（§10.0）
- 本模块在既有 duplicate protection（task_io.save_task 的 TASK_ALREADY_EXISTS）之上，
  提供状态卡片所需的结构化信息；**不得删除/放宽 duplicate protection**（RW-016
  Do Not Forget）——判定仍以 canonical TASK.md 落盘路径存在为准
- 分类（req 8）：
    running   = 同 Task ID 正在运行（registry 活跃 launch 或 launcher 当前任务）
    completed = 同 Task ID 已完成（terminal 状态：SUCCESS / WAITING / FAILED / CANCELLED）
    abnormal  = 同 Task ID 已存在但状态异常（task.json 非终态/残留 RUNNING 等）
    unknown   = 同 Task ID 已存在但状态未知（无 task.json）
    None      = 可以合法重新提交的新任务
- 只读；不写任何文件（REPORT 路径解析走 task_archive 既有只读逻辑）

Authority 边界（req 12）：本模块只提供「是什么状态」的事实；
是否允许切换/启动由 Bridge intake 决策，本模块不改写 Task ID / Workspace /
canonical terminal / 历史 artifacts。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import task_io
from ai_agent_framework import runtime_state as runtime_state_mod
from ai_agent_framework import task_archive
from ai_agent_framework.task_lifecycle import TERMINAL_STATUSES

KIND_RUNNING = "running"
KIND_COMPLETED = "completed"
KIND_ABNORMAL = "abnormal"
KIND_UNKNOWN = "unknown"

# task.json 非终态但已存在的状态 → 「状态异常」（残留 RUNNING / CREATED 未启动等）
_ABNORMAL_STATUSES = ("RUNNING", "CREATED")

KIND_LABELS = {
    KIND_RUNNING: "同 Task ID 正在运行",
    KIND_COMPLETED: "同 Task ID 已完成",
    KIND_ABNORMAL: "同 Task ID 已存在但状态异常",
    KIND_UNKNOWN: "同 Task ID 已存在但状态未知",
}


@dataclass
class DuplicateInfo:
    """Duplicate 状态卡片数据（全部字段面向 UI，技术状态值保留英文原值）。"""

    task_id: str
    kind: str  # running / completed / abnormal / unknown
    status: str | None  # 原始 status（英文，技术字段）
    status_cn: str  # 中文映射
    stage: str | None
    stage_cn: str
    last_activity: str | None  # 最近活动（格式化中文）
    report_path: str | None
    output_dir: str | None
    reason: str  # 为什么需要确认/为什么拒绝（中文）


def _status_cn(status: str | None) -> str:
    from .status_window import overall_status_label  # 延迟导入：单一中文映射来源（§11）
    return overall_status_label(status) if status else "状态未知"


def _stage_cn(stage: str | None) -> str:
    from .status_window import stage_display_name  # 延迟导入：阶段中文名
    return stage_display_name(stage)


def _last_activity(task_dir: Path) -> str | None:
    """最近活动 = 任务目录产物最大 mtime（设计 §5.1/§10.2）。无产物 → None。"""
    if not task_dir.is_dir():
        return None
    latest: float | None = None
    for p in task_dir.rglob("*"):
        if p.is_file():
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            latest = mtime if latest is None else max(latest, mtime)
    if latest is None:
        return None
    try:
        return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return None


def active_launch_for_task_id(task_id: str, active_launches: list[dict]) -> dict | None:
    """从 registry 活跃 launch 列表找同 Task ID 条目（首个）。"""
    for entry in active_launches or []:
        if entry.get("task_id") == task_id:
            return entry
    return None


def inspect_duplicate(
    task_id: str,
    workspace: str,
    active_launches: list[dict] | None = None,
    launcher_current_task_id: str | None = None,
) -> DuplicateInfo | None:
    """检查 Task ID 是否为 duplicate。非 duplicate（可合法提交）→ None。

    - canonical duplicate 判定 = 正式 TASK.md 落盘路径存在（与 save_task 同一判定，
      不因 UX 放宽 execution authority）
    - active_launches：registry 活跃（PREPARED/RUNNING）条目列表（可空）
    - launcher_current_task_id：本 Bridge 进程 launcher 当前任务（内存事实）
    """
    tid = (task_id or "").strip()
    if not tid or not workspace:
        return None
    target = task_io.task_target_path(workspace, tid)
    if not target.exists():
        return None  # 新任务：可以合法重新提交

    task_dir = Path(workspace) / ".aaf" / tid
    output_dir = str(task_dir)

    # 1) 正在运行（registry 活跃 launch 优先；launcher 内存事实兜底）
    active = active_launch_for_task_id(tid, active_launches)
    if active is not None or launcher_current_task_id == tid:
        return DuplicateInfo(
            task_id=tid,
            kind=KIND_RUNNING,
            status="RUNNING",
            status_cn="执行中",
            stage=None,
            stage_cn="",
            last_activity=_last_activity(task_dir),
            report_path=None,  # RUNNING：REPORT 尚未生成（§10.3）
            output_dir=output_dir,
            reason="同 Task ID 正在运行：不启动第二份 runner，不创建并行重复 execution（req 9）。",
        )

    # 2) 已存在 → 读 task.json 状态
    runtime = runtime_state_mod.read_runtime_state(task_dir)
    if runtime is not None and runtime.status:
        status = runtime.status
        if status in TERMINAL_STATUSES:
            report_path = _resolve_report_path(runtime.report_path, tid, workspace)
            return DuplicateInfo(
                task_id=tid,
                kind=KIND_COMPLETED,
                status=status,
                status_cn=_status_cn(status),
                stage=runtime.stage,
                stage_cn=_stage_cn(runtime.stage),
                last_activity=_last_activity(task_dir),
                report_path=report_path,
                output_dir=output_dir,
                reason=(
                    f"同 Task ID 已完成（{status}）：当前 execution contract 不允许 rerun——"
                    f"需新 Task ID 才能重新提交（req 10）。"
                ),
            )
        if status in _ABNORMAL_STATUSES:
            return DuplicateInfo(
                task_id=tid,
                kind=KIND_ABNORMAL,
                status=status,
                status_cn=_status_cn(status),
                stage=runtime.stage,
                stage_cn=_stage_cn(runtime.stage),
                last_activity=_last_activity(task_dir),
                report_path=_resolve_report_path(runtime.report_path, tid, workspace),
                output_dir=output_dir,
                reason=(
                    f"同 Task ID 已存在但状态异常（{status}）：任务记录非终态且无活跃启动。"
                    f"请勿重复提交；如需处理请先核查任务目录。"
                ),
            )
        # 其他未知状态（防御）
        return DuplicateInfo(
            task_id=tid,
            kind=KIND_ABNORMAL,
            status=status,
            status_cn=_status_cn(status),
            stage=runtime.stage,
            stage_cn=_stage_cn(runtime.stage),
            last_activity=_last_activity(task_dir),
            report_path=_resolve_report_path(runtime.report_path, tid, workspace),
            output_dir=output_dir,
            reason=f"同 Task ID 已存在但状态异常（{status}）：无法确认可安全重新提交。",
        )

    # 3) TASK.md 存在但无 task.json → 状态未知（如已登记未启动/产物缺失）
    return DuplicateInfo(
        task_id=tid,
        kind=KIND_UNKNOWN,
        status=None,
        status_cn="状态未知",
        stage=None,
        stage_cn="",
        last_activity=_last_activity(task_dir),
        report_path=_resolve_report_path(None, tid, workspace),
        output_dir=output_dir,
        reason="同 Task ID 已存在但状态未知（无 task.json）：不静默覆盖历史 artifacts（req 10）。",
    )


def _resolve_report_path(report_path: str | None, task_id: str, workspace: str) -> str | None:
    """REPORT 路径：task.json.report_path → 归档/兜底查找（§10.2）。"""
    if report_path:
        p = Path(report_path)
        if p.exists():
            return str(p)
    try:
        found = task_archive.find_report_path(task_id, Path(workspace))
        return str(found) if found is not None else None
    except Exception:  # noqa: BLE001 —— 只读兜底失败不阻断卡片展示
        return None
