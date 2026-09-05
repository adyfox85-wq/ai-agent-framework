"""AAF Bridge — Phase C Status Window 测试。

覆盖（TASK AAF-v0.4-TASK-003 req 19）：
A. Status mapping（RUNNING / SUCCESS / WAITING / FAILED）
B. Stage mapping（not started / running / success / failed / waiting）
C. Agent mapping
D. Legacy / missing runtime fields
E. No-task empty state
F. Current task resolution
G. elapsed formatter
H. last activity formatter
I. Status window singleton（打开一次 / 再次打开聚焦 / 关闭不退出 Bridge）
J. Tray → status window integration
K. Chinese-first strings
L. UI refresh callback safety

GUI 相关测试需要真实 Tk（Windows 桌面）；无显示环境时自动 skip。
"""
from datetime import datetime, timedelta
from json import dumps
from pathlib import Path
from types import SimpleNamespace

import pytest
import tkinter as tk

from ai_agent_framework.runtime_state import RuntimeState
from ai_agent_framework import runtime_health as rh_mod
from bridge import main as bridge_main
from bridge import status_window as sw
from bridge import tray as tray_mod
from bridge import cost_visibility as cv
from bridge.status_window import (
    StatusWindow,
    StatusWindowController,
    collect_status,
    resolve_current_task,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_real_last_run(monkeypatch):
    """隔离真实 ~/.aaf-bridge/last_run.json：默认无 last 记录（各测试自行注入）。"""
    monkeypatch.setattr(sw, "_load_last_run_file", lambda: None)


# ---------------------------------------------------------------------------
# A. Status mapping
# ---------------------------------------------------------------------------


def test_overall_status_label_mapping():
    assert sw.overall_status_label("RUNNING") == "执行中"
    assert sw.overall_status_label("SUCCESS") == "已完成"
    assert sw.overall_status_label("WAITING") == "等待处理"
    assert sw.overall_status_label("FAILED") == "执行失败"
    assert sw.overall_status_label("CREATED") == "已创建"


def test_overall_status_label_unknown_and_missing():
    assert sw.overall_status_label(None) == "—"
    assert sw.overall_status_label("") == "—"
    assert sw.overall_status_label("BOGUS") == "—"


def test_cancelled_status_label_in_phase_e():
    # Phase E（TASK-005-A）：CANCELLED 进入生命周期状态映射（§11.1 CANCELLED → 已取消）；
    # 阶段状态不增加 CANCELLED（阶段保持事实状态，整体取消由 status 表达）
    assert sw.STATUS_LABELS.get("CANCELLED") == "已取消"
    assert "CANCELLED" not in sw.PHASE_STATE_DISPLAY
    assert sw.overall_status_label("CANCELLED") == "已取消"
    assert sw.LAUNCHER_RESULT_LABELS.get("CANCELLED") == "已取消"


# ---------------------------------------------------------------------------
# B. Stage mapping
# ---------------------------------------------------------------------------


def test_stage_state_label_symbols():
    assert sw.stage_state_label("PENDING") == ("○", "未开始")
    assert sw.stage_state_label("RUNNING") == ("▶", "进行中")
    assert sw.stage_state_label("SUCCESS") == ("✓", "已完成")
    assert sw.stage_state_label("WAITING") == ("⏸", "等待处理")
    assert sw.stage_state_label("FAILED") == ("✗", "失败")
    assert sw.stage_state_label(None) == ("○", "未开始")
    assert sw.stage_state_label("SKIPPED") == ("○", "未开始")
    assert sw.stage_state_label("UNKNOWN_RAW") == ("○", "未知")


def test_stage_order_is_six_fixed_stages():
    assert sw.STAGE_ORDER == ("VALIDATION", "BOUNDARY", "HERMES", "WORKBUDDY", "CODEX", "REPORT")


def test_stage_states_from_phases_running():
    runtime = RuntimeState(
        task_id="T1",
        status="RUNNING",
        stage="WORKBUDDY",
        agent="workbuddy",
        phases={
            "VALIDATION": {"state": "SUCCESS"},
            "BOUNDARY": {"state": "SUCCESS"},
            "HERMES": {"state": "SUCCESS"},
            "WORKBUDDY": {"state": "RUNNING"},
            "CODEX": {"state": "PENDING"},
            "REPORT": {"state": "PENDING"},
        },
    )
    states = sw.stage_states(runtime, None, ["hermes", "workbuddy", "codex"])
    assert states["VALIDATION"] == "SUCCESS"
    assert states["BOUNDARY"] == "SUCCESS"
    assert states["HERMES"] == "SUCCESS"
    assert states["WORKBUDDY"] == "RUNNING"
    assert states["CODEX"] == "PENDING"
    assert states["REPORT"] == "PENDING"


def test_stage_states_failed_stage():
    runtime = RuntimeState(
        task_id="T1",
        status="FAILED",
        stage="HERMES",
        agent="hermes",
        phases={"HERMES": {"state": "FAILED"}},
    )
    states = sw.stage_states(runtime, None, ["hermes"])
    assert states["HERMES"] == "FAILED"
    assert states["VALIDATION"] == "SUCCESS"  # task.json 存在 ⇒ Validation 已通过


def test_stage_states_waiting_stage():
    runtime = RuntimeState(
        task_id="T1",
        status="WAITING",
        stage="WORKBUDDY",
        agent="workbuddy",
        phases={"WORKBUDDY": {"state": "WAITING"}},
    )
    states = sw.stage_states(runtime, None, ["hermes", "workbuddy"])
    assert states["WORKBUDDY"] == "WAITING"


def test_stage_states_legacy_artifacts(tmp_path):
    # legacy：无 phases → 按产物存在性映射（冻结设计 §3 legacy 兼容）
    (tmp_path / "boundary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "route.json").write_text(dumps({"agents": ["hermes"]}), encoding="utf-8")
    (tmp_path / "hermes_prompt.md").write_text("prompt", encoding="utf-8")
    runtime = RuntimeState(task_id="T1", status="RUNNING", stage="HERMES", agent="hermes")
    route = sw.read_route_agents(tmp_path)
    assert route == ["hermes"]
    states = sw.stage_states(runtime, tmp_path, route)
    assert states["BOUNDARY"] == "SUCCESS"
    assert states["HERMES"] == "RUNNING"  # prompt 已写、result 未写
    assert states["WORKBUDDY"] == "PENDING"  # 不在 route → 未开始
    assert states["CODEX"] == "PENDING"
    assert states["REPORT"] == "PENDING"


def test_stage_states_legacy_agent_done(tmp_path):
    (tmp_path / "hermes_result.md").write_text("OK", encoding="utf-8")
    runtime = RuntimeState(task_id="T1", status="RUNNING", stage="HERMES", agent="hermes")
    states = sw.stage_states(runtime, tmp_path, ["hermes"])
    assert states["HERMES"] == "SUCCESS"  # result 已写 ⇒ 完成


def test_stage_states_report_success_when_report_exists(tmp_path):
    (tmp_path / "REPORT.md").write_text("R", encoding="utf-8")
    runtime = RuntimeState(task_id="T1", status="SUCCESS", stage="COMPLETED", agent=None)
    states = sw.stage_states(runtime, tmp_path, ["hermes"])
    assert states["REPORT"] == "SUCCESS"


def test_stage_states_report_running_when_all_agents_done(tmp_path):
    (tmp_path / "hermes_result.md").write_text("OK", encoding="utf-8")
    runtime = RuntimeState(task_id="T1", status="RUNNING", stage="REPORT", agent=None)
    states = sw.stage_states(runtime, tmp_path, ["hermes"])
    assert states["HERMES"] == "SUCCESS"
    assert states["REPORT"] == "RUNNING"


# ---------------------------------------------------------------------------
# C. Agent mapping
# ---------------------------------------------------------------------------


def test_agent_label_mapping():
    assert sw.agent_label("hermes") == "Hermes"
    assert sw.agent_label("workbuddy") == "WorkBuddy"
    assert sw.agent_label("codex") == "Codex"
    assert sw.agent_label("HERMES") == "Hermes"  # 大小写不敏感


def test_agent_label_null_and_unknown():
    assert sw.agent_label(None) == "—"
    assert sw.agent_label("") == "—"
    assert sw.agent_label("OTHER") == "OTHER"  # 未知 agent 保留英文原值


# ---------------------------------------------------------------------------
# D. Legacy / missing runtime fields
# ---------------------------------------------------------------------------


def test_legacy_runtime_state_no_crash(tmp_path):
    # 空 RuntimeState（legacy task.json 无 Phase A 新字段）
    runtime = RuntimeState()
    assert runtime.elapsed_seconds() is None
    assert runtime.stage is None
    assert runtime.agent is None
    states = sw.stage_states(runtime, None, None)
    # task.json 存在 ⇒ Validation 已通过（事实）；其余无记录 → 未开始
    assert states["VALIDATION"] == "SUCCESS"
    assert states["BOUNDARY"] == "PENDING"
    assert states["REPORT"] == "PENDING"


def test_missing_artifacts_no_crash(tmp_path):
    # output_dir 为空目录（task.json / route.json / REPORT.md 全缺）
    runtime = RuntimeState(task_id="T1", status="RUNNING")
    states = sw.stage_states(runtime, tmp_path, None)
    assert states["VALIDATION"] == "SUCCESS"
    assert states["BOUNDARY"] == "RUNNING"  # 任务 RUNNING 且 boundary.json 尚无
    assert states["HERMES"] == "PENDING"
    assert states["REPORT"] == "PENDING"
    assert sw.read_route_agents(tmp_path) is None
    assert sw.format_elapsed(None) == "—"
    assert sw.format_last_activity(None) == "—"


def test_corrupted_task_json_no_crash(tmp_path):
    (tmp_path / "task.json").write_text("{broken json", encoding="utf-8")
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(tmp_path, "AAF-CORRUPT"),
    )
    assert snap.has_task is True
    assert snap.task_id == "AAF-CORRUPT"
    # 不崩溃；task.json 损坏 → 只显示 last_run 事实（FINISHED → 已完成）
    assert snap.overall == "已完成"
    assert snap.overall_raw == "FINISHED"


def _launcher_with_last(output_dir, task_id, result="FINISHED"):
    class _Last:
        def __init__(self):
            self.task_id = task_id
            self.task_path = str(output_dir / "TASK.md")
            self.output_dir = str(output_dir)
            self.report_path = None
            self.exit_code = 0
            self.result = result

    class _Launcher:
        state = "IDLE"
        last = _Last()
        current = None

        def load_last(self):
            return self.last

    return _Launcher()


# ---------------------------------------------------------------------------
# E. No-task empty state
# ---------------------------------------------------------------------------


def test_no_task_empty_state(tmp_path):
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        None,
    )
    assert snap.has_task is False
    assert "当前没有任务" in (snap.empty_hint or "")
    assert snap.task_id == ""
    assert snap.log_dir is None
    assert snap.stage_strip == {s: "PENDING" for s in sw.STAGE_ORDER}


