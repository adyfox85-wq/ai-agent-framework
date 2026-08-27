"""AI Agent Framework — 最小、正式、确定性 Task Lifecycle。

职责：
- 为每个正式 TASK 维护机器可读状态（task.json）
- 状态迁移由 Runner 编排（本模块不调用 LLM / Agent / Router）
- 只记录状态，不修改 TASK.md / REPORT.md

职责分离：
- TASK.md  = formal task input
- task.json = machine lifecycle state
- REPORT.md = execution result / human-readable report
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

# 正式 Task Status（唯一合法集合；ARCHIVED 属于存储生命周期，不属于执行结果）
VALID_STATUSES = ("CREATED", "RUNNING", "WAITING", "SUCCESS", "FAILED")

# 正式 Stage（v0.4 Phase A Runtime State；CANCELLED 不属于 Phase A）
VALID_STAGES = ("VALIDATION", "BOUNDARY", "HERMES", "WORKBUDDY", "CODEX", "REPORT", "COMPLETED")

# 阶段状态（Phase A 支持集合）
VALID_PHASE_STATES = ("PENDING", "RUNNING", "SUCCESS", "WAITING", "FAILED", "SKIPPED")

_STATUS_REASON = "reason"  # internal，非正式状态


class LifecycleError(RuntimeError):
    """task.json 读写失败（不得静默忽略）。"""


def task_json_path(output_dir: Path) -> Path:
    """task.json 位置：<output_dir>/task.json（与 route.json / REPORT.md 同目录）。"""
    return Path(output_dir) / "task.json"


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
    """写入/更新 task.json。

    - 原子写：临时文件 → os.replace（避免部分写入损坏 JSON）
    - 保留旧 report_path（新值为 None 时）
    - v0.4 Phase A：可选维护 live runtime state：
      started_at（首次 RUNNING）/ last_activity_at（每次更新）/
      stage + stage_started_at（stage 首次进入或变化时）/ agent / phases
    - 写入失败抛 LifecycleError（调用方不得静默吞掉）
    """
    if status not in VALID_STATUSES:
        raise LifecycleError(f"非法 lifecycle status: {status!r}（允许: {', '.join(VALID_STATUSES)}）")
    if stage is not None and stage not in VALID_STAGES:
        raise LifecycleError(f"非法 stage: {stage!r}（允许: {', '.join(VALID_STAGES)}）")
    if phase_state not in VALID_PHASE_STATES:
        raise LifecycleError(f"非法 phase_state: {phase_state!r}（允许: {', '.join(VALID_PHASE_STATES)}）")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = task_json_path(output_dir)

    prev = None
    try:
        prev = read_status(output_dir)
    except LifecycleError:
        prev = None  # 已损坏：从新值重建（不静默——read 已抛出过；此处重建可恢复）

    now = datetime.now()
    now_iso = now.isoformat(timespec="seconds")

    data = {
        "task_id": task_id,
        "status": status,
        "updated_at": now_iso,
        "task_path": str(task_path),
        "workspace": str(workspace),
        "report_path": str(report_path) if report_path is not None else (prev or {}).get("report_path"),
    }

    # --- v0.4 Phase A live runtime state ---
    prev = prev or {}
    # started_at：首次进入 RUNNING 时固定
    if status == "RUNNING" and not prev.get("started_at"):
        data["started_at"] = now_iso
    elif prev.get("started_at"):
        data["started_at"] = prev["started_at"]
    # last_activity_at：每次状态活动都更新
    data["last_activity_at"] = now_iso

    if stage is not None:
        data["stage"] = stage
        data["agent"] = agent
        phases = dict(prev.get("phases") or {})
        entry = dict(phases.get(stage) or {})
        entry["state"] = phase_state
        entry["started_at"] = entry.get("started_at") or now_iso
        entry["updated_at"] = now_iso
        phases[stage] = entry
        data["phases"] = phases
        # stage_started_at：阶段首次进入（或阶段变化）时设置
        if not prev.get("stage_started_at") or prev.get("stage") != stage:
            data["stage_started_at"] = entry["started_at"]
        else:
            data["stage_started_at"] = prev["stage_started_at"]
    else:
        # 保留已有 runtime 字段（非 stage 更新，如终态无 stage 时）
        for key in ("stage", "stage_started_at", "agent", "phases", "started_at"):
            if prev.get(key) is not None:
                data[key] = prev[key]

    if reason is not None:
        data[_STATUS_REASON] = reason

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
    return path
