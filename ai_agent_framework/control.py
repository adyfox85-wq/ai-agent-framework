"""AI Agent Framework — Task control artifact（control.json，Phase E §6A.7 / §6B.12 / §6B.17）。

control.json 的角色：
- **task-owned ownership evidence**：``<output_dir>/control.json``（与 task.json 同目录），
  记录本次 launch 的 launch_id / task_id / workspace / runner 身份 / 期望命令行
- **不是 terminal truth**（§6A.15）：不含任何 terminal authority；终态裁决权仍在
  Core（task.json + state.lock）
- 与 Bridge launch registry（~/.aaf-bridge/launches/<launch_id>.json，§6B.11）互为
  第二份独立证据：restart 接管必须 registry + control + live process 三方验证（§6B.13）

写者归属与原子性（§6A.7）：
- Launcher：创建（launch 前预写）+ 更新 cancel_requested / force_terminate_requested /
  superseded_by / RUNNING 回填（runner_pid / runner_creation_time）
- Runner：启动后写回 runner_pid / runner_creation_time（handshake，§6A.6-4）
- 全部 **原子写（tmp + os.replace）** + **schema 验证** + 确定性（无 partial JSON）
- 跨进程 read-modify-write 串行化：Framework-owned 的 control 变更统一经 per-task
  ``state.lock``（§6B.1 同一把锁；owner protocol，TASK req 4）——Launcher 与 Runner
  不会互相覆盖丢失字段；锁失败 → 显式错误，不写、不 fallback 无锁写（§6B.19）

读取（verify / 诊断）：无锁只读；损坏 → (None, error)，调用方 fail closed。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .lock_utils import LockError, LockTimeout, task_state_lock

CONTROL_FILENAME = "control.json"
CONTROL_SCHEMA_VERSION = 1

# 必需字段（TASK req 3 字段集；冻结设计 §6A.7 schema 以本 TASK 为准）
REQUIRED_FIELDS = (
    "task_id",
    "workspace",
    "launch_id",
    "launcher_pid",
    "launcher_instance_id",
    "started_at",
    "expected_runner_entry",
    "expected_command_line",
    "runner_pid",
    "runner_creation_time",
    "cancel_requested",
    "force_terminate_requested",
    "superseded_by",
)

# Launcher 预写字段（Runner 不得修改）
LAUNCHER_OWNED = (
    "task_id",
    "workspace",
    "launch_id",
    "launcher_pid",
    "launcher_instance_id",
    "started_at",
    "expected_runner_entry",
    "expected_command_line",
    "superseded_by",
)

# Runner 回写字段（handshake 写回；Launcher RUNNING 回填同值交叉验证）
RUNNER_WRITEBACK = ("runner_pid", "runner_creation_time")


def control_path(output_dir: Path | str) -> Path:
    return Path(output_dir) / CONTROL_FILENAME


def validate_control(data: dict) -> list[str]:
    """schema 验证 → 错误列表（空 = 合法）。确定性；任一必需字段缺失/类型错 → error。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["control.json 不是 JSON object"]
    if data.get("schema_version") != CONTROL_SCHEMA_VERSION:
        errors.append(f"schema_version != {CONTROL_SCHEMA_VERSION}")
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")
    if "task_id" in data and not isinstance(data["task_id"], str):
        errors.append("task_id 必须是字符串")
    if "workspace" in data and not isinstance(data["workspace"], str):
        errors.append("workspace 必须是字符串")
    if "launch_id" in data and not (isinstance(data["launch_id"], str) and data["launch_id"]):
        errors.append("launch_id 必须是非空字符串")
    if "expected_runner_entry" in data and not (isinstance(data["expected_runner_entry"], str) and data["expected_runner_entry"]):
        errors.append("expected_runner_entry 必须是非空字符串")
    if "expected_command_line" in data and not isinstance(data["expected_command_line"], list):
        errors.append("expected_command_line 必须是 list")
    if "runner_pid" in data and data["runner_pid"] is not None and not isinstance(data["runner_pid"], int):
        errors.append("runner_pid 必须是 int 或 null")
    if "runner_creation_time" in data and data["runner_creation_time"] is not None and not isinstance(data["runner_creation_time"], str):
        errors.append("runner_creation_time 必须是 str 或 null")
    if "superseded_by" in data and data["superseded_by"] is not None and not isinstance(data["superseded_by"], str):
        errors.append("superseded_by 必须是 str 或 null")
    for flag in ("cancel_requested", "force_terminate_requested"):
        if flag in data and not isinstance(data[flag], bool):
            errors.append(f"{flag} 必须是 bool")
    return errors


