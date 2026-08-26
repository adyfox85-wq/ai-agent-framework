"""AI Agent Framework — Task Artifact Archive 测试。"""
import json
from pathlib import Path
import pytest

from ai_agent_framework.task_archive import (
    ArchiveError,
    ArchiveResult,
    RestoreResult,
    archived_report_path,
    archive_package,
    find_report_path,
    restore_package,
)
from bridge import handoff


def _make_package(tmp_path, task_id="T-001", status="SUCCESS", extra_files=("route.json", "run.json", "REPORT.md", "hermes_result.md")):
    """构造真实结构的 Task Package：<root>/.aaf/<Task-ID>/。"""
    pkg = tmp_path / ".aaf" / task_id
    pkg.mkdir(parents=True)
    (pkg / "task.json").write_text(json.dumps({
        "task_id": task_id, "status": status, "updated_at": "2026-01-01T00:00:00",
        "task_path": str(pkg / "TASK.md"), "workspace": str(tmp_path),
        "report_path": str(pkg / "REPORT.md"),
    }, ensure_ascii=False), encoding="utf-8")
    for name in extra_files:
        (pkg / name).write_text(f"content-{name}", encoding="utf-8")
    return pkg


def _package_files(pkg: Path):
    return sorted(str(p.relative_to(pkg)) for p in pkg.rglob("*") if p.is_file())


# ---------- 终态可归档 ----------

@pytest.mark.parametrize("status", ["SUCCESS", "WAITING", "FAILED"])
def test_terminal_status_archive(tmp_path, status):
    pkg = _make_package(tmp_path, status=status)
    before = _package_files(pkg)
    result = archive_package(pkg, tmp_path / ".aaf" / "archive")
    assert isinstance(result, ArchiveResult)
    assert result.task_id == "T-001"
    assert result.status == status
    assert not pkg.exists()  # 源已移动
    archived = tmp_path / ".aaf" / "archive" / "T-001"
    assert archived.is_dir()
    assert _package_files(archived) == before  # 全部产物保留


# ---------- 非终态拒绝 ----------

@pytest.mark.parametrize("status", ["CREATED", "RUNNING"])
def test_non_terminal_reject_no_mutation(tmp_path, status):
    pkg = _make_package(tmp_path, status=status)
    before = _package_files(pkg)
    with pytest.raises(ArchiveError) as ei:
        archive_package(pkg, tmp_path / ".aaf" / "archive")
    assert ei.value.code == "TASK_NOT_ARCHIVABLE"
    assert pkg.exists()  # source 未变化
    assert _package_files(pkg) == before
    assert not (tmp_path / ".aaf" / "archive").exists()  # 未移动任何文件


# ---------- 状态与存储分离 ----------

def test_status_unchanged_after_archive(tmp_path):
    pkg = _make_package(tmp_path, status="SUCCESS")
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    data = json.loads((tmp_path / ".aaf" / "archive" / "T-001" / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "SUCCESS"  # 不得变成 ARCHIVED
    assert data["archived_at"]  # metadata 已写


# ---------- 覆盖保护 ----------

def test_duplicate_archive_target_reject(tmp_path):
    pkg = _make_package(tmp_path)
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    # 再构造一个同 ID 的 active package → 目标已存在
    pkg2 = _make_package(tmp_path, task_id="T-001", status="FAILED")
    with pytest.raises(ArchiveError) as ei:
        archive_package(pkg2, tmp_path / ".aaf" / "archive")
    assert ei.value.code == "ARCHIVE_TARGET_EXISTS"
    assert pkg2.exists()  # 源未动


def test_duplicate_restore_target_reject(tmp_path):
    pkg = _make_package(tmp_path, status="WAITING")
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    # active 已有同 ID package（模拟异常双份）
    _make_package(tmp_path, task_id="T-001", status="FAILED")
    with pytest.raises(ArchiveError) as ei:
        restore_package(tmp_path / ".aaf" / "archive" / "T-001", tmp_path / ".aaf")
    assert ei.value.code == "RESTORE_TARGET_EXISTS"


# ---------- 归档失败行为 ----------

def test_archive_source_missing(tmp_path):
    with pytest.raises(ArchiveError) as ei:
        archive_package(tmp_path / "nope", tmp_path / ".aaf" / "archive")
    assert ei.value.code == "SOURCE_NOT_FOUND"


def test_archive_task_json_missing(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "REPORT.md").write_text("x", encoding="utf-8")
    with pytest.raises(ArchiveError) as ei:
        archive_package(pkg, tmp_path / ".aaf" / "archive")
    assert ei.value.code == "TASK_JSON_UNREADABLE"
    assert pkg.exists()  # 未移动


# ---------- REPORT 定位（active → archive） ----------

def test_report_resolve_after_archive(tmp_path):
    pkg = _make_package(tmp_path)
    report_active = pkg / "REPORT.md"
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    assert not report_active.exists()
    found = find_report_path("T-001", tmp_path)
    assert found == tmp_path / ".aaf" / "archive" / "T-001" / "REPORT.md"
    assert found.exists()


def test_archived_report_path_conversion():
    p = Path(r"D:\ws\.aaf\T-9\REPORT.md")
    assert archived_report_path(p) == Path(r"D:\ws\.aaf\archive\T-9\REPORT.md")
    assert archived_report_path(None) is None
    assert archived_report_path(Path(r"D:\ws\REPORT.md")) is None  # 无 .aaf 段


# ---------- Bridge Copy Last Report 兼容 ----------

def test_bridge_read_report_archived_fallback(tmp_path):
    pkg = _make_package(tmp_path)
    original_report = pkg / "REPORT.md"
    original_report.write_text("# REPORT\n归档后的正文", encoding="utf-8")
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    # last_run 仍指向原路径（已失效）→ read_report 兜底读取 archived
    text = handoff.read_report(str(original_report))
    assert text == "# REPORT\n归档后的正文"


def test_unrelated_last_run_unchanged(tmp_path):
    """非归档任务的 last_run 指向不存在路径 → read_report 返回 None，且不修改任何文件。"""
    missing = tmp_path / ".aaf" / "T-X" / "REPORT.md"
    assert handoff.read_report(str(missing)) is None
    assert not missing.exists()  # 无副作用


def test_bridge_read_report_no_archive_no_fallback(tmp_path):
    """原路径不存在且无 archive 变体 → None（不造假）。"""
    missing = tmp_path / ".aaf" / "T-X" / "REPORT.md"
    assert handoff.read_report(str(missing)) is None


# ---------- Restore ----------

def test_restore_waiting_status_unchanged(tmp_path):
    pkg = _make_package(tmp_path, status="WAITING")
    archive_package(pkg, tmp_path / ".aaf" / "archive")
    result = restore_package(tmp_path / ".aaf" / "archive" / "T-001", tmp_path / ".aaf")
    assert isinstance(result, RestoreResult)
    assert result.status == "WAITING"
    restored = tmp_path / ".aaf" / "T-001"
    assert restored.is_dir()
    data = json.loads((restored / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "WAITING"  # restore 不改状态
    assert not (tmp_path / ".aaf" / "archive" / "T-001").exists()
    # restore 后可正常 resume（runner 接受 active 路径）
    assert (restored / "route.json").exists()
