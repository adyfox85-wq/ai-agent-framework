"""AI Agent Framework — 最小、正式、确定性 Task Lifecycle。

职责：
- 为每个正式 TASK 维护机器可读状态（task.json）
- 状态迁移由 Runner 编排（本模块不调用 LLM / Agent / Router）
- 只记录状态，不修改 TASK.md / REPORT.md

Phase E（Safe Cancel Lifecycle，冻结设计 §6 / §6A / §6B）：
- 合法终态集合 TERMINAL_STATUSES = {SUCCESS, WAITING, FAILED, CANCELLED}（§6A.1）
- Core 是 Task terminal state 的唯一 authoritative finalizer（§6A.1）：终态只能通过
  ``finalize_terminal``（锁内临界区 §6B.2）写入；``update_status`` 拒绝终态
- 每次 terminal commit 持久化单调 ``terminal_generation``（§6B.4），legacy task.json
  无该字段不崩溃（兼容）
- 终态一旦 committed 不可被 late event 覆盖（§6A.2 / §6B.2-D：锁内 reload 后已有终态
  → 返回现有 canonical result，不写任何东西）

职责分离：
- TASK.md  = formal task input
- task.json = machine lifecycle state（唯一 canonical terminal truth，§6B.5）
- REPORT.md = execution result / human-readable report
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .lock_utils import LockError, LockTimeout, task_state_lock

# 正式 Task Status（唯一合法集合；ARCHIVED 属于存储生命周期，不属于执行结果）
VALID_STATUSES = ("CREATED", "RUNNING", "WAITING", "SUCCESS", "FAILED", "CANCELLED")

# 合法终态集合（§6A.1 TERMINAL = {SUCCESS, WAITING, FAILED, CANCELLED}）
# 只有两类入口可以写终态：Runner 自身生命周期路径（含检查点取消收敛）与
# Core recovery finalizer（finalize_cancelled）——二者都经 finalize_terminal 锁内提交。
TERMINAL_STATUSES = ("SUCCESS", "WAITING", "FAILED", "CANCELLED")

# 正式 Stage（v0.4 Phase A Runtime State）
VALID_STAGES = ("VALIDATION", "BOUNDARY", "HERMES", "WORKBUDDY", "CODEX", "REPORT", "COMPLETED")

# 阶段状态（Phase A 支持集合；CANCELLED 是任务级终态，不是阶段状态——
# 阶段保持事实（已完成 ✓ / 未开始 ○），整体状态由 status 表达）
VALID_PHASE_STATES = ("PENDING", "RUNNING", "SUCCESS", "WAITING", "FAILED", "SKIPPED")

_STATUS_REASON = "reason"  # internal，非正式状态

# terminal_reason 取值（设计 §6B.5）
TERMINAL_REASON_NORMAL_COMPLETION = "NORMAL_COMPLETION"
TERMINAL_REASON_WAITING = "WAITING"
TERMINAL_REASON_FRAMEWORK_ERROR = "FRAMEWORK_ERROR"
TERMINAL_REASON_CANCEL_REQUESTED = "CANCEL_REQUESTED"
TERMINAL_REASON_FORCE_CANCELLED = "FORCE_CANCELLED"

# cancel_mode（仅取消终态；设计 §6B.5）
CANCEL_MODE_SOFT = "soft"
CANCEL_MODE_FORCE = "force"

_DEFAULT_TERMINAL_REASON = {
    "SUCCESS": TERMINAL_REASON_NORMAL_COMPLETION,
    "WAITING": TERMINAL_REASON_WAITING,
    "FAILED": TERMINAL_REASON_FRAMEWORK_ERROR,
    "CANCELLED": TERMINAL_REASON_CANCEL_REQUESTED,
}


class LifecycleError(RuntimeError):
    """task.json 读写失败（不得静默忽略）。"""


@dataclass
class TerminalResult:
    """canonical terminal result（§6B.2-D 返回给调用方；供 run.json / REPORT /
    last_run.json 跟随——派生产物必须服从此结果，不得自行推导覆盖）。

    - preserved=True：调用时 task.json 已有终态，本次未改写，返回现有 canonical
    - preserved=False：本次 commit 成功
    """

    status: str
    task_id: str
    output_dir: str
    terminal_generation: int | None = None
    terminal_at: str | None = None
    terminal_reason: str | None = None
    report_path: str | None = None
    cancel_mode: str | None = None
    preserved: bool = False

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "task_id": self.task_id,
            "output_dir": self.output_dir,
            "terminal_generation": self.terminal_generation,
            "terminal_at": self.terminal_at,
            "terminal_reason": self.terminal_reason,
            "report_path": self.report_path,
            "cancel_mode": self.cancel_mode,
            "preserved": self.preserved,
        }


def task_json_path(output_dir: Path) -> Path:
    """task.json 位置：<output_dir>/task.json（与 route.json / REPORT.md 同目录）。"""
    return Path(output_dir) / "task.json"


def is_terminal_status(status: str) -> bool:
    return status in TERMINAL_STATUSES


def read_status(output_dir: Path) -> dict | None:
    """读取任务 lifecycle；文件不存在 → None；损坏 → 抛 LifecycleError。"""
    path = task_json_path(output_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise LifecycleError(f"task.json 损坏或不可读: {path} ({exc})") from exc
    if not isinstance(data, dict) or data.get("task_id") is None:
        raise LifecycleError(f"task.json 缺少 task_id: {path}")
    return data


def read_canonical_terminal(output_dir: Path | str) -> TerminalResult | None:
    """读取 canonical terminal record（§6B.5）。

    - task.json 缺失 / 无终态 → None（不臆造）
    - task.json 损坏 → 抛 LifecycleError
    - 已有终态 → TerminalResult（status / terminal_generation / terminal_at /
      terminal_reason / report_path / cancel_mode）
    """
    data = read_status(Path(output_dir))
    if data is None or not is_terminal_status(data.get("status", "")):
        return None
    return TerminalResult(
        status=data["status"],
        task_id=data.get("task_id", ""),
        output_dir=str(Path(output_dir)),
        terminal_generation=data.get("terminal_generation"),
        terminal_at=data.get("terminal_at"),
        terminal_reason=data.get("terminal_reason"),
        report_path=data.get("report_path"),
        cancel_mode=data.get("cancel_mode"),
    )


def _validate_args(status: str, stage: str | None, phase_state: str | None) -> None:
    if status not in VALID_STATUSES:
        raise LifecycleError(f"非法 lifecycle status: {status!r}（允许: {', '.join(VALID_STATUSES)}）")
    if stage is not None and stage not in VALID_STAGES:
        raise LifecycleError(f"非法 stage: {stage!r}（允许: {', '.join(VALID_STAGES)}）")
    if phase_state is not None and phase_state not in VALID_PHASE_STATES:
        raise LifecycleError(f"非法 phase_state: {phase_state!r}（允许: {', '.join(VALID_PHASE_STATES)}）")


def _build_data(
    prev: dict,
    *,
    task_id: str,
    status: str,
    task_path: Path | str,
    workspace: Path | str,
    report_path: Path | str | None,
    reason: str | None,
    stage: str | None,
    agent: str | None,
    phase_state: str | None,
    terminal_fields: dict | None = None,
) -> dict:
    """由 prev + 参数构建完整 task.json 内容（update_status / finalize_terminal 共用）。"""
    now = datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    prev = prev or {}

    data = {
        "task_id": task_id,
        "status": status,
        "updated_at": now_iso,
        "task_path": str(task_path),
        "workspace": str(workspace),
        "report_path": str(report_path) if report_path is not None else prev.get("report_path"),
    }

    # --- v0.4 Phase A live runtime state ---
    if status == "RUNNING" and not prev.get("started_at"):
        data["started_at"] = now_iso
    elif prev.get("started_at"):
        data["started_at"] = prev["started_at"]
    data["last_activity_at"] = now_iso

    if stage is not None:
        data["stage"] = stage
        data["agent"] = agent
        phases = dict(prev.get("phases") or {})
        entry = dict(phases.get(stage) or {})
        entry["state"] = phase_state if phase_state is not None else "RUNNING"
        entry["started_at"] = entry.get("started_at") or now_iso
        entry["updated_at"] = now_iso
        phases[stage] = entry
        data["phases"] = phases
        if not prev.get("stage_started_at") or prev.get("stage") != stage:
            data["stage_started_at"] = entry["started_at"]
        else:
            data["stage_started_at"] = prev["stage_started_at"]
    else:
        for key in ("stage", "stage_started_at", "agent", "phases", "started_at"):
            if prev.get(key) is not None:
                data[key] = prev[key]

    if reason is not None:
        data[_STATUS_REASON] = reason

    if terminal_fields:
        data.update(terminal_fields)  # terminal_generation / terminal_at / terminal_reason / cancel_mode
    return data


def _atomic_write(path: Path, data: dict) -> None:
    """原子写（tmp + os.replace：只保证单文件完整替换，不承担跨进程互斥——§6B.23）。"""
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
        raise LifecycleError(f"task.json 写入失败: {path} ({exc})") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def update_status(
    output_dir: Path,
    *,
    task_id: str,
    status: str,
    task_path: Path | str,
    workspace: Path | str,
    report_path: Path | str | None = None,
    reason: str | None = None,
    stage: str | None = None,
    agent: str | None = None,
    phase_state: str = "RUNNING",
) -> Path:
    """写入/更新 task.json（**非终态**更新；原子写 + live runtime state 维护）。

    - 终态（SUCCESS / WAITING / FAILED / CANCELLED）必须经 ``finalize_terminal``
      （锁内 critical section，§6B.2）写入——本函数直接拒绝，防止绕过锁的终态写
    - 原子写：临时文件 → os.replace（避免部分写入损坏 JSON）
    - 保留旧 report_path（新值为 None 时）
    - v0.4 Phase A：可选维护 live runtime state：
      started_at（首次 RUNNING）/ last_activity_at（每次更新）/
      stage + stage_started_at（stage 首次进入或变化时）/ agent / phases
    - 写入失败抛 LifecycleError（调用方不得静默吞掉）
    """
    if is_terminal_status(status):
        raise LifecycleError(
            f"终态 {status!r} 必须经 finalize_terminal()（state.lock 锁内提交）写入，"
            f"不允许绕过锁直接 update_status"
        )
    _validate_args(status, stage, phase_state)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = task_json_path(output_dir)

    try:
        prev = read_status(output_dir)
    except LifecycleError:
        prev = None  # 已损坏：从新值重建（不静默——read 已抛出过；此处重建可恢复）

    data = _build_data(
        prev,
        task_id=task_id,
        status=status,
        task_path=task_path,
        workspace=workspace,
        report_path=report_path,
        reason=reason,
        stage=stage,
        agent=agent,
        phase_state=phase_state,
    )
    _atomic_write(path, data)
    return path


def finalize_terminal(
    output_dir: Path | str,
    *,
    task_id: str,
    status: str,
    task_path: Path | str,
    workspace: Path | str,
    report_path: Path | str | None = None,
    reason: str | None = None,
    stage: str | None = None,
    agent: str | None = None,
    phase_state: str | None = None,
    terminal_reason: str | None = None,
    cancel_mode: str | None = None,
    lock_timeout: float = 10.0,
) -> TerminalResult:
    """Canonical Terminal Critical Section（§6B.2）——所有 Core 终态写入口的共享路径。

    锁内顺序（read/check/write 同一把 state.lock 内，禁止锁外读后盲写）::

        A. acquire exclusive state.lock（超时抛 LockTimeout / OS 错误抛 LockError）
        B. reload canonical task.json（锁内重读，不使用锁外缓存）
        C. inspect current status
        D. terminal 已存在 → 返回现有 canonical result（幂等；不写任何东西）
        E. 否则：确定 allowed terminal outcome
        F. 原子提交 task.json 终态（tmp + os.replace）
        G. 持久化 terminal generation（与 F 同一次原子提交，§6B.4：prev or 0 + 1）
        H. release state.lock（仅当 canonical commit 已 durable）

    - 终态一旦 committed，任何后续 finalize_terminal（含 late cancel）都返回现有
      canonical，不覆盖（§6A.2 / §6B.18 terminal winner = 同一把锁下先 commit 者）
    - 返回 TerminalResult（canonical result；派生产物必须跟随）
    - legacy task.json 无 terminal_generation 不崩溃（兼容，从 1 开始）
    """
    _validate_args(status, stage, phase_state)
    if not is_terminal_status(status):
        raise LifecycleError(f"finalize_terminal 只接受终态，收到 {status!r}（允许: {', '.join(TERMINAL_STATUSES)}）")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with task_state_lock(output_dir, task_id, timeout=lock_timeout):
        # B. 锁内 reload canonical
        try:
            prev = read_status(output_dir)
        except LifecycleError:
            prev = None  # 已损坏：从新值重建（与 update_status 一致的可恢复语义）

        # C/D. terminal arbitration：已有终态 → 幂等返回，不写任何东西
        prev = prev or {}
        existing_status = prev.get("status")
        if is_terminal_status(existing_status):
            return TerminalResult(
                status=existing_status,
                task_id=prev.get("task_id", task_id),
                output_dir=str(output_dir),
                terminal_generation=prev.get("terminal_generation"),
                terminal_at=prev.get("terminal_at"),
                terminal_reason=prev.get("terminal_reason"),
                report_path=prev.get("report_path"),
                cancel_mode=prev.get("cancel_mode"),
                preserved=True,
            )

        # E. 确定 allowed terminal outcome + G. generation
        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        generation = int(prev.get("terminal_generation") or 0) + 1
        if cancel_mode is not None and status != "CANCELLED":
            raise LifecycleError(f"cancel_mode 只能用于 CANCELLED 终态（status={status!r}）")

        terminal_fields = {
            "terminal_generation": generation,
            "terminal_at": now_iso,
            "terminal_reason": terminal_reason or _DEFAULT_TERMINAL_REASON.get(status, status),
        }
        if status == "CANCELLED":
            terminal_fields["cancel_mode"] = cancel_mode or CANCEL_MODE_SOFT

        data = _build_data(
            prev,
            task_id=task_id,
            status=status,
            task_path=task_path,
            workspace=workspace,
            report_path=report_path,
            reason=reason,
            stage=stage,
            agent=agent,
            phase_state=phase_state,
            terminal_fields=terminal_fields,
        )
        # F. 原子提交（同一次原子写内包含 generation —— §6B.2-F/G）
        _atomic_write(task_json_path(output_dir), data)

    return TerminalResult(
        status=status,
        task_id=task_id,
        output_dir=str(output_dir),
        terminal_generation=generation,
        terminal_at=now_iso,
        terminal_reason=terminal_fields["terminal_reason"],
        report_path=str(report_path) if report_path is not None else prev.get("report_path"),
        cancel_mode=terminal_fields.get("cancel_mode"),
        preserved=False,
    )
