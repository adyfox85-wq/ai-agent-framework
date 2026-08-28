"""Phase F（AAF-v0.4-TASK-006）— Duplicate Task 状态识别单元测试。

覆盖 TASK req 8–10：
- 同 Task ID 正在运行（registry 活跃 / launcher 当前）→ running（req 9）
- 同 Task ID 已完成（SUCCESS / WAITING / FAILED / CANCELLED）→ completed（req 10）
- 同 Task ID 状态异常（残留 RUNNING / CREATED）→ abnormal
- 同 Task ID 状态未知（无 task.json）→ unknown
- 新任务 → None（可以合法重新提交）
- REPORT 路径解析（task.json.report_path → find_report_path 归档兜底）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_agent_framework import task_lifecycle
from ai_agent_framework.task_lifecycle import read_status

from bridge import duplicate as dup_mod
from bridge import task_io
from bridge.launch_registry import (
    REGISTRY_STATE_PREPARED,
    REGISTRY_STATE_RUNNING,
    create_prepared,
    mark_running,
)

VALID_TASK = """# Task ID
DUP-001

# Task Name
duplicate test

# Objective
验证 duplicate 识别

# Acceptance
1. 通过
"""


def _workspace(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir(exist_ok=True)
    return ws


def _save_task(ws: Path, task_id: str = "DUP-001") -> Path:
    body = VALID_TASK.replace("DUP-001", task_id)
    target = task_io.task_target_path(str(ws), task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def _task_dir(ws: Path, task_id: str = "DUP-001") -> Path:
    return ws / ".aaf" / task_id


def _status_json(ws: Path, task_id: str, status: str, *, report_path: str | None = None) -> dict:
    task_dir = _task_dir(ws, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    task_file = task_dir / "TASK.md"
    task_file.write_text(VALID_TASK.replace("DUP-001", task_id), encoding="utf-8")
    if status in task_lifecycle.TERMINAL_STATUSES:
        # 终态必须经 finalize_terminal（与真实执行链同一写入路径）
        task_lifecycle.finalize_terminal(
            task_dir, task_id=task_id, status=status,
            task_path=str(task_file), workspace=str(ws), report_path=report_path,
            stage="COMPLETED",
            phase_state=("SUCCESS" if status in ("SUCCESS", "WAITING") else None),
        )
    else:
        task_lifecycle.update_status(
            task_dir, task_id=task_id, status=status,
            task_path=str(task_file), workspace=str(ws), report_path=report_path,
        )
    return read_status(task_dir)


# ---------- 新任务 / 不存在的判定 ----------

def test_inspect_none_for_new_task(tmp_path):
    ws = _workspace(tmp_path)
    assert dup_mod.inspect_duplicate("DUP-NEW", str(ws), []) is None


def test_inspect_none_when_no_workspace():
    assert dup_mod.inspect_duplicate("DUP-001", "", []) is None
    assert dup_mod.inspect_duplicate("", "D:\\x", []) is None


# ---------- running（req 9） ----------

def test_inspect_running_via_active_registry(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    launch = {
        "launch_id": "l1", "task_id": "DUP-001", "workspace": str(ws),
        "state": REGISTRY_STATE_RUNNING, "output_dir": "x",
    }
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [launch])
    assert info is not None
    assert info.kind == dup_mod.KIND_RUNNING
    assert info.status == "RUNNING"
    assert info.status_cn == "执行中"
    assert info.report_path is None  # RUNNING 无 REPORT（§10.3）
    assert "不启动第二份 runner" in info.reason


def test_inspect_running_via_launcher_current(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [], launcher_current_task_id="DUP-001")
    assert info is not None
    assert info.kind == dup_mod.KIND_RUNNING


def test_inspect_running_via_prepared_registry(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    launch = {
        "launch_id": "l1", "task_id": "DUP-001", "workspace": str(ws),
        "state": REGISTRY_STATE_PREPARED, "output_dir": "x",
    }
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [launch])
    assert info is not None and info.kind == dup_mod.KIND_RUNNING


# ---------- completed（req 10） ----------

@pytest.mark.parametrize("status", ["SUCCESS", "WAITING", "FAILED", "CANCELLED"])
def test_inspect_completed_terminal(tmp_path, status):
    ws = _workspace(tmp_path)
    _save_task(ws)
    task_dir = _task_dir(ws)
    task_dir.mkdir(parents=True, exist_ok=True)
    report = task_dir / "REPORT.md"
    report.write_text(f"## Current Status\n{status}\n", encoding="utf-8")
    _status_json(ws, "DUP-001", status, report_path=str(report))
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.kind == dup_mod.KIND_COMPLETED
    assert info.status == status
    assert info.report_path == str(report)
    assert "需新 Task ID" in info.reason


def test_inspect_completed_cn_labels(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    _status_json(ws, "DUP-001", "SUCCESS")
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info.status_cn == "已完成"


# ---------- abnormal / unknown ----------

def test_inspect_abnormal_stale_running(tmp_path):
    """task.json=RUNNING 但无活跃 launch → 状态异常（残留，非 running）。"""
    ws = _workspace(tmp_path)
    _save_task(ws)
    _status_json(ws, "DUP-001", "RUNNING")
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.kind == dup_mod.KIND_ABNORMAL
    assert info.status == "RUNNING"
    assert "状态异常" in info.reason


def test_inspect_abnormal_created(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    _status_json(ws, "DUP-001", "CREATED")
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.kind == dup_mod.KIND_ABNORMAL


def test_inspect_unknown_no_task_json(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.kind == dup_mod.KIND_UNKNOWN
    assert info.status_cn == "状态未知"


def test_inspect_duplicate_basis_is_task_md_existence(tmp_path):
    """判定基础 = canonical TASK.md 存在（与 save_task 同一判定；UX 不改变判定）。"""
    ws = _workspace(tmp_path)
    # 无 task.json、无 task 目录 → 依然 duplicate
    _save_task(ws)
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.kind == dup_mod.KIND_UNKNOWN


# ---------- REPORT 路径解析 ----------

def test_inspect_report_path_from_task_json(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    task_dir = _task_dir(ws)
    task_dir.mkdir(parents=True, exist_ok=True)
    report = task_dir / "REPORT.md"
    report.write_text("ok", encoding="utf-8")
    _status_json(ws, "DUP-001", "SUCCESS", report_path=str(report))
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info.report_path == str(report)


def test_inspect_report_path_fallback_archive(tmp_path):
    """task.json 无 report_path → find_report_path 归档兜底（§10.2/§10.3）。"""
    ws = _workspace(tmp_path)
    _save_task(ws)
    # 归档布局：.aaf/archive/<id>/REPORT.md
    archived = ws / ".aaf" / "archive" / "DUP-001" / "REPORT.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("archived report", encoding="utf-8")
    _status_json(ws, "DUP-001", "SUCCESS")
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info.report_path is not None
    assert Path(info.report_path) == archived


def test_active_launch_for_task_id_filters():
    launches = [
        {"launch_id": "l1", "task_id": "AAA", "state": "RUNNING"},
        {"launch_id": "l2", "task_id": "BBB", "state": "RUNNING"},
    ]
    assert dup_mod.active_launch_for_task_id("BBB", launches)["launch_id"] == "l2"
    assert dup_mod.active_launch_for_task_id("CCC", launches) is None
    assert dup_mod.active_launch_for_task_id("AAA", None) is None


def test_last_activity_uses_artifact_mtime(tmp_path):
    ws = _workspace(tmp_path)
    _save_task(ws)
    d = _task_dir(ws)
    d.mkdir(parents=True)
    (d / "a.txt").write_text("x", encoding="utf-8")
    info = dup_mod.inspect_duplicate("DUP-001", str(ws), [])
    assert info is not None
    assert info.last_activity is not None
