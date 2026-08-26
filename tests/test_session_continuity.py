"""AI Agent Framework — Session Continuity 测试。"""
import json
from pathlib import Path
import pytest

from ai_agent_framework.session_continuity import (
    MAX_RECENT_TASKS,
    UNKNOWN,
    SessionError,
    current_dir,
    rollover,
    session_archive_dir,
    session_id,
)


def _ws(tmp_path) -> Path:
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    return ws


def _make_task(ws: Path, task_id: str, status="SUCCESS", updated="2026-01-01T00:00:00", archived=False):
    base = ws / ".aaf" / ("archive" if archived else "") / task_id if archived else ws / ".aaf" / task_id
    base.mkdir(parents=True)
    (base / "task.json").write_text(json.dumps({
        "task_id": task_id, "status": status, "updated_at": updated,
        "task_path": "T.md", "workspace": str(ws), "report_path": str(base / "REPORT.md"),
    }, ensure_ascii=False), encoding="utf-8")
    (base / "REPORT.md").write_text(f"# REPORT {task_id}\n## Current Status\n{status}\n结论", encoding="utf-8")
    return base


def _summary_text(result) -> str:
    return Path(result.summary_path).read_text(encoding="utf-8")


def _next_text(result) -> str:
    return Path(result.next_start_path).read_text(encoding="utf-8")


# ---------- first rollover + 文件生成 ----------

def test_first_rollover_generates_files(tmp_path):
    ws = _ws(tmp_path)
    r = rollover(ws, project="测试项目", phase="v0.3", core_goal="接通链路",
                 frozen_boundaries="冻结 000-A", next_step="下一步 004")
    assert r.archived_previous is None
    assert Path(r.summary_path).exists()
    assert Path(r.next_start_path).exists()
    assert (current_dir(ws) / "session.json").exists()
    assert r.session_id == session_id()


def test_session_summary_required_sections(tmp_path):
    ws = _ws(tmp_path)
    r = rollover(ws, project="P", phase="ph", core_goal="g", frozen_boundaries="fb",
                 completed_work="cw", open_items="oi", blocking_issues="bi",
                 important_decisions="id", relevant_task_ids="T-1", next_step="ns", do_not_reopen="dnr")
    text = _summary_text(r)
    for section in ("# SESSION SUMMARY", "Project:", "Workspace:", "Session ID:",
                    "## Current Phase", "## Core Goal", "## Frozen Boundaries",
                    "## Completed Work", "## Current State", "## Open Items",
                    "## Blocking Issues", "## Important Decisions",
                    "## Relevant Task IDs", "## What NOT to Reopen",
                    "## Next Recommended Step"):
        assert section in text


def test_next_session_start_required_sections_and_short(tmp_path):
    ws = _ws(tmp_path)
    r = rollover(ws, project="P", phase="ph", core_goal="g", frozen_boundaries="fb",
                 open_items="oi", next_step="ns", do_not_reopen="dnr",
                 relevant_task_ids="T-1")
    text = _next_text(r)
    for section in ("# NEXT SESSION START", "This project is:", "Current phase:",
                    "Current objective:", "## Frozen Boundaries", "## Latest Completed Task",
                    "## Current Unresolved Items", "## Immediate Next Step",
                    "## Files to Read First", "## Do NOT reopen completed scope"):
        assert section in text
    # NEXT 不复制完整历史：结构上不含 Recent Task Snapshot / 完整字段列表
    assert "## Recent Task Snapshot" not in text


def test_no_full_history_dump(tmp_path):
    """bounded：只纳入最近任务，不把全部历史写进文件。"""
    ws = _ws(tmp_path)
    for i in range(MAX_RECENT_TASKS + 4):
        _make_task(ws, f"T-{i}", status="SUCCESS", updated=f"2026-01-0{i+1:02d}T00:00:00")
    r = rollover(ws)
    text = _summary_text(r)
    # 只列出最近 N 个（不是全部）——最新 3 个是 T-6/T-5/T-4，T-3 已超出
    assert f"T-{MAX_RECENT_TASKS - 1}" not in text  # "T-2" 级更早任务也不在（用唯一子串）
    assert "T-3" not in text
    assert "T-6" in text and "T-4" in text
    assert len(r.recent_tasks) == MAX_RECENT_TASKS


# ---------- PROJECT_STATE ----------

def test_missing_project_state_unknown(tmp_path):
    ws = _ws(tmp_path)
    r = rollover(ws)
    text = _summary_text(r)
    assert "## Core Goal\nUNKNOWN" in text  # 明确 UNKNOWN，不猜测
    assert UNKNOWN in text