def new_control(
    *,
    task_id: str,
    workspace: str,
    launch_id: str,
    launcher_pid: int,
    launcher_instance_id: str,
    expected_runner_entry: str,
    expected_command_line: list[str],
    started_at: str | None = None,
) -> dict:
    """Launcher 预写 control dict（launch 前；§6B.12-C）。"""
    return {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "task_id": task_id,
        "workspace": str(workspace),
        "launch_id": launch_id,
        "launcher_pid": int(launcher_pid),
        "launcher_instance_id": launcher_instance_id,
        "started_at": started_at or datetime.now().isoformat(timespec="seconds"),
        "expected_runner_entry": expected_runner_entry,
        "expected_command_line": list(expected_command_line),
        "runner_pid": None,
        "runner_creation_time": None,
        "cancel_requested": False,
        "force_terminate_requested": False,
        "superseded_by": None,
    }


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ControlWriteError(f"control.json 写入失败: {path} ({exc})") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class ControlError(RuntimeError):
    """control.json 读写 / schema 校验失败（不得静默；fail closed）。"""


class ControlWriteError(ControlError):
    """control.json 原子写失败（OS 错误）。"""


class ControlLockError(ControlError):
    """control.json 变更无法取得 state.lock（超时 / OS 错误）——不写、不 fallback。"""


def read_control(output_dir: Path | str) -> tuple[dict | None, str | None]:
    """无锁只读 control.json → (data, error)。

    - 无文件 → (None, None)
    - 合法 → (dict, None)
    - 损坏 / schema 非法 → (None, error)（调用方 fail closed）
    """
    path = control_path(output_dir)
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"control.json 不可读: {path} ({exc})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"control.json 损坏（JSON 解析失败）: {path} ({exc})"
    errors = validate_control(data)
    if errors:
        return None, f"control.json schema 非法: {'; '.join(errors)}"
    return data, None


def write_control(
    output_dir: Path | str,
    data: dict,
    *,
    task_id: str | None = None,
    lock_timeout: float = 10.0,
) -> Path:
    """原子写 control.json（全量；tmp + os.replace + schema 验证；state.lock 内）。

    - 调用方提供完整 dict（new_control 或 read-modify 结果）
    - 写前 schema 验证：非法 → ControlError，零写
    - 跨进程串行化：per-task state.lock（与 terminal writers 同一把锁；owner protocol）
    - 锁失败 → ControlLockError（不写、不 fallback 无锁写）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    errors = validate_control(data)
    if errors:
        raise ControlError(f"control.json schema 校验失败: {'; '.join(errors)}")
    lock_task_id = task_id or data.get("task_id") or output_dir.name or "?"
    try:
        with task_state_lock(output_dir, lock_task_id, timeout=lock_timeout):
            _atomic_write(control_path(output_dir), data)
    except (LockTimeout, LockError) as exc:
        raise ControlLockError(f"control.json 变更无法取得 state.lock: {exc}") from exc
    return control_path(output_dir)


def update_control(
    output_dir: Path | str,
    fields: dict,
    *,
    task_id: str | None = None,
    lock_timeout: float = 10.0,
) -> Path:
    """read-modify-write 更新 control.json 指定字段（原子；state.lock 内；TASK req 4）。

    - 无现有 control → 抛 ControlError（不凭空创建；创建必须经 write_control 全量）
    - 现文件损坏 → ControlError（不覆盖未知状态）
    - 更新后仍必须通过完整 schema 验证
    """
    output_dir = Path(output_dir)
    current, err = read_control(output_dir)
    if err:
        raise ControlError(f"control.json 无法更新（现有文件损坏）: {err}")
    if current is None:
        raise ControlError(
            f"control.json 不存在（{control_path(output_dir)}），无法 update_control——"
            f"创建必须经 write_control 全量写入"
        )
    merged = dict(current)
    merged.update(fields)
    return write_control(output_dir, merged, task_id=task_id, lock_timeout=lock_timeout)
