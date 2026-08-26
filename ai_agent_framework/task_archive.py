"""AI Agent Framework — 最小、正式、确定性 Task Artifact Archive。

职责：
- 整个 Task Package（<ws>/.aaf/<Task-ID>/）作为归档单元 → <ws>/.aaf/archive/<Task-ID>/
- 只有终态（SUCCESS / WAITING / FAILED）可归档；CREATED / RUNNING 拒绝
- 归档不改 task.json.status（Execution Lifecycle 与 Storage Lifecycle 独立）
- 纯确定性本地操作：不调用 LLM / Agent；不删除 / 不压缩 / 不建数据库

职责分离：
- task.json.status  = Execution Lifecycle
- filesystem location = Storage Lifecycle（archive 只动位置）
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ARCHIVE_DIR_NAME = "archive"

# 可归档的正式终态（CREATED / RUNNING 不得归档）
TERMINAL_STATUSES = ("SUCCESS", "WAITING", "FAILED")

# 错误码
ERR_TASK_NOT_ARCHIVABLE = "TASK_NOT_ARCHIVABLE"
ERR_ARCHIVE_TARGET_EXISTS = "ARCHIVE_TARGET_EXISTS"
ERR_RESTORE_TARGET_EXISTS = "RESTORE_TARGET_EXISTS"
ERR_SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
ERR_TASK_JSON_UNREADABLE = "TASK_JSON_UNREADABLE"
ERR_MOVE_FAILED = "MOVE_FAILED"
ERR_METADATA_WRITE_FAILED = "METADATA_WRITE_FAILED"


class ArchiveError(RuntimeError):
    """归档/恢复失败（code 供机器读取）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass
class ArchiveResult:
    task_id: str
    source_path: str
    archive_path: str
    status: str
    archived_at: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source_path": self.source_path,
            "archive_path": self.archive_path,
            "status": self.status,
            "archived_at": self.archived_at,
        }


@dataclass
class RestoreResult:
    task_id: str
    archive_path: str
    restored_path: str
    status: str
    restored_at: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "archive_path": self.archive_path,
            "restored_path": self.restored_path,
            "status": self.status,
            "restored_at": self.restored_at,
        }


def _read_task_json(package_dir: Path) -> dict:
    path = package_dir / "task.json"
    if not path.exists():
        raise ArchiveError(ERR_TASK_JSON_UNREADABLE, f"缺少 task.json: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ArchiveError(ERR_TASK_JSON_UNREADABLE, f"task.json 不可读: {path} ({exc})") from exc
    if not isinstance(data, dict) or not data.get("task_id"):
        raise ArchiveError(ERR_TASK_JSON_UNREADABLE, f"task.json 缺少 task_id: {path}")
    return data


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.move(str(tmp), str(path))
    except OSError as exc:
        raise ArchiveError(ERR_METADATA_WRITE_FAILED, f"task.json 写入失败: {path} ({exc})") from exc


def archive_package(package_dir: Path | str, archive_root: Path | str) -> ArchiveResult:
    """将整个 Task Package 归档为 <archive_root>/<Task-ID>/。

    - 拒绝 CREATED / RUNNING（TASK_NOT_ARCHIVABLE），不移动任何文件
    - 目标已存在拒绝（ARCHIVE_TARGET_EXISTS），不覆盖其他包
    - 同卷 rename（shutil.move），保留全部产物
    - 归档后在 task.json 增加 archived_at metadata（不改 status）
    """
    package_dir = Path(package_dir)
    archive_root = Path(archive_root)
    if not package_dir.is_dir():
        raise ArchiveError(ERR_SOURCE_NOT_FOUND, f"Task package 不存在: {package_dir}")

    data = _read_task_json(package_dir)
    status = data.get("status", "")
    if status not in TERMINAL_STATUSES:
        raise ArchiveError(
            ERR_TASK_NOT_ARCHIVABLE,
            f"status={status} 不是终态（允许: {', '.join(TERMINAL_STATUSES)}），不得归档",
        )
    task_id = data["task_id"]
    target = archive_root / task_id
    if target.exists():
        raise ArchiveError(ERR_ARCHIVE_TARGET_EXISTS, f"归档目标已存在（禁止覆盖）: {target}")

    archive_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(package_dir), str(target))
    except OSError as exc:
        raise ArchiveError(ERR_MOVE_FAILED, f"归档移动失败（源未动）: {exc}") from exc

    # metadata（Execution Lifecycle 不变；Storage Lifecycle 记录）
    now = datetime.now().isoformat(timespec="seconds")
    archived = _read_task_json(target)
    archived["archived_at"] = now
    _atomic_write_json(target / "task.json", archived)

    return ArchiveResult(
        task_id=task_id,
        source_path=str(package_dir),
        archive_path=str(target),
        status=status,
        archived_at=now,
    )


def restore_package(archive_path: Path | str, active_root: Path | str) -> RestoreResult:
    """将 archived Task Package 恢复到 <active_root>/<Task-ID>/。

    - 不改变 task.json.status（WAITING 恢复后仍是 WAITING）
    - 目标已存在拒绝（RESTORE_TARGET_EXISTS），不产生双份权威 package
    """
    archive_path = Path(archive_path)
    active_root = Path(active_root)
    if not archive_path.is_dir():
        raise ArchiveError(ERR_SOURCE_NOT_FOUND, f"archive package 不存在: {archive_path}")

    data = _read_task_json(archive_path)
    task_id = data["task_id"]
    status = data.get("status", "")
    target = active_root / task_id
    if target.exists():
        raise ArchiveError(ERR_RESTORE_TARGET_EXISTS, f"恢复目标已存在（禁止覆盖）: {target}")

    active_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(archive_path), str(target))
    except OSError as exc:
        raise ArchiveError(ERR_MOVE_FAILED, f"恢复移动失败（源未动）: {exc}") from exc

    # 清除 storage metadata（archived_at）：restore 后已不在 archive
    restored_data = _read_task_json(target)
    restored_data.pop("archived_at", None)
    _atomic_write_json(target / "task.json", restored_data)

    return RestoreResult(
        task_id=task_id,
        archive_path=str(archive_path),
        restored_path=str(target),
        status=status,
        restored_at=datetime.now().isoformat(timespec="seconds"),
    )


def archived_report_path(report_path: Path | str | None) -> Path | None:
    """把 active 位置的 REPORT 路径推导为 archive 变体。

    例：<ws>/.aaf/<Task-ID>/REPORT.md → <ws>/.aaf/archive/<Task-ID>/REPORT.md
    供 Bridge Copy Last Report 在任务归档后兜底定位（不修改 last_run.json）。
    """
    if not report_path:
        return None
    parts = Path(report_path).parts
    for i, part in enumerate(parts):
        if part == ".aaf" and i + 2 < len(parts):
            return Path(*parts[: i + 1], ARCHIVE_DIR_NAME, parts[i + 1], *parts[i + 2 :])
    return None


def find_report_path(task_id: str, workspace: Path | str, report_file: str = "REPORT.md") -> Path | None:
    """按 Task ID 定位正式 REPORT：active 优先，archive 兜底；找不到 → None。"""
    ws = Path(workspace)
    active = ws / ".aaf" / task_id / report_file
    if active.exists():
        return active
    archived = ws / ".aaf" / ARCHIVE_DIR_NAME / task_id / report_file
    if archived.exists():
        return archived
    return None