def test_reads_project_state_sections(tmp_path):
    ws = _ws(tmp_path)
    (ws / "PROJECT_STATE.md").write_text(
        "# Project State\n\n## Current Phase\nv0.3 阶段\n\n## Core Goal\n接通链路\n\n"
        "## Frozen Boundaries\n000-A 冻结\n\n## Next Step\n做 004\n",
        encoding="utf-8")
    r = rollover(ws)
    text = _summary_text(r)
    assert "## Current Phase\nv0.3 阶段" in text
    assert "## Core Goal\n接通链路" in text
    assert "## Frozen Boundaries\n000-A 冻结" in text
    assert "## Next Recommended Step\n做 004" in text


# ---------- current archive / 覆盖保护 ----------

def test_second_rollover_archives_previous(tmp_path):
    ws = _ws(tmp_path)
    r1 = rollover(ws, project="P1")
    r2 = rollover(ws, project="P2")
    assert r2.archived_previous is not None
    archive_path = Path(r2.archived_previous)
    assert archive_path.exists()
    assert (archive_path / "SESSION_SUMMARY.md").exists()  # 前一个完整归档
    assert "P1" in (archive_path / "SESSION_SUMMARY.md").read_text(encoding="utf-8")  # 内容属前一个 session


def test_duplicate_session_archive_target_reject(tmp_path):
    ws = _ws(tmp_path)
    r1 = rollover(ws)
    # 手工制造 archive 目标已存在（同 sid）
    target = session_archive_dir(ws) / r1.session_id
    target.mkdir(parents=True)
    with pytest.raises(SessionError) as ei:
        rollover(ws)
    assert "禁止覆盖" in str(ei.value)


def test_archived_previous_preserved_on_error(tmp_path):
    """归档前一个失败（目标已存在）→ current 不被破坏。"""
    ws = _ws(tmp_path)
    r1 = rollover(ws)
    target = session_archive_dir(ws) / r1.session_id
    target.mkdir(parents=True)
    with pytest.raises(SessionError):
        rollover(ws)
    # current 仍是第一个 session 的文件（未动）
    assert (current_dir(ws) / "SESSION_SUMMARY.md").exists()
    assert (current_dir(ws) / "NEXT_SESSION_START.md").exists()


# ---------- 状态不变 / 有界 / archived REPORT ----------

def test_no_task_status_mutation(tmp_path):
    ws = _ws(tmp_path)
    _make_task(ws, "T-1", status="WAITING")
    rollover(ws)
    data = json.loads((ws / ".aaf" / "T-1" / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "WAITING"  # rollover 不改任务状态


def test_archived_report_resolution(tmp_path):
    """recent task 已归档 → 通过 resolver 找到 archived REPORT 摘要。"""
    ws = _ws(tmp_path)
    _make_task(ws, "T-OLD", status="SUCCESS", updated="2026-01-01T00:00:00", archived=True)
    r = rollover(ws)
    assert len(r.recent_tasks) == 1
    assert r.recent_tasks[0]["task_id"] == "T-OLD"
    assert "SUCCESS" in r.recent_tasks[0]["report"]  # 摘要来自 archived REPORT


def test_task_ids_explicit_priority(tmp_path):
    ws = _ws(tmp_path)
    _make_task(ws, "T-A", status="SUCCESS", updated="2026-01-02T00:00:00")
    _make_task(ws, "T-B", status="FAILED", updated="2026-01-03T00:00:00")
    r = rollover(ws, relevant_task_ids="T-A")
    assert r.recent_tasks[0]["task_id"] == "T-A"  # 显式优先


# ---------- 确定性 / 无 agent ----------

def test_deterministic_with_same_inputs(tmp_path):
    """相同输入 → 相同结构（确定性模板）。"""
    ws1 = tmp_path / "projA"
    ws1.mkdir()
    _make_task(ws1, "T-1", status="SUCCESS", updated="2026-01-01T00:00:00")
    r1 = rollover(ws1, project="P", phase="ph", core_goal="g")
    t1 = _summary_text(r1)
    ws2 = tmp_path / "projB"
    ws2.mkdir()
    _make_task(ws2, "T-1", status="SUCCESS", updated="2026-01-01T00:00:00")
    r2 = rollover(ws2, project="P", phase="ph", core_goal="g")
    t2 = _summary_text(r2)
    # 相同输入 → 相同字段结构（session id/时间戳/路径会不同，只比较结构）
    assert "## Core Goal\ng" in t1 and "## Core Goal\ng" in t2
    assert "## Current Phase\nph" in t1 and "## Current Phase\nph" in t2


def test_no_agent_imports(tmp_path):
    """Session Continuity 不依赖/不调用 Agent 模块。"""
    import ai_agent_framework.session_continuity as sc
    src = Path(sc.__file__).read_text(encoding="utf-8")
    for forbidden in ("run_agent", "adapters", "decide_route", "hermes", "workbuddy", "codex"):
        assert forbidden not in src
