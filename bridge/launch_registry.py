"""AAF Bridge — Persistent Launch Registry（Phase E §6B.11 / TASK-005-B req 5）。

Bridge-owned 第二份独立 ownership 记录：``~/.aaf-bridge/launches/<launch_id>.json``。

- 与 task-owned ``.aaf/<Task-ID>/control.json``（§6A.7）是**两份不同 ownership
  evidence**（§6B.14）：launch 发起方（Bridge）与 task 契约（Launcher/Runner）落在
  不同目录、不同写者；一份丢失/损坏时另一份仍可交叉验证
- restart 接管必须 registry + control + live process 三方验证（§6B.13），
  不是 control.json 自我比较
- 状态机（§6B.11）：PREPARED → RUNNING → EXITED；↘ SUPERSEDED（新 launch 覆盖旧
  launch；旧 launch 立即失去 force-kill authority——TASK req 13）
- 启动失败（Popen 失败）：registry 标记 EXITED + ``start_failure`` 记录，
  避免 phantom RUNNING（§6B.12 / TASK req 7）
- 写：原子 tmp + os.replace（单文件完整替换；registry 每 launch 单文件，
  唯一写者 = 创建该 launch 的 Launcher instance；supersede 可能来自新 instance，
  读-modify-写以磁盘最新为准，原子替换保证无部分写入）
- **不自动清理历史**（§6B.15：保留时长由实现定；本模块不删除任何历史记录）
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from . import config as cfg_mod

REGISTRY_STATE_PREPARED = "PREPARED"
REGISTRY_STATE_RUNNING = "RUNNING"
REGISTRY_STATE_EXITED = "EXITED"
REGISTRY_STATE_SUPERSEDED = "SUPERSEDED"

VALID_STATES = (
    REGISTRY_STATE_PREPARED,
    REGISTRY_STATE_RUNNING,
    REGISTRY_STATE_EXITED,
    REGISTRY_STATE_SUPERSEDED,
)

# 非终态（可被 force-cancel 管理）的 registry 状态
ACTIVE_STATES = (REGISTRY_STATE_PREPARED, REGISTRY_STATE_RUNNING)

REGISTRY_SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "schema_version",
    "launch_id",
    "task_id",
    "workspace",
    "output_dir",
    "expected_runner_entry",
    "expected_command_line",
    "launcher_instance_id",
    "created_at",
    "runner_pid",
    "runner_creation_time",
    "state",
)


class RegistryError(RuntimeError):
    """launch registry 读写 / schema 校验失败（不得静默；fail closed）。"""


def registry_root() -> Path:
    """Bridge 私有 state root 的 launches 目录（§6B.11）。

    - 默认 ``~/.aaf-bridge/launches``（与 config.json / last_run.json 同根）
    - 环境变量 ``AAF_BRIDGE_DIR`` 可覆盖根目录（测试 / 迁移 / 诊断用）
    """
    base = Path(os.environ.get("AAF_BRIDGE_DIR") or cfg_mod.CONFIG_DIR)
    return base / "launches"


def new_launch_id() -> str:
    """每次真实 launch 生成唯一 launch_id（uuid4().hex；同一 task 新 launch 必须新 id）。"""
    return uuid.uuid4().hex


def registry_path(launch_id: str, root: Path | None = None) -> Path:
    return (root or registry_root()) / f"{launch_id}.json"


def validate_registry(data: dict) -> list[str]:
    """schema 验证 → 错误列表（空 = 合法）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["registry 不是 JSON object"]
    if data.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        errors.append(f"schema_version != {REGISTRY_SCHEMA_VERSION}")
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")
    if data.get("state") not in VALID_STATES:
        errors.append(f"state 非法: {data.get('state')!r}（允许: {', '.join(VALID_STATES)}）")
    if not isinstance(data.get("launch_id"), str) or not data["launch_id"]:
        errors.append("launch_id 必须是非空字符串")
    if data.get("runner_pid") is not None and not isinstance(data["runner_pid"], int):
        errors.append("runner_pid 必须是 int 或 null")
    if data.get("runner_creation_time") is not None and not isinstance(data["runner_creation_time"], str):
        errors.append("runner_creation_time 必须是 str 或 null")
    if data.get("launch_root_pid") is not None and not isinstance(data["launch_root_pid"], int):
        errors.append("launch_root_pid 必须是 int 或 null")
    if not isinstance(data.get("expected_command_line"), list):
        errors.append("expected_command_line 必须是 list")
    return errors


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise RegistryError(f"registry 写入失败: {path} ({exc})") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def create_prepared(
    *,
    launch_id: str,
    task_id: str,
    workspace: str,
    output_dir: str,
    expected_runner_entry: str,
    expected_command_line: list[str],
    launcher_instance_id: str,
    root: Path | None = None,
) -> Path:
    """创建 PREPARED registry 条目（§6B.12-B；launch runner 之前）。"""
    data = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "launch_id": launch_id,
        "task_id": task_id,
        "workspace": str(workspace),
        "output_dir": str(output_dir),
        "expected_runner_entry": expected_runner_entry,
        "expected_command_line": list(expected_command_line),
        "launcher_instance_id": launcher_instance_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "runner_pid": None,
        "runner_creation_time": None,
        "state": REGISTRY_STATE_PREPARED,
    }
    errors = validate_registry(data)
    if errors:
        raise RegistryError(f"registry schema 校验失败: {'; '.join(errors)}")
    path = registry_path(launch_id, root)
    _atomic_write(path, data)
    return path