def test_no_task_does_not_read_files(tmp_path, monkeypatch):
    # 无任务时不应尝试读任何 task 产物
    calls = []

    class _NoLastLauncher:
        state = "IDLE"
        last = None
        current = None

        def load_last(self):
            calls.append("load_last")
            return None

    monkeypatch.setattr(sw, "_load_last_run_file", lambda: None)
    snap = collect_status({"hotkey": "ctrl+alt+a"}, ("OK", "正常运行"), _NoLastLauncher())
    assert snap.has_task is False


# ---------------------------------------------------------------------------
# F. Current task resolution
# ---------------------------------------------------------------------------


def test_resolve_prefers_running_launcher_task(tmp_path):
    launcher = SimpleNamespace(
        state="RUNNING",
        last=None,
        current=SimpleNamespace(
            task_id="AAF-RUN",
            task_path=str(tmp_path / "TASK.md"),
            output_dir=str(tmp_path),
        ),
    )
    ref = resolve_current_task(launcher)
    assert ref is not None
    assert ref.task_id == "AAF-RUN"
    assert ref.output_dir == tmp_path


def test_resolve_falls_back_to_last_run(tmp_path):
    launcher = SimpleNamespace(
        state="IDLE",
        last=SimpleNamespace(
            task_id="AAF-LAST",
            task_path=str(tmp_path / "TASK.md"),
            output_dir=str(tmp_path),
            result="FINISHED",
        ),
    )
    ref = resolve_current_task(launcher)
    assert ref.task_id == "AAF-LAST"
    assert ref.output_dir == tmp_path


