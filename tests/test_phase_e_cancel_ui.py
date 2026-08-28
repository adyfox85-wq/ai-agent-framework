"""Phase E / TASK-005-C — Status Window Cancel UX 测试（req 1–10 / acceptance 1–8）。

覆盖：
A. derive_cancel_ui 状态机全矩阵（req 2：正在运行/请求停止/正在取消/已取消/
   已完成/停止失败/无法安全停止）
B. Stop 入口守卫（req 1：terminal / 无任务 / 不可验证 → 不提供误导 Stop）
C. Soft cancel first（req 3：Stop 只写 cancel.request；UI 不写 terminal）
D. Soft timeout 不自动 force kill（req 4/17：超时只出现 force option，无自动终止）
E. Force 二次确认（req 4/5：confirm=False 不触发 backend）
F. Force eligibility fail closed（req 6：backend 不明确 eligible → 无 Force）
G. UI Authority Boundary（req 7：status_window 无 terminal 写路径 / 无 taskkill）
H. Canonical winner（req 8：normal completion vs cancel request → 跟随 canonical）
I. Artifact 恢复（req 9：UI 状态纯由 artifacts 推导，不依赖 UI 内存）
J. 中文反馈文案（req 10）
K. GUI：真实 Tk 渲染按钮状态与回调（无显示环境自动 skip）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import tkinter as tk

from ai_agent_framework import cancel as cancel_mod

from bridge import main as bridge_main
from bridge import status_window as sw
from bridge import ui as ui_mod
from bridge.status_window import (
    CANCEL_UI_CANCELLED,
    CANCEL_UI_CANCELLING,
    CANCEL_UI_COMPLETED,
    CANCEL_UI_RUNNING,
    CANCEL_UI_STOP_REQUESTED,
    CANCEL_UI_STOP_UNSAFE,
    CANCEL_UI_UNKNOWN,
    StatusWindow,
    collect_cancel_ui,
    collect_status,
    derive_cancel_ui,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

_OLD = 120.0  # 已超 soft timeout 的请求年龄（秒）


def _cu(**kw) -> sw.CancelUi:
    defaults = dict(
        runtime_status="RUNNING",
        has_cancel_request=False,
        request_age=None,
        soft_timeout=30.0,
        force_eligible=None,
        force_detail=None,
    )
    defaults.update(kw)
    return derive_cancel_ui(**defaults)


# ---------------------------------------------------------------------------
# A. 状态机全矩阵（req 2）
# ---------------------------------------------------------------------------


def test_state_machine_full_matrix():
    # 正在运行（可停止）
    cu = _cu()
    assert cu.state == CANCEL_UI_RUNNING and cu.can_stop and not cu.can_force
    assert cu.label == "正在运行"
    # 请求停止（软取消窗口内）
    cu = _cu(has_cancel_request=True, request_age=5.0)
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert cu.label == "请求停止"
    assert not cu.can_stop and not cu.can_force
    assert sw.MSG_WAITING_EXIT in cu.message
    # 正在取消（超时 + force eligible）→ 提供 Force
    cu = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=True)
    assert cu.state == CANCEL_UI_CANCELLING
    assert cu.label == "正在取消"
    assert not cu.can_stop and cu.can_force
    assert "强制停止" in cu.message
    # 已取消（canonical terminal）
    cu = _cu(runtime_status="CANCELLED", has_cancel_request=True)
    assert cu.state == CANCEL_UI_CANCELLED and cu.label == "已取消"
    assert not cu.can_stop and not cu.can_force
    assert sw.MSG_CANCELLED in cu.message
    # 已完成（canonical terminal；无请求）
    cu = _cu(runtime_status="SUCCESS")
    assert cu.state == CANCEL_UI_COMPLETED and cu.label == "已完成"
    assert not cu.can_stop
    # 已完成 + 曾有请求 → 任务已先完成（req 8）
    cu = _cu(runtime_status="SUCCESS", has_cancel_request=True)
    assert cu.state == CANCEL_UI_COMPLETED
    assert sw.MSG_COMPLETED_FIRST in cu.message
    # 无法安全停止（超时 + force 不可用）→ fail closed 无 Force
    cu = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=False,
             force_detail="OWNERSHIP_UNCERTAIN: x")
    assert cu.state == CANCEL_UI_STOP_UNSAFE
    assert cu.label == "无法安全停止"
    assert not cu.can_stop and not cu.can_force
    assert "无法安全强制停止" in cu.message
    # 不可验证 → 无 Stop
    cu = _cu(runtime_status=None)
    assert cu.state == CANCEL_UI_UNKNOWN
    assert not cu.can_stop and not cu.can_force


def test_all_terminal_statuses_follow_canonical():
    for terminal in ("SUCCESS", "WAITING", "FAILED", "CANCELLED"):
        cu = _cu(runtime_status=terminal, has_cancel_request=True)
        if terminal == "CANCELLED":
            assert cu.state == CANCEL_UI_CANCELLED
        else:
            assert cu.state == CANCEL_UI_COMPLETED
            assert sw.MSG_COMPLETED_FIRST in cu.message  # late cancel absorbed
        assert not cu.can_stop


def test_request_age_none_means_within_soft_window():
    # 有请求但年龄未知 → 保守按「等待安全退出」处理，不提供 Force
    cu = _cu(has_cancel_request=True, request_age=None, force_eligible=True)
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert not cu.can_force


def test_state_machine_never_exposes_raw_technical_state_as_primary_copy():
    for state in (CANCEL_UI_RUNNING, CANCEL_UI_STOP_REQUESTED, CANCEL_UI_CANCELLING,
                  CANCEL_UI_CANCELLED, CANCEL_UI_COMPLETED, CANCEL_UI_STOP_UNSAFE,
                  CANCEL_UI_UNKNOWN):
        cu = derive_cancel_ui(
            runtime_status=("RUNNING" if state in (CANCEL_UI_RUNNING, CANCEL_UI_STOP_REQUESTED,
                                                   CANCEL_UI_CANCELLING, CANCEL_UI_STOP_UNSAFE)
                            else "CANCELLED" if state == CANCEL_UI_CANCELLED
                            else "SUCCESS" if state == CANCEL_UI_COMPLETED else None),
            has_cancel_request=state in (CANCEL_UI_STOP_REQUESTED, CANCEL_UI_CANCELLING,
                                         CANCEL_UI_STOP_UNSAFE),
            request_age=(_OLD if state in (CANCEL_UI_CANCELLING, CANCEL_UI_STOP_UNSAFE) else 1.0),
            soft_timeout=30.0,
            force_eligible=(state == CANCEL_UI_CANCELLING),
            force_detail="OWNERSHIP_UNCERTAIN" if state == CANCEL_UI_STOP_UNSAFE else None,
        )
        assert cu.state == state
        # 主要文案不含裸技术状态码（CANCELLED 终态本身是合法展示，排除）
        if state != CANCEL_UI_CANCELLED:
            for raw in ("OWNERSHIP_", "taskkill", "PID", "registry", "STALE"):
                assert raw.lower() not in cu.message.lower(), f"{state}: {cu.message}"


# ---------------------------------------------------------------------------
# B. Stop 入口守卫（req 1）
# ---------------------------------------------------------------------------


def test_stop_not_offered_for_terminal_task():
    for terminal in ("SUCCESS", "WAITING", "FAILED", "CANCELLED"):
        cu = _cu(runtime_status=terminal)
        assert not cu.can_stop


def test_stop_not_offered_when_unverifiable():
    cu = _cu(runtime_status=None)
    assert not cu.can_stop
    assert collect_cancel_ui(None, "T1", Path("x"), "RUNNING") is None  # 无 launcher
    assert collect_cancel_ui(SimpleNamespace(), "T1", None, "RUNNING") is None  # 无目录


# ---------------------------------------------------------------------------
# C. Soft cancel first（req 3）
# ---------------------------------------------------------------------------


def test_status_window_source_writes_only_cancel_request_not_terminal():
    """静态权威边界（req 7）：status_window 可执行代码无任何文件写原语 /
    taskkill / terminal writer / cancel 写入调用；停止动作只经回调转发
    （真实写入在 main.py → Core-owned cancel 模块）。AST 只扫可执行代码，
    注释/文档字符串中的说明性文字不计入。"""
    import ast

    tree = ast.parse((REPO_ROOT / "bridge" / "status_window.py").read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    for forbidden in ("finalize_terminal", "update_status", "taskkill",
                      "finalize_cancelled", "write_cancel_request",
                      "request_force_cancel", "write_text"):
        assert forbidden not in used, f"status_window.py 可执行代码不得包含 {forbidden!r}"
    # 动作只经回调转发（main.py 接线到 launcher backend）
    assert "_on_stop_cb" in used and "_on_force_cb" in used


def test_main_request_stop_writes_only_cancel_request(tmp_path, monkeypatch):
    """Bridge._request_stop：确认后只写 cancel.request（真实写入），不写任何终态。"""
    out = tmp_path / "T1"
    out.mkdir(parents=True)

    class _Launcher:
        state = "RUNNING"
        current = SimpleNamespace(task_id="T1")

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    shown = []
    monkeypatch.setattr(ui_mod, "ask_stop_task", lambda root, tid: True)
    monkeypatch.setattr(ui_mod, "show_info", lambda t, m: shown.append((t, m)))
    monkeypatch.setattr(ui_mod, "show_error", lambda t, m: shown.append((t, m)))

    bridge_main.Bridge._request_stop(bridge, "T1", str(out))
    # 只写 cancel.request；无任何 canonical 产物
    assert (out / "cancel.request").exists()
    req, warn = cancel_mod.inspect_cancel_request(out)
    assert warn is None and req is not None and req.task_id == "T1"
    assert not (out / "task.json").exists()
    assert not (out / "run.json").exists()
    assert not (out / "REPORT.md").exists()
    assert shown and "停止请求已发送" in shown[0][0]


def test_main_request_stop_rejects_when_not_running(tmp_path, monkeypatch):
    out = tmp_path / "T1"
    out.mkdir(parents=True)

    class _Launcher:
        state = "IDLE"
        current = None

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    errors = []
    monkeypatch.setattr(ui_mod, "ask_stop_task", lambda root, tid: True)
    monkeypatch.setattr(ui_mod, "show_error", lambda t, m: errors.append((t, m)))

    bridge_main.Bridge._request_stop(bridge, "T1", str(out))
    assert not (out / "cancel.request").exists()
    assert errors and "无法停止" in errors[0][0]


def test_main_request_stop_cancel_without_confirm_writes_nothing(tmp_path, monkeypatch):
    out = tmp_path / "T1"
    out.mkdir(parents=True)

    class _Launcher:
        state = "RUNNING"
        current = SimpleNamespace(task_id="T1")

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    monkeypatch.setattr(ui_mod, "ask_stop_task", lambda root, tid: False)  # 用户取消
    bridge_main.Bridge._request_stop(bridge, "T1", str(out))
    assert not (out / "cancel.request").exists()


# ---------------------------------------------------------------------------
# D. Soft timeout 不自动 force kill（req 4/17）
# ---------------------------------------------------------------------------


def test_soft_timeout_only_offers_force_option_no_auto_kill(tmp_path):
    """超时后 UI 状态只表达「可选择强制停止」；derive/collect 路径无任何
    request_force_cancel / taskkill 调用（自动 kill 不存在于 UI 层）。"""
    cu = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=True)
    assert cu.can_force
    # collect_cancel_ui 只调用 force_eligible（只读判定），不调用 request_force_cancel
    calls = []

    class FakeLauncher:
        def force_eligible(self, task_id):
            calls.append(task_id)
            return True, "soft cancel timeout reached"

    out = tmp_path / "T1"
    out.mkdir()
    cancel_mod.write_cancel_request(
        out, "T1", requested_at=(datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds"))
    cu2 = collect_cancel_ui(FakeLauncher(), "T1", out, "RUNNING")
    assert cu2.state == CANCEL_UI_CANCELLING and cu2.can_force
    assert calls == ["T1"]


# ---------------------------------------------------------------------------
# E. Force 二次确认（req 4/5）
# ---------------------------------------------------------------------------


def test_main_request_force_requires_second_confirmation(monkeypatch):
    """第二次确认取消 → 不调用 launcher.request_force_cancel（不执行任何终止）。"""
    calls = []

    class _Launcher:
        def request_force_cancel(self, task_id):
            calls.append(task_id)
            return SimpleNamespace(ok=True, canonical_status="CANCELLED")

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    monkeypatch.setattr(ui_mod, "ask_force_stop", lambda root, tid: False)
    bridge_main.Bridge._request_force_stop(bridge, "T1")
    assert calls == []


def test_main_request_force_after_confirmation_calls_verified_backend(monkeypatch):
    calls = []

    class _Launcher:
        def request_force_cancel(self, task_id):
            calls.append(task_id)
            return SimpleNamespace(ok=True, canonical_status="CANCELLED")

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    infos = []
    monkeypatch.setattr(ui_mod, "ask_force_stop", lambda root, tid: True)
    monkeypatch.setattr(ui_mod, "show_info", lambda t, m: infos.append((t, m)))
    bridge_main.Bridge._request_force_stop(bridge, "T1")
    assert calls == ["T1"]
    assert infos and "已强制停止" in infos[0][0]


def test_main_request_force_refusal_maps_to_chinese(monkeypatch):
    """拒绝原因 → 中文主文案（req 10：不裸露 technical 为主要文案）。"""
    class _Launcher:
        def request_force_cancel(self, task_id):
            return SimpleNamespace(ok=False,
                                   refusal_reason="OWNERSHIP_UNCERTAIN: creation time mismatch")

    bridge = object.__new__(bridge_main.Bridge)
    bridge.launcher = _Launcher()
    bridge.root = SimpleNamespace()
    errors = []
    monkeypatch.setattr(ui_mod, "ask_force_stop", lambda root, tid: True)
    monkeypatch.setattr(ui_mod, "show_error", lambda t, m: errors.append((t, m)))
    bridge_main.Bridge._request_force_stop(bridge, "T1")
    assert errors and errors[0][0] == "无法安全强制停止"
    assert "无法安全强制停止" in errors[0][1]
    assert "任务所有权无法确认" in errors[0][1]


# ---------------------------------------------------------------------------
# F. Force eligibility fail closed（req 6）
# ---------------------------------------------------------------------------


def test_force_ui_only_when_backend_explicitly_eligible():
    cu = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=None)
    assert not cu.can_force  # 未评估 → 不提供
    cu = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=False,
             force_detail="OWNERSHIP_UNCERTAIN")
    assert not cu.can_force  # 明确不可用 → 不提供


def test_collect_cancel_ui_force_eligible_backend_exception_fails_closed(tmp_path, monkeypatch):
    out = tmp_path / "T1"
    out.mkdir()
    cancel_mod.write_cancel_request(out, "T1", requested_at=(datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds"))

    class BoomLauncher:
        def force_eligible(self, task_id):
            raise RuntimeError("backend down")

    cu = collect_cancel_ui(BoomLauncher(), "T1", out, "RUNNING")
    assert cu.state == CANCEL_UI_STOP_UNSAFE and not cu.can_force


def test_collect_cancel_ui_force_requires_verified_ownership(tmp_path):
    """req 6：backend 返回 eligible 但 ownership 未通过 → UI fail closed 不提供 Force。"""
    out = tmp_path / "T1"
    out.mkdir()
    cancel_mod.write_cancel_request(out, "T1", requested_at=(datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds"))

    calls = []

    class Verdict:
        result = "UNCERTAIN"

        def ok(self):
            return False

    class LauncherWithOwnership:
        def force_eligible(self, task_id):
            return True, "soft cancel timeout reached"

        def ownership_status(self, task_id):
            calls.append(task_id)
            return Verdict()

    cu = collect_cancel_ui(LauncherWithOwnership(), "T1", out, "RUNNING")
    assert cu.state == CANCEL_UI_STOP_UNSAFE and not cu.can_force
    assert calls == ["T1"]

    # ownership 通过 → Force 可用
    class OkVerdict:
        result = "VERIFIED"

        def ok(self):
            return True

    class LauncherOk:
        def force_eligible(self, task_id):
            return True, "ok"

        def ownership_status(self, task_id):
            return OkVerdict()

    cu2 = collect_cancel_ui(LauncherOk(), "T1", out, "RUNNING")
    assert cu2.state == CANCEL_UI_CANCELLING and cu2.can_force


# ---------------------------------------------------------------------------
# G. UI Authority Boundary（req 7）—— 见 test_status_window_source_writes_only_cancel_request
#    以及 launcher 层面既有 force_authority 测试（test_phase_e_force_authority.py）
# ---------------------------------------------------------------------------


def test_bridge_main_force_refusal_mapping_covers_known_codes():
    b = bridge_main.Bridge
    for code in ("OWNERSHIP_STALE", "NOT_ELIGIBLE: x", "TERMINATION_FAILED: x",
                 "EVIDENCE_WRITE_FAILED: x", "CONTROL_UPDATE_FAILED: x",
                 "NO_ACTIVE_LAUNCH", "WEIRD_CODE"):
        msg = b._force_refusal_cn(code)
        assert msg.startswith("无法") or msg.startswith("尚不能") or "强制" in msg
        assert len(msg) > 10


# ---------------------------------------------------------------------------
# H. Canonical winner（req 8）
# ---------------------------------------------------------------------------


def test_late_cancel_absorbed_ui_follows_canonical(tmp_path, monkeypatch):
    """normal completion 已 commit，late cancel.request 写入 → UI 显示已完成/任务已先完成，
    canonical terminal 保持原 SUCCESS（late cancel 不覆盖 canonical，req 8）。"""
    out = tmp_path / "T1"
    out.mkdir()
    (out / "task.json").write_text(json.dumps({
        "task_id": "T1", "status": "SUCCESS", "terminal_generation": 1,
        "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
    }), encoding="utf-8")
    # late cancel request（canonical 已终态后写入——request 只是外部意图，不改变 canonical）
    cancel_mod.write_cancel_request(out, "T1")
    cu = collect_cancel_ui(SimpleNamespace(), "T1", out, "SUCCESS")
    assert cu.state == CANCEL_UI_COMPLETED
    assert sw.MSG_COMPLETED_FIRST in cu.message
    data = json.loads((out / "task.json").read_text(encoding="utf-8"))
    assert data["status"] == "SUCCESS"  # canonical 保持原终态
    assert data["terminal_generation"] == 1


def test_cancelled_terminal_wins_over_running_observation(tmp_path):
    """canonical CANCELLED 存在（即使 cancel.request 仍在）→ UI 已取消。"""
    cu = _cu(runtime_status="CANCELLED", has_cancel_request=True, request_age=_OLD)
    assert cu.state == CANCEL_UI_CANCELLED


# ---------------------------------------------------------------------------
# I. Artifact 恢复（req 9）
# ---------------------------------------------------------------------------


def test_ui_state_derived_purely_from_artifacts_not_memory(tmp_path, monkeypatch):
    """窗口/重启后状态恢复：两个独立「UI 会话」（无共享内存）从相同 artifacts
    推导出相同 cancel UI 状态（不依赖窗口实例内存）。"""
    out = tmp_path / "T1"
    out.mkdir()
    (out / "task.json").write_text(json.dumps({
        "task_id": "T1", "status": "RUNNING",
        "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
    }), encoding="utf-8")
    cancel_mod.write_cancel_request(out, "T1", requested_at=(datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds"))

    def derive_in_session():
        # 每个会话重新从 artifacts 收集（模拟全新窗口/provider，零内存）
        return collect_cancel_ui(SimpleNamespace(), "T1", out, "RUNNING")

    a = derive_in_session()
    b = derive_in_session()
    assert a.state == b.state == CANCEL_UI_STOP_REQUESTED
    assert a.message == b.message


# ---------------------------------------------------------------------------
# J. 中文反馈文案（req 10）
# ---------------------------------------------------------------------------


def test_required_chinese_feedback_strings_exist():
    for text in (sw.MSG_STOP_SENT, sw.MSG_WAITING_EXIT, sw.MSG_FORCE_OPTION,
                 sw.MSG_FORCE_CONFIRM, sw.MSG_CANCELLED, sw.MSG_COMPLETED_FIRST,
                 sw.MSG_UNSAFE_FORCE, sw.MSG_STOP_CONFIRM):
        assert isinstance(text, str) and len(text) >= 4
    # 全部主要文案为中文（无英文技术状态码裸露）
    assert "CANCEL_REQUESTED" not in sw.MSG_WAITING_EXIT
    assert "CANCELLING" not in sw.MSG_FORCE_OPTION


# ---------------------------------------------------------------------------
# K. GUI：真实 Tk 渲染（无显示环境自动 skip）
# ---------------------------------------------------------------------------


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk 不可用（无显示环境）: {e}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def _snapshot_with(cancel_ui):
    return sw.StatusSnapshot(
        project="P", workspace="W", bridge_status="正常运行", bridge_detail="", hotkey="Ctrl+Alt+A",
        has_task=True, task_id="T1", task_name="测试任务", stage="Hermes", agent="Hermes",
        elapsed="1分", last_activity="刚刚", overall="执行中", overall_raw="RUNNING",
        stage_strip={s: "PENDING" for s in sw.STAGE_ORDER},
        progress_percent=0, progress_text="", stage_share_text="", stuck=False,
        task_dir=None, log_dir=None, report_path=None, cancel_ui=cancel_ui,
    )


def test_gui_stop_button_enabled_when_can_stop(tk_root):
    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(_cu()))
    try:
        win.refresh()
        assert win.btn_stop.cget("state") == "normal"
        assert win.btn_stop.cget("text") == "停止当前任务"
        assert not win._force_shown  # force 按钮隐藏
    finally:
        win.close()


def test_gui_stop_button_disabled_after_request(tk_root):
    cu = _cu(has_cancel_request=True, request_age=5.0)
    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(cu))
    try:
        win.refresh()
        assert win.btn_stop.cget("state") == "disabled"
        assert win.btn_stop.cget("text") == "正在取消…"
        assert not win._force_shown
    finally:
        win.close()


def test_gui_force_button_shown_only_when_eligible(tk_root):
    eligible = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=True)
    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(eligible))
    try:
        win.refresh()
        assert win._force_shown
        assert win.btn_force.cget("state") == "normal"
        assert win.btn_force.cget("text") == "强制停止"
    finally:
        win.close()
    # 不可用 → 隐藏
    unsafe = _cu(has_cancel_request=True, request_age=_OLD, force_eligible=False)
    win2 = StatusWindow(tk_root, provider=lambda: _snapshot_with(unsafe))
    try:
        win2.refresh()
        assert not win2._force_shown
    finally:
        win2.close()


def test_gui_force_button_hides_when_state_changes(tk_root):
    """eligible → 显示；随后 terminal → 隐藏（同一窗口，状态变化驱动）。"""
    state = {"cu": _cu(has_cancel_request=True, request_age=_OLD, force_eligible=True)}
    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(state["cu"]))
    try:
        win.refresh()
        assert win._force_shown
        state["cu"] = _cu(runtime_status="CANCELLED")
        win.refresh()
        assert not win._force_shown
        assert win.btn_stop.cget("state") == "disabled"
    finally:
        win.close()


def test_gui_stop_click_calls_callback_with_task_context(tk_root):
    calls = []

    def on_stop(task_id, output_dir):
        calls.append((task_id, output_dir))

    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(_cu()),
                       on_stop_request=on_stop)
    try:
        win.refresh()
        win._cancel_task_id = "T1"
        win._task_dir = "D:/x"
        win._on_stop()
        assert calls == [("T1", "D:/x")]
        # 无回调 / 无任务 → 不调用
        win._cancel_task_id = None
        win._on_stop()
        assert len(calls) == 1
    finally:
        win.close()


def test_gui_force_click_calls_callback(tk_root):
    calls = []

    def on_force(task_id):
        calls.append(task_id)

    win = StatusWindow(tk_root, provider=lambda: _snapshot_with(
        _cu(has_cancel_request=True, request_age=_OLD, force_eligible=True)),
        on_force_request=on_force)
    try:
        win.refresh()
        win._cancel_task_id = "T1"
        win._on_force()
        assert calls == ["T1"]
    finally:
        win.close()


def test_gui_no_task_no_stop_entry(tk_root):
    snap = _snapshot_with(None)
    snap.has_task = False
    win = StatusWindow(tk_root, provider=lambda: snap)
    try:
        win.refresh()
        assert win.btn_stop.cget("state") == "disabled"
        assert not win._force_shown
    finally:
        win.close()