def read_registry(launch_id: str, root: Path | None = None) -> tuple[dict | None, str | None]:
    """只读 registry → (data, error)。无文件 → (None, None)；损坏/schema 非法 → (None, error)。"""
    path = registry_path(launch_id, root)
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"registry 不可读: {path} ({exc})"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"registry 损坏（JSON 解析失败）: {path} ({exc})"
    errors = validate_registry(data)
    if errors:
        return None, f"registry schema 非法: {'; '.join(errors)}"
    return data, None


def update_registry(launch_id: str, fields: dict, *, root: Path | None = None) -> Path:
    """read-modify-write 更新 registry 指定字段（原子；以磁盘最新为准）。

    - 无现有条目 → RegistryError（创建必须经 create_prepared）
    - 现条目损坏 → RegistryError（不覆盖未知状态）
    - 更新后仍必须通过完整 schema 验证
    """
    current, err = read_registry(launch_id, root)
    if err:
        raise RegistryError(f"registry 无法更新（现有条目损坏）: {err}")
    if current is None:
        raise RegistryError(
            f"registry 不存在（{registry_path(launch_id, root)}），无法 update_registry——"
            f"创建必须经 create_prepared"
        )
    merged = dict(current)
    merged.update(fields)
    errors = validate_registry(merged)
    if errors:
        raise RegistryError(f"registry schema 校验失败: {'; '.join(errors)}")
    path = registry_path(launch_id, root)
    _atomic_write(path, merged)
    return path


def mark_running(launch_id: str, runner_pid: int, runner_creation_time: str | None, *, root: Path | None = None) -> Path:
    """Popen 成功后 registry → RUNNING + runner 身份（§6B.12-F）。"""
    return update_registry(
        launch_id,
        {
            "runner_pid": int(runner_pid),
            "runner_creation_time": runner_creation_time,
            "state": REGISTRY_STATE_RUNNING,
        },
        root=root,
    )


def mark_exited(
    launch_id: str,
    *,
    exit_result: str | None = None,
    note: str | None = None,
    exited_at: str | None = None,
    root: Path | None = None,
) -> Path:
    """registry → EXITED（进程退出 / 启动失败 / 任务终态；TASK req 7/26；幂等）。"""
    fields: dict = {"state": REGISTRY_STATE_EXITED, "exited_at": exited_at or datetime.now().isoformat(timespec="seconds")}
    if exit_result is not None:
        fields["exit_result"] = exit_result
    if note is not None:
        fields["exit_note"] = note
    return update_registry(launch_id, fields, root=root)


def mark_superseded(launch_id: str, new_launch_id: str, *, root: Path | None = None) -> Path:
    """registry → SUPERSEDED + superseded_by 新 launch_id（TASK req 13；幂等）。"""
    return update_registry(
        launch_id,
        {
            "state": REGISTRY_STATE_SUPERSEDED,
            "superseded_by": new_launch_id,
            "superseded_at": datetime.now().isoformat(timespec="seconds"),
        },
        root=root,
    )


def supersede_existing_for_task(task_id: str, new_launch_id: str, *, root: Path | None = None) -> list[str]:
    """同一 task 的新 launch 产生时，supersede 所有仍活跃（PREPARED/RUNNING）的旧 launch。

    - 返回被 supersede 的旧 launch_id 列表
    - 旧 launch 立即失去 force-kill authority（registry SUPERSEDED + control
      superseded_by 由调用方处理；TASK req 13）
    - 已 EXITED / SUPERSEDED 的历史条目不动
    """
    superseded: list[str] = []
    for entry in list_launches(root=root):
        if entry.get("task_id") != task_id:
            continue
        if entry.get("state") not in ACTIVE_STATES:
            continue
        old_id = entry.get("launch_id")
        if not old_id or old_id == new_launch_id:
            continue
        mark_superseded(old_id, new_launch_id, root=root)
        superseded.append(old_id)
    return superseded


def list_launches(state: str | None = None, *, root: Path | None = None) -> list[dict]:
    """列出 registry 全部条目（按 created_at 升序；损坏条目跳过并保留原始文件名日志）。"""
    base = root or registry_root()
    entries: list[dict] = []
    if not base.is_dir():
        return entries
    for p in sorted(base.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("launch_id") != p.stem:
            continue
        if state is not None and data.get("state") != state:
            continue
        entries.append(data)
    return entries


def force_evidence_path_for(launch_id: str, root: Path | None = None) -> Path:
    """该 launch 的 force evidence 文件位置（与 registry 同目录）。"""
    return (root or registry_root()) / f"{launch_id}.force-evidence.json"