def test_resolve_uses_load_last_when_memory_empty(tmp_path):
    last = SimpleNamespace(
        task_id="AAF-FILE",
        task_path=str(tmp_path / "TASK.md"),
        output_dir=str(tmp_path),
        result="FINISHED",
    )

    class _Launcher:
        state = "IDLE"
        last = None
        current = None

        def load_last(self):
            return last

    ref = resolve_current_task(_Launcher())
    assert ref.task_id == "AAF-FILE"


def test_resolve_none_when_nothing(monkeypatch):
    monkeypatch.setattr(sw, "_load_last_run_file", lambda: None)
    assert resolve_current_task(None) is None


def test_resolve_legacy_last_without_output_dir(tmp_path):
    # legacy last_run.json 无 output_dir → 从 task_path 推导 <ws>/.aaf/<id>
    ws = tmp_path / "ws"
    task_path = ws / ".aaf" / "tasks" / "active" / "AAF-X.md"
    launcher = SimpleNamespace(
        state="IDLE",
        last=SimpleNamespace(
            task_id="AAF-X",
            task_path=str(task_path),
            output_dir=None,
            result="FINISHED",
        ),
    )
    ref = resolve_current_task(launcher)
    assert ref.output_dir == ws / ".aaf" / "AAF-X"


def test_resolve_reads_last_run_file_directly(tmp_path, monkeypatch):
    last = SimpleNamespace(
        task_id="AAF-DIRECT",
        task_path=str(tmp_path / "TASK.md"),
        output_dir=str(tmp_path),
        result="FINISHED",
    )
    monkeypatch.setattr(sw, "_load_last_run_file", lambda: last)
    ref = resolve_current_task(None)
    assert ref.task_id == "AAF-DIRECT"


