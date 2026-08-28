"""Phase F（AAF-v0.4-TASK-006）— Bridge TASK 提交流程决策单元测试。

覆盖 TASK req 1–12 的决策矩阵（不弹 UI，纯逻辑）：
- req 1/2：SAME → proceed（无额外确认）
- req 3：KNOWN → confirm_switch（明确显示当前/目标项目）
- req 4：UNKNOWN → confirm_unknown（fail-safe 暂停）
- req 5：INVALID → reject fail closed（路径不存在/相对/非目录/malformed）
- req 7：launcher RUNNING → 不同 workspace 拒绝切换（running_blocked）
- req 9：duplicate RUNNING → reject（不启动第二份 runner）
- req 10：duplicate completed/unknown → reject + 状态卡片（不覆盖 artifacts）
- req 6/12：apply_submission 切换持久化 + 落盘；不改写 Task ID / Workspace
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bridge import config as cfg_mod
from bridge import duplicate as dup_mod
from bridge import intake
from bridge import task_io
from bridge import workspace as ws_mod


def _task_text(ws: str, task_id: str = "F-001") -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: Phase F intake 测试
Workspace: {ws}

Objective:
验证提交流程决策

Acceptance:
1. 通过
AAF_TASK_END"""


def _ws(tmp_path: Path, name: str = "ws-a") -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _cfg(tmp_path: Path, workspace: Path, project: str = "Current Project") -> dict:
    cfg_path = tmp_path / "cfg" / "config.json"
    cfg = cfg_mod.update_project(project, str(workspace), cfg_path)
    return cfg


def _idle_launcher():
    return SimpleNamespace(state="IDLE", current=None)


def _running_launcher(task_id: str = "T-RUNNING"):
    return SimpleNamespace(state="RUNNING", current=SimpleNamespace(task_id=task_id))


@pytest.fixture()
def bridge_dir(tmp_path, monkeypatch):
    """registry 隔离：list_launches 读 AAF_BRIDGE_DIR。"""
    d = tmp_path / "aaf-bridge"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(d))
    return d


def _write_active_registry(bridge_dir: Path, ws: Path, task_id: str, state: str = "RUNNING") -> Path:
    reg_root = bridge_dir / "launches"
    reg_root.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": 1,
        "launch_id": "launch-phasef-1",
        "task_id": task_id,
        "workspace": str(ws),
        "output_dir": str(ws / ".aaf" / task_id),
        "expected_runner_entry": "run.py",
        "expected_command_line": ["py", "run.py", "task.md"],
        "launcher_instance_id": "inst-1",
        "created_at": "2026-08-28T10:00:00",
        "runner_pid": 1234,
        "runner_creation_time": "2026-08-28T10:00:00.000",
        "state": state,
    }
    p = reg_root / f"{data['launch_id']}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _save_task(ws: Path, task_id: str) -> Path:
    target = task_io.task_target_path(str(ws), task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_task_text(str(ws), task_id), encoding="utf-8")
    return target


# ---------- req 2：SAME → proceed（无额外确认） ----------