# ---------------------------------------------------------------------------
# G. elapsed formatter
# ---------------------------------------------------------------------------


def test_format_elapsed():
    assert sw.format_elapsed(None) == "—"
    assert sw.format_elapsed(0) == "0秒"
    assert sw.format_elapsed(59) == "59秒"
    assert sw.format_elapsed(60) == "1分0秒"
    assert sw.format_elapsed(754) == "12分34秒"
    assert sw.format_elapsed(3600) == "1小时0分"
    assert sw.format_elapsed(90061) == "1天1小时"
    assert sw.format_elapsed(-5) == "0秒"  # 负值钳制


def test_collect_status_elapsed_and_activity(tmp_path):
    started = (datetime.now() - timedelta(minutes=12, seconds=34)).isoformat(timespec="seconds")
    activity = (datetime.now() - timedelta(minutes=2)).isoformat(timespec="seconds")
    out = tmp_path / "AAF-EL-1"
    out.mkdir()
    (out / "task.json").write_text(
        dumps(
            {
                "task_id": "AAF-EL-1",
                "status": "RUNNING",
                "updated_at": activity,
                "task_path": str(tmp_path / "TASK.md"),
                "workspace": str(tmp_path),
                "report_path": None,
                "stage": "HERMES",
                "agent": "hermes",
                "started_at": started,
                "last_activity_at": activity,
                "phases": {},
            }
        ),
        encoding="utf-8",
    )
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-EL-1", result="RUNNING"),
    )
    # 事实时间差：12分34秒 ± 1 秒容差
    assert snap.elapsed == "12分34秒" or snap.elapsed == "12分35秒"
    assert snap.last_activity in ("2分钟前", "1分钟前")


# ---------------------------------------------------------------------------
# H. last activity formatter
# ---------------------------------------------------------------------------


def test_format_last_activity():
    now = datetime(2026, 8, 27, 12, 0, 0)
    assert sw.format_last_activity(None, now=now) == "—"
    assert sw.format_last_activity("not-a-date", now=now) == "—"
    assert (
        sw.format_last_activity((now - timedelta(seconds=10)).isoformat(timespec="seconds"), now=now)
        == "刚刚"
    )
    assert (
        sw.format_last_activity((now - timedelta(minutes=2)).isoformat(timespec="seconds"), now=now)
        == "2分钟前"
    )
    assert (
        sw.format_last_activity((now - timedelta(hours=3)).isoformat(timespec="seconds"), now=now)
        == "3小时前"
    )
    assert (
        sw.format_last_activity((now - timedelta(days=2)).isoformat(timespec="seconds"), now=now)
        == "2天前"
    )


# ---------------------------------------------------------------------------
# 工具：真实 Tk root（无显示环境自动 skip）
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


def _collect_all_buttons(widget):
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button):
            texts.append(child.cget("text"))
        texts.extend(_collect_all_buttons(child))
    return texts


# ---------------------------------------------------------------------------
# I. Status window singleton（打开一次 / 再次打开聚焦 / 关闭不退出 Bridge）
# ---------------------------------------------------------------------------