def test_same_workspace_proceeds_without_confirm(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    plan = intake.plan_submission(_task_text(str(ws)), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_PROCEED
    assert not plan.switch_workspace
    assert plan.is_same
    assert plan.duplicate is None
    assert not plan.reasons


def test_same_workspace_case_insensitive(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    plan = intake.plan_submission(_task_text(str(ws).upper()), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_PROCEED


# ---------- req 3：KNOWN → confirm_switch ----------

def test_known_workspace_requires_switch_confirm(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "known-proj")
    cfg = _cfg(tmp_path, cur)
    cfg_path = tmp_path / "cfg" / "config.json"
    # 先切到 other（进入 recent_projects），再切回 cur → other = 已知但非当前
    cfg_mod.update_project("Known Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg = cfg_mod.load_config(cfg_path)
    plan = intake.plan_submission(_task_text(str(other)), cfg, _idle_launcher(), cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_SWITCH
    assert plan.switch_workspace
    assert plan.is_known
    assert plan.target_project == "Known Project"
    assert plan.current_workspace == str(cur)


# ---------- req 4：UNKNOWN → confirm_unknown ----------

def test_unknown_workspace_fail_safe_confirm(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "brand-new")
    cfg = _cfg(tmp_path, cur)
    plan = intake.plan_submission(_task_text(str(other)), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_CONFIRM_UNKNOWN
    assert plan.switch_workspace
    assert not plan.is_known
    assert plan.target_project == "brand-new"


# ---------- req 5：INVALID → reject fail closed ----------

@pytest.mark.parametrize("bad", ["", "relative\\path", "   "])
def test_invalid_workspace_rejected(tmp_path, bridge_dir, bad):
    cur = _ws(tmp_path, "current")
    cfg = _cfg(tmp_path, cur)
    plan = intake.plan_submission(_task_text(bad), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.reasons


def test_missing_path_workspace_rejected(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    cfg = _cfg(tmp_path, cur)
    plan = intake.plan_submission(
        _task_text(str(tmp_path / "does-not-exist")), cfg, _idle_launcher(),
        cfg_path=tmp_path / "cfg" / "config.json",
    )
    assert plan.action == intake.ACTION_REJECT
    assert any("不存在" in r for r in plan.reasons)


def test_non_dir_workspace_rejected(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    cfg = _cfg(tmp_path, cur)
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    plan = intake.plan_submission(_task_text(str(f)), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert any("不是目录" in r for r in plan.reasons)


def test_missing_required_fields_rejected(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    text = _task_text(str(ws)).replace("Task Name: Phase F intake 测试\n", "")
    plan = intake.plan_submission(text, cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert any("Task Name" in r for r in plan.reasons)


def test_unsafe_task_id_rejected(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    plan = intake.plan_submission(_task_text(str(ws), "BAD/ID"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert any("不安全文件名字符" in r for r in plan.reasons)


def test_missing_markers_rejected(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    plan = intake.plan_submission("no markers here", cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT


# ---------- req 7：RUNNING 时不得切换 ----------

def test_running_blocks_workspace_switch(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "other")
    cfg = _cfg(tmp_path, cur)
    plan = intake.plan_submission(_task_text(str(other)), cfg, _running_launcher("T-RUN-1"), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.running_blocked
    assert plan.running_task_id == "T-RUN-1"
    assert any("正在运行" in r for r in plan.reasons)
    assert any("不能切换项目" in r for r in plan.reasons)


def test_running_same_workspace_still_proceeds(tmp_path, bridge_dir):
    """RUNNING + 同 workspace 新任务 → 决策放行（第二 runner 由 launcher 既有并发保护拒绝）。"""
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    plan = intake.plan_submission(_task_text(str(ws), "F-NEW"), cfg, _running_launcher("T-RUN-1"), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_PROCEED
    assert not plan.running_blocked


# ---------- req 9：duplicate RUNNING → 不启动第二 runner ----------

def test_duplicate_running_rejected(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-DUP")
    _write_active_registry(bridge_dir, ws, "F-DUP")
    plan = intake.plan_submission(_task_text(str(ws), "F-DUP"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None
    assert plan.duplicate.kind == dup_mod.KIND_RUNNING
    assert any("正在运行" in r for r in plan.reasons)
    assert any("第二份 runner" in r for r in plan.reasons)


def test_duplicate_running_via_launcher_current(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-DUP")
    plan = intake.plan_submission(_task_text(str(ws), "F-DUP"), cfg, _running_launcher("F-DUP"), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None and plan.duplicate.kind == dup_mod.KIND_RUNNING


# ---------- req 10：duplicate terminal → reject + 卡片 + 不覆盖 ----------

def test_duplicate_completed_rejected_with_card(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-DONE")
    # 完成态 artifacts（真实 lifecycle 终态路径：finalize_terminal）
    from ai_agent_framework import task_lifecycle
    task_dir = ws / ".aaf" / "F-DONE"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "REPORT.md").write_text("## Current Status\nSUCCESS\n", encoding="utf-8")
    task_lifecycle.finalize_terminal(task_dir, task_id="F-DONE", status="SUCCESS",
                                     task_path=str(ws / ".aaf" / "tasks" / "active" / "F-DONE.md"),
                                     workspace=str(ws), report_path=str(task_dir / "REPORT.md"),
                                     stage="COMPLETED", phase_state="SUCCESS")
    target_before = _save_task(ws, "F-DONE").read_bytes()

    plan = intake.plan_submission(_task_text(str(ws), "F-DONE"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None
    assert plan.duplicate.kind == dup_mod.KIND_COMPLETED
    assert plan.duplicate.report_path is not None
    assert any("新 Task ID" in r for r in plan.reasons)
    # 未写入任何文件：TASK.md 未被覆盖
    assert _save_task(ws, "F-DONE") is not None
    assert (ws / ".aaf" / "tasks" / "active" / "F-DONE.md").read_bytes() == target_before


def test_duplicate_unknown_rejected(tmp_path, bridge_dir):
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-GHOST")
    plan = intake.plan_submission(_task_text(str(ws), "F-GHOST"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_REJECT
    assert plan.duplicate is not None and plan.duplicate.kind == dup_mod.KIND_UNKNOWN


def test_new_task_id_after_terminal_is_legal(tmp_path, bridge_dir):
    """已完成任务后，用新 Task ID 重新提交 → 合法（proceed）。"""
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-DONE")
    plan = intake.plan_submission(_task_text(str(ws), "F-NEXT"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.action == intake.ACTION_PROCEED
    assert plan.duplicate is None


# ---------- req 6/12：apply_submission 切换持久化 + 落盘 ----------

def test_apply_switch_persists_and_saves(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "target")
    cfg = _cfg(tmp_path, cur)
    cfg_path = tmp_path / "cfg" / "config.json"
    # 构造「已知但非当前」：先切到 other，再切回 cur
    cfg_mod.update_project("Target Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg = cfg_mod.load_config(cfg_path)
    plan = intake.plan_submission(_task_text(str(other), "F-SW"), cfg, _idle_launcher(), cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_SWITCH

    target = intake.apply_submission(plan, cfg_path)
    # 配置已持久化（req 6）
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_workspace"] == str(other)
    assert on_disk["current_project"] == "Target Project"
    # recent_projects 置顶
    assert on_disk["recent_projects"][0]["workspace"] == str(other)
    # TASK.md 落在目标 workspace（req 12：不改写 Workspace）
    assert target == task_io.task_target_path(str(other), "F-SW")
    assert target.exists()


def test_apply_unknown_switch_records_recent(tmp_path, bridge_dir):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "brand-new")
    cfg = _cfg(tmp_path, cur)
    cfg_path = tmp_path / "cfg" / "config.json"
    plan = intake.plan_submission(_task_text(str(other)), cfg, _idle_launcher(), cfg_path=cfg_path)
    assert plan.action == intake.ACTION_CONFIRM_UNKNOWN
    intake.apply_submission(plan, cfg_path)
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_workspace"] == str(other)
    assert on_disk["recent_projects"][0]["workspace"] == str(other)
    # 切回 cur 后，再次提交 other（新 Task ID）→ 已变为已知（confirm_switch 而非 confirm_unknown）
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    on_disk = cfg_mod.load_config(cfg_path)
    plan2 = intake.plan_submission(_task_text(str(other), "F-002"), on_disk, _idle_launcher(), cfg_path=cfg_path)
    assert plan2.action == intake.ACTION_CONFIRM_SWITCH
    assert plan2.is_known


def test_apply_does_not_overwrite_existing_terminal(tmp_path, bridge_dir):
    """apply 前 duplicate 保护仍生效（save_task TASK_ALREADY_EXISTS 兜底）。"""
    ws = _ws(tmp_path)
    cfg = _cfg(tmp_path, ws)
    _save_task(ws, "F-EXIST")
    plan = intake.plan_submission(_task_text(str(ws), "F-EXIST"), cfg, _idle_launcher(), cfg_path=tmp_path / "cfg" / "config.json")
    assert plan.is_reject
    with pytest.raises(task_io.TaskParseError):
        intake.apply_submission(plan, tmp_path / "cfg" / "config.json")