def test_singleton_open_twice_reuses_window(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w1 = ctl.open()
    assert ctl.window is w1
    w2 = ctl.open()  # 再次打开 → 复用，不新建
    assert w2 is w1
    assert len([c for c in tk_root.winfo_children() if isinstance(c, StatusWindow)]) == 1
    w1.close()
    assert ctl.window is None


def test_singleton_reopen_after_close_creates_new(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w1 = ctl.open()
    w1.close()
    assert ctl.window is None
    w2 = ctl.open()  # 关闭后再打开 → 新建窗口
    assert w2 is not w1
    w2.close()


def test_close_window_does_not_exit_bridge(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    w.close()
    assert ctl.window is None
    assert tk_root.winfo_exists()  # Bridge 主循环仍然存活（关闭 ≠ 退出）


def test_window_close_via_wm_delete_protocol(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    # WM_DELETE_WINDOW 已注册处理器（点击 X → close 路径，只关窗不退出 Bridge）
    assert w.protocol("WM_DELETE_WINDOW")
    w.close()
    assert ctl.window is None
    assert tk_root.winfo_exists()


# ---------------------------------------------------------------------------
# J. Tray → status window integration
# ---------------------------------------------------------------------------


def _make_bridge(root, monkeypatch):
    monkeypatch.setattr(bridge_main.Bridge, "_apply_hotkey", lambda self: None)
    monkeypatch.setattr(bridge_main.Bridge, "_start_tray", lambda self: None)
    monkeypatch.setattr(bridge_main.FrameworkLauncher, "load_last", lambda self: None)
    monkeypatch.setattr(
        bridge_main.cfg_mod,
        "load_config",
        lambda *a, **k: {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
    )
    return bridge_main.Bridge(root)


def test_tray_open_status_opens_status_window(tk_root, monkeypatch):
    bridge = _make_bridge(tk_root, monkeypatch)
    bridge._on_tray_event(tray_mod.EVENT_OPEN_STATUS)
    assert bridge.status_ctl.window is not None
    w = bridge.status_ctl.window

    bridge._on_tray_event(tray_mod.EVENT_OPEN_STATUS)  # 再次 → 复用/聚焦
    assert bridge.status_ctl.window is w

    w.close()
    assert bridge.status_ctl.window is None
    assert tk_root.winfo_exists()  # Bridge 未退出

    bridge._on_tray_event(tray_mod.EVENT_OPEN_STATUS)  # 关闭后再打开 → 新建
    assert bridge.status_ctl.window is not None
    assert bridge.status_ctl.window is not w
    bridge.status_ctl.window.close()


def test_tray_menu_label_is_chinese():
    labels = [label for kind, label, _ in tray_mod.build_tray_menu_spec() if kind == "item"]
    assert "打开状态窗口" in labels


# ---------------------------------------------------------------------------
# K. Chinese-first strings
# ---------------------------------------------------------------------------


def test_window_title_chinese(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    assert "状态窗口" in w.title()
    w.close()


def test_window_buttons_chinese(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    texts = _collect_all_buttons(w)
    assert "查看日志" in texts
    assert "关闭" in texts
    assert "重启 Bridge" in texts
    assert "退出 AAF" in texts
    w.close()


def test_window_labels_chinese(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    assert w._lbl_project.cget("text") == "（未设置）"
    assert w._lbl_bridge.cget("text") == "正常运行"
    assert "Ctrl+Alt+A" in w._lbl_hotkey.cget("text")
    w.close()


def test_empty_state_text_chinese(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    assert w._empty_shown is True
    assert "当前没有任务" in w._empty_lbl.cget("text")
    w.close()


def test_snapshot_chinese_strings(tmp_path):
    out = tmp_path / "AAF-CN-1"
    out.mkdir()
    started = datetime.now().isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps(
            {
                "task_id": "AAF-CN-1",
                "status": "SUCCESS",
                "updated_at": started,
                "task_path": str(tmp_path / "TASK.md"),
                "workspace": str(tmp_path),
                "report_path": str(out / "REPORT.md"),
                "stage": "COMPLETED",
                "agent": None,
                "started_at": started,
                "last_activity_at": started,
                "phases": {
                    "VALIDATION": {"state": "SUCCESS"},
                    "BOUNDARY": {"state": "SUCCESS"},
                    "HERMES": {"state": "SUCCESS"},
                    "WORKBUDDY": {"state": "SUCCESS"},
                    "CODEX": {"state": "SUCCESS"},
                    "REPORT": {"state": "SUCCESS"},
                },
            }
        ),
        encoding="utf-8",
    )
    (out / "REPORT.md").write_text("R", encoding="utf-8")
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-CN-1"),
    )
    assert snap.has_task is True
    assert snap.task_id == "AAF-CN-1"
    assert snap.overall == "已完成"
    assert snap.overall_raw == "SUCCESS"  # 详情保留英文原值
    assert snap.stage == "已完成"
    assert snap.agent == "—"
    assert snap.log_dir == str(out)
    assert all(snap.stage_strip[s] == "SUCCESS" for s in sw.STAGE_ORDER)


def test_view_log_button_opens_directory(tk_root, tmp_path, monkeypatch):
    opened = []

    def fake_open(path):
        opened.append(str(path))
        return True

    monkeypatch.setattr(sw, "open_directory", fake_open)
    out = tmp_path / "AAF-LOG-1"
    out.mkdir()
    ctl = StatusWindowController(
        tk_root,
        provider=lambda: SimpleNamespace(
            has_task=True,
            project="P",
            workspace="W",
            bridge_status="正常运行",
            bridge_detail="",
            hotkey="Ctrl+Alt+A",
            task_id="AAF-LOG",
            task_name="T",
            stage="Hermes",
            agent="Hermes",
            elapsed="1分0秒",
            last_activity="刚刚",
            overall="执行中",
            overall_raw="RUNNING",
            stage_strip={s: "PENDING" for s in sw.STAGE_ORDER},
            log_dir=str(out),
            report_path=None,
            empty_hint=None,
        ),
    )
    w = ctl.open()
    assert w.btn_log.cget("state") != "disabled"
    w._on_open_log()
    assert opened and opened[0] == str(out)
    w.close()


# ---------------------------------------------------------------------------
# L. UI refresh callback safety
# ---------------------------------------------------------------------------


def test_refresh_after_close_is_safe(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    w.refresh()  # 正常刷新
    w.close()
    assert w._after_id is None  # 刷新回调已取消
    w.refresh()  # 关闭后刷新 → 不得 TclError
    assert w._closed is True


def test_refresh_after_external_destroy_is_safe(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    w.destroy()  # 外部销毁（不经过 close）
    w.refresh()  # 不得 TclError
    # 控制器识别窗口已死 → 再次 open 新建
    w2 = ctl.open()
    assert w2 is not w
    w2.close()


def test_refresh_provider_exception_is_safe(tk_root):
    def boom():
        raise RuntimeError("provider 异常")

    ctl = StatusWindowController(tk_root, provider=boom)
    w = ctl.open()
    w.refresh()  # provider 抛异常 → 兜底未知快照，不崩溃
    assert w.winfo_exists()
    assert w._lbl_bridge.cget("text") == "—"
    w.close()


def test_refresh_ticks_after_interval(tk_root):
    ctl = StatusWindowController(
        tk_root, provider=lambda: collect_status({}, ("OK", "正常运行"), None)
    )
    w = ctl.open()
    assert w._after_id is not None  # 已安排下一次刷新
    w.close()


def test_stage_strip_rendered_in_window(tk_root, tmp_path):
    out = tmp_path / "AAF-WIN-1"
    out.mkdir()
    started = datetime.now().isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps(
            {
                "task_id": "AAF-WIN-1",
                "status": "RUNNING",
                "updated_at": started,
                "task_path": str(tmp_path / "TASK.md"),
                "workspace": str(tmp_path),
                "report_path": None,
                "stage": "WORKBUDDY",
                "agent": "workbuddy",
                "started_at": started,
                "last_activity_at": started,
                "phases": {
                    "VALIDATION": {"state": "SUCCESS"},
                    "BOUNDARY": {"state": "SUCCESS"},
                    "HERMES": {"state": "SUCCESS"},
                    "WORKBUDDY": {"state": "RUNNING"},
                    "CODEX": {"state": "PENDING"},
                    "REPORT": {"state": "PENDING"},
                },
            }
        ),
        encoding="utf-8",
    )

    class _CurrentLauncher:
        state = "RUNNING"
        last = None
        current = SimpleNamespace(
            task_id="AAF-WIN-1",
            task_path=str(tmp_path / "TASK.md"),
            output_dir=str(out),
        )

        def load_last(self):
            return None

    ctl = StatusWindowController(
        tk_root,
        provider=lambda: collect_status(
            {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": str(tmp_path)},
            ("OK", "正常运行"),
            _CurrentLauncher(),
        ),
    )
    w = ctl.open()
    assert w._empty_shown is False
    assert w._lbl_task_id.cget("text") == "AAF-WIN-1"
    assert w._lbl_overall.cget("text") == "执行中（RUNNING）"
    assert w._lbl_agent.cget("text") == "WorkBuddy"
    assert "▶" in w._cells["WORKBUDDY"].cget("text")
    assert "进行中" in w._cells["WORKBUDDY"].cget("text")
    assert "✓" in w._cells["HERMES"].cget("text")
    assert "○" in w._cells["CODEX"].cget("text")
    assert "未开始" in w._cells["REPORT"].cget("text")
    w.close()


# ---------------------------------------------------------------------------
# TASK-007 / RW-020：Runtime Health 集成（只读观察；UI 无 terminal authority）
# ---------------------------------------------------------------------------


def test_collect_status_running_includes_health(tmp_path):
    """RUNNING + 无 ownership 记录 + 新鲜活动 → health 有值但无警告（不误报）。"""
    out = tmp_path / "AAF-HL-1"
    out.mkdir()
    activity = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps({
            "task_id": "AAF-HL-1", "status": "RUNNING", "stage": "HERMES", "agent": "hermes",
            "updated_at": activity, "task_path": str(tmp_path / "TASK.md"),
            "workspace": str(tmp_path), "report_path": None,
            "started_at": activity, "last_activity_at": activity, "phases": {},
        }),
        encoding="utf-8",
    )
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-HL-1", result="RUNNING"),
    )
    assert snap.health in (rh_mod.HEALTH_UNKNOWN,)
    assert snap.health_warning == ""
    assert snap.health_diagnostics  # 有诊断行（查看诊断可用）


def test_collect_status_dead_runner_warning_banner(tmp_path):
    """RUNNING + runner 已死 + stale + 期望产物缺失 → 中文「任务可能已异常中断」警告。"""
    out = tmp_path / "AAF-HL-2"
    out.mkdir()
    stale = (datetime.now() - timedelta(minutes=25)).isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps({
            "task_id": "AAF-HL-2", "status": "RUNNING", "stage": "WORKBUDDY", "agent": "workbuddy",
            "updated_at": stale, "task_path": str(tmp_path / "TASK.md"),
            "workspace": str(tmp_path), "report_path": None,
            "started_at": stale, "last_activity_at": stale,
            "phases": {"WORKBUDDY": {"state": "RUNNING"}},
        }),
        encoding="utf-8",
    )
    (out / "control.json").write_text(
        dumps({
            "schema_version": 1, "task_id": "AAF-HL-2", "workspace": str(tmp_path),
            "launch_id": "hl2", "launcher_pid": 1, "launcher_instance_id": "i",
            "started_at": stale, "expected_runner_entry": "run.py",
            "expected_command_line": ["py", "run.py", "T"],
            "runner_pid": 987654321, "runner_creation_time": "2026-08-28T10:00:00.000",
            "cancel_requested": False, "force_terminate_requested": False, "superseded_by": None,
        }),
        encoding="utf-8",
    )
    (out / "workbuddy_prompt.md").write_text("p", encoding="utf-8")  # agent 已调用未产出
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-HL-2", result="RUNNING"),
    )
    assert "任务可能已异常中断" in snap.health_warning
    assert snap.health == "SUSPICIOUS_DEAD"
    assert snap.health_diagnostics


def test_collect_status_terminal_no_health_warning(tmp_path):
    """SUCCESS 终态 → health NOT_APPLICABLE，无 liveness 警告（canonical wins）。"""
    out = tmp_path / "AAF-HL-3"
    out.mkdir()
    (out / "task.json").write_text(
        dumps({
            "task_id": "AAF-HL-3", "status": "SUCCESS", "stage": "COMPLETED", "agent": None,
            "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
            "report_path": str(out / "REPORT.md"),
            "started_at": (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds"),
            "last_activity_at": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
            "phases": {},
        }),
        encoding="utf-8",
    )
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-HL-3", result="FINISHED"),
    )
    assert snap.health == "NOT_APPLICABLE"
    assert snap.health_warning == ""


# ---------------------------------------------------------------------------
# M. v0.5 UX Cost Visibility（display-only；IMPLEMENT-001）
# ---------------------------------------------------------------------------


def _cv_completed_dir(tmp_path, task_id="AAF-CV-1"):
    """完成态任务目录：canonical task.json（phases SUCCESS）+ route + 经济 artifact。"""
    out = tmp_path / task_id
    out.mkdir()
    started = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps({
            "task_id": task_id, "status": "SUCCESS", "stage": "COMPLETED", "agent": None,
            "updated_at": started, "task_path": str(tmp_path / "TASK.md"),
            "workspace": str(tmp_path), "report_path": str(out / "REPORT.md"),
            "started_at": started, "last_activity_at": started,
            "phases": {
                "VALIDATION": {"state": "SUCCESS"},
                "BOUNDARY": {"state": "SUCCESS"},
                "HERMES": {"state": "SUCCESS"},
                "WORKBUDDY": {"state": "SUCCESS"},
                "CODEX": {"state": "SUCCESS"},
                "REPORT": {"state": "SUCCESS"},
            },
        }),
        encoding="utf-8",
    )
    (out / "route.json").write_text(
        dumps({"agents": ["hermes", "workbuddy", "codex"], "reason": "explicit route"}),
        encoding="utf-8",
    )
    (out / cv.ARTIFACT_COST_GUARD).write_text(
        dumps({
            "decision": "ALLOWED_AUTHORIZED_PAID", "cost_class": "PAID_OR_UNKNOWN",
            "model": "deepseek-v4-flash", "provider": "deepseek",
            "authorization_present": True, "authorization_matched": True,
            "authorization_consumed": True,
        }),
        encoding="utf-8",
    )
    (out / cv.ARTIFACT_MODEL_OBSERVATION).write_text(
        dumps({"observations": {
            "hermes": {"agent": "hermes", "model": "deepseek-v4-flash",
                       "provider": "deepseek", "cost_class": "UNKNOWN"},
        }}),
        encoding="utf-8",
    )
    (out / "REPORT.md").write_text("# REPORT\n", encoding="utf-8")
    return out


def test_snapshot_cost_rows_completed_reopen(tmp_path):
    """Requirement 18：终端/窗口 reopen 完成态任务 -> 从持久化 artifact
    重建 Cost / Model 显示（collect_status 只读 output_dir artifacts）。"""
    out = _cv_completed_dir(tmp_path)
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-CV-1"),
    )
    assert snap.has_task is True
    rows = snap.cost_rows
    assert len(rows) == 3  # hermes + workbuddy + codex（route agents，已完成阶段）
    hermes = next(r for r in rows if r.agent == "hermes")
    assert hermes.cost_class == cv.COST_PAID
    assert hermes.model == "deepseek-v4-flash"
    assert hermes.provider == "deepseek"
    assert hermes.fallback == cv.FALLBACK_NOT_USED
    wb = next(r for r in rows if r.agent == "workbuddy")
    assert wb.cost_class == cv.COST_UNKNOWN  # 无 A4/观测证据 -> UNKNOWN（不猜）
    codex = next(r for r in rows if r.agent == "codex")
    assert codex.cost_class == cv.COST_UNKNOWN


def test_snapshot_cost_rows_missing_artifacts_unknown_no_crash(tmp_path):
    """Requirement 14/I：经济 artifact 缺失/损坏 -> UNKNOWN 行，快照不崩溃。"""
    out = tmp_path / "AAF-CV-2"
    out.mkdir()
    started = datetime.now().isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps({
            "task_id": "AAF-CV-2", "status": "SUCCESS", "stage": "COMPLETED", "agent": None,
            "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
            "report_path": str(out / "REPORT.md"),
            "started_at": started, "last_activity_at": started,
            "phases": {s: {"state": "SUCCESS"} for s in ("VALIDATION", "BOUNDARY", "HERMES",
                                                          "WORKBUDDY", "CODEX", "REPORT")},
        }),
        encoding="utf-8",
    )
    (out / "route.json").write_text(dumps({"agents": ["hermes"]}), encoding="utf-8")
    (out / cv.ARTIFACT_COST_GUARD).write_text("{broken", encoding="utf-8")  # 损坏
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-CV-2"),
    )
    assert snap.has_task is True
    assert snap.cost_rows and all(r.cost_class == cv.COST_UNKNOWN for r in snap.cost_rows)


def test_snapshot_cost_rows_empty_when_no_task():
    snap = collect_status({}, ("OK", "正常运行"), None)
    assert snap.cost_rows == []


def test_window_cost_rows_rendered(tk_root, tmp_path):
    """真实 Tk：完成态任务 reopen -> Cost / Model 区显示（Hermes PAID 行）。"""
    out = _cv_completed_dir(tmp_path)
    ctl = StatusWindowController(
        tk_root,
        provider=lambda: collect_status(
            {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
            ("OK", "正常运行"),
            _launcher_with_last(out, "AAF-CV-1"),
        ),
    )
    w = ctl.open()
    try:
        # Cost / Model 区标题 + Hermes 行内容（display-only 文本）
        assert w._cost_header.cget("text") == "Cost / Model"
        assert w._cost_agent_lbls[0].cget("text") == "Hermes"
        assert w._cost_cost_lbls[0].cget("text") == cv.COST_PAID
        assert "deepseek-v4-flash" in w._cost_model_lbls[0].cget("text")
        assert w._cost_detail_lbls[0].cget("text") == "explicitly authorized paid"
    finally:
        w.close()


def test_window_cost_rows_hide_pending_future_stages(tk_root, tmp_path):
    """Requirement 17：未开始的 future stage（PENDING + 零 evidence）不显示；
    已开始 stage 显示诚实 UNKNOWN（evidence 未落盘前不猜）。"""
    out = tmp_path / "AAF-CV-3"
    out.mkdir()
    started = datetime.now().isoformat(timespec="seconds")
    (out / "task.json").write_text(
        dumps({
            "task_id": "AAF-CV-3", "status": "RUNNING", "stage": "WORKBUDDY", "agent": "workbuddy",
            "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
            "report_path": None, "started_at": started, "last_activity_at": started,
            "phases": {
                "VALIDATION": {"state": "SUCCESS"}, "BOUNDARY": {"state": "SUCCESS"},
                "HERMES": {"state": "SUCCESS"}, "WORKBUDDY": {"state": "RUNNING"},
            },
        }),
        encoding="utf-8",
    )
    (out / "route.json").write_text(
        dumps({"agents": ["hermes", "workbuddy", "codex"]}), encoding="utf-8",
    )
    # 零经济 artifact（guard 未写盘窗口期）：hermes/workbuddy 行 UNKNOWN 诚实显示
    ctl = StatusWindowController(
        tk_root,
        provider=lambda: collect_status(
            {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
            ("OK", "正常运行"),
            _launcher_with_last(out, "AAF-CV-3", result="RUNNING"),
        ),
    )
    w = ctl.open()
    try:
        assert w._cost_agent_lbls[0].cget("text") == "Hermes"  # 已开始阶段显示
        assert w._cost_cost_lbls[0].cget("text") == cv.COST_UNKNOWN
        assert w._cost_agent_lbls[1].cget("text") == "WorkBuddy"
        assert w._cost_agent_lbls[2].cget("text") == ""  # Codex PENDING：行隐藏
        assert w._cost_cost_lbls[2].cget("text") == ""
    finally:
        w.close()
