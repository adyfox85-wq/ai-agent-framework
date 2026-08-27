"""AAF Bridge — Phase D Progress Visualization 测试（TASK req 22 A–T 全覆盖）。

A. Progress 0%
B. Validation running
C. Boundary complete
D. Hermes running
E. WorkBuddy running
F. Codex running
G. Report running
H. SUCCESS → 100%
I. FAILED → <100%
J. WAITING freeze
K. legacy missing phases
L. no-task state
M. monotonic progress
N. stuck threshold below
O. stuck threshold exceeded
P. stuck not shown for SUCCESS
Q. stuck not shown for FAILED
R. last_activity missing
S. stage_started_at missing
T. Chinese strings

设计依据：冻结设计 §4（权重 / 平滑 / 收敛）、§5.2（stuck 阈值）、
§12.1（文案）、§15 Phase D。GUI 测试需要真实 Tk（Windows 桌面）；
无显示环境时自动 skip。
"""
from datetime import datetime, timedelta
from json import dumps
from pathlib import Path
from types import SimpleNamespace

import pytest
import tkinter as tk

from ai_agent_framework.runtime_state import RuntimeState
from bridge import progress as prog
from bridge import status_window as sw
from bridge import stuck as stuck_mod
from bridge.status_window import (
    StatusSnapshot,
    StatusWindow,
    StatusWindowController,
    collect_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

V, B, H, WB, C, R = "VALIDATION", "BOUNDARY", "HERMES", "WORKBUDDY", "CODEX", "REPORT"


@pytest.fixture(autouse=True)
def _no_real_last_run(monkeypatch):
    """隔离真实 ~/.aaf-bridge/last_run.json：默认无 last 记录（各测试自行注入）。"""
    monkeypatch.setattr(sw, "_load_last_run_file", lambda: None)


def _strip(**states) -> dict:
    out = {s: "PENDING" for s in sw.STAGE_ORDER}
    out.update(states)
    return out


def _now_iso(ago_seconds: float = 0.0) -> str:
    return (datetime.now() - timedelta(seconds=ago_seconds)).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# A. Progress 0%
# ---------------------------------------------------------------------------


def test_progress_0_percent_all_pending():
    est = prog.estimate_progress(_strip(), "RUNNING", {})
    assert est.percent == 0
    assert all(c == 0.0 for c in est.credits.values())


def test_progress_0_percent_created_status():
    est = prog.estimate_progress(_strip(), "CREATED", {})
    assert est.percent == 0


# ---------------------------------------------------------------------------
# B. Validation running（进行中阶段内部 0%–50% 线性，60 分钟为满分，§4.1.4）
# ---------------------------------------------------------------------------


def test_progress_validation_running_just_started():
    est = prog.estimate_progress(_strip(VALIDATION="RUNNING"), "RUNNING", {V: 0})
    assert est.percent == 0  # 刚开始 → 0（0%–50% 线性起点）


def test_progress_validation_running_midway():
    # 30 分钟 → fraction=0.25 → credit=5*0.25=1.25 → round=1
    est = prog.estimate_progress(_strip(VALIDATION="RUNNING"), "RUNNING", {V: 1800})
    assert est.percent == 1


def test_running_fraction_linear_and_capped():
    assert prog.running_fraction(None) == 0.0
    assert prog.running_fraction(-5) == 0.0
    assert prog.running_fraction(0) == 0.0
    assert prog.running_fraction(1800) == pytest.approx(0.25)
    assert prog.running_fraction(3600) == pytest.approx(0.5)
    assert prog.running_fraction(7200) == pytest.approx(0.5)  # 超过上限停在 50%


# ---------------------------------------------------------------------------
# C. Boundary complete
# ---------------------------------------------------------------------------


def test_progress_boundary_complete():
    est = prog.estimate_progress(
        _strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS"), "RUNNING", {}
    )
    assert est.percent == 10


# ---------------------------------------------------------------------------
# D. Hermes running
# ---------------------------------------------------------------------------


def test_progress_hermes_running_start():
    est = prog.estimate_progress(
        _strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="RUNNING"),
        "RUNNING",
        {H: 0},
    )
    assert est.percent == 10  # 已完成 5+5，Hermes 刚开始部分 ≈ 0


def test_progress_hermes_running_partial():
    est = prog.estimate_progress(
        _strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="RUNNING"),
        "RUNNING",
        {H: 1800},
    )
    assert est.percent == 21  # 10 + 45*0.25 = 21.25 → 21


# ---------------------------------------------------------------------------
# E. WorkBuddy running
# ---------------------------------------------------------------------------


def test_progress_workbuddy_running():
    est = prog.estimate_progress(
        _strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS", WORKBUDDY="RUNNING"),
        "RUNNING",
        {WB: 0},
    )
    assert est.percent == 55  # 5+5+45，WorkBuddy 刚开始


# ---------------------------------------------------------------------------
# F. Codex running
# ---------------------------------------------------------------------------


def test_progress_codex_running():
    est = prog.estimate_progress(
        _strip(
            VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS",
            WORKBUDDY="SUCCESS", CODEX="RUNNING",
        ),
        "RUNNING",
        {C: 0},
    )
    assert est.percent == 75  # 5+5+45+20


# ---------------------------------------------------------------------------
# G. Report running
# ---------------------------------------------------------------------------


def test_progress_report_running():
    est = prog.estimate_progress(
        _strip(
            VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS",
            WORKBUDDY="SUCCESS", CODEX="SUCCESS", REPORT="RUNNING",
        ),
        "RUNNING",
        {R: 1800},
    )
    assert est.percent == 96  # 95 + 5*0.25 = 96.25 → 96


# ---------------------------------------------------------------------------
# H. SUCCESS → 100%
# ---------------------------------------------------------------------------


def test_progress_success_converges_to_100():
    est = prog.estimate_progress(_strip(), "SUCCESS", {})
    assert est.percent == 100
    # 全阶段已完成 → credits 也收敛到 100
    full = prog.estimate_progress(
        _strip(**{s: "SUCCESS" for s in sw.STAGE_ORDER}), "SUCCESS", {}
    )
    assert full.percent == 100
    assert round(sum(full.credits.values())) == 100


def test_progress_text_success_done():
    assert prog.progress_text(100, status="SUCCESS") == "整体进度：100%（已完成）"


# ---------------------------------------------------------------------------
# I. FAILED → <100%（冻结在失败阶段之前，设计 §4.1.5）
# ---------------------------------------------------------------------------


def test_progress_failed_less_than_100():
    est = prog.estimate_progress(
        _strip(
            VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="FAILED",
            WORKBUDDY="PENDING", CODEX="PENDING", REPORT="PENDING",
        ),
        "FAILED",
        {},
    )
    assert est.percent == 10  # 只累计已完成：5+5；失败阶段不占权重
    assert est.percent < 100


def test_progress_failed_freezes_before_failed_stage():
    # 失败前 Hermes 进行中部分估算 21% → 失败后收敛到事实 10%（估算→事实收敛，
    # 设计允许回退的明确场景：FAILED 停在失败阶段之前；不显示 100%）
    before = prog.estimate_progress(
        _strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="RUNNING"),
        "RUNNING",
        {H: 1800},
    )
    after = prog.estimate_progress(
        _strip(
            VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="FAILED",
            WORKBUDDY="PENDING", CODEX="PENDING", REPORT="PENDING",
        ),
        "FAILED",
        {},
    )
    assert before.percent == 21
    assert after.percent == 10
    assert after.percent < 100


# ---------------------------------------------------------------------------
# J. WAITING freeze（停在已完成阶段权重和；不自动推进，§4.1.5）
# ---------------------------------------------------------------------------


def test_progress_waiting_freeze_no_growth():
    strip = _strip(
        VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS",
        WORKBUDDY="WAITING", CODEX="PENDING", REPORT="PENDING",
    )
    est1 = prog.estimate_progress(strip, "WAITING", {WB: 0})
    est2 = prog.estimate_progress(strip, "WAITING", {WB: 3600})
    assert est1.percent == 55  # 已完成 5+5+45；等待阶段不占权重
    assert est2.percent == 55  # 时间流逝 → 不变（WAITING 不自动推进）


def test_progress_waiting_running_partial_not_counted():
    # WAITING 状态下，即使阶段条显示 RUNNING 部分估算也不计入（冻结在事实进度）
    strip = _strip(
        VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS",
        WORKBUDDY="RUNNING", CODEX="PENDING", REPORT="PENDING",
    )
    est = prog.estimate_progress(strip, "WAITING", {WB: 1800})
    assert est.percent == 55  # 不把 WorkBuddy 的部分估算加进去


def test_progress_waiting_all_completed_is_fact():
    # 全阶段已完成但最终聚合 WAITING（RW-022 语义）：停在已完成权重和 = 100（事实）
    strip = _strip(**{s: "SUCCESS" for s in sw.STAGE_ORDER})
    est = prog.estimate_progress(strip, "WAITING", {})
    assert est.percent == 100


# ---------------------------------------------------------------------------
# K. legacy missing phases（不崩溃，确定性）
# ---------------------------------------------------------------------------


def test_progress_legacy_missing_phases():
    runtime = RuntimeState(task_id="T1", status="RUNNING")  # 无 phases / 无时间戳
    strip = sw.stage_states(runtime, None, None)
    elapsed = prog.stage_elapsed_map(runtime)
    est = prog.estimate_progress(strip, runtime.status, elapsed)
    # VALIDATION SUCCESS（task.json 存在）+ BOUNDARY RUNNING（无边界文件，部分=0）→ 5
    assert est.percent == 5
    assert 0 <= est.percent <= 100


def test_progress_stage_elapsed_map_missing_timestamps():
    runtime = RuntimeState(task_id="T1", status="RUNNING")
    elapsed = prog.stage_elapsed_map(runtime)
    assert set(elapsed) == set(sw.STAGE_ORDER)
    assert all(v is None for v in elapsed.values())  # 无时间戳 → None（credit 保守 0）


def test_progress_legacy_empty_runtime_no_crash():
    # 空 RuntimeState（无 status / phases）：task.json 存在 ⇒ VALIDATION 已完成（事实）→ 5
    est = prog.estimate_progress(sw.stage_states(RuntimeState(), None, None), None, {})
    assert est.percent == 5
    # runtime 为 None（task.json 缺失）→ 0
    est2 = prog.estimate_progress(sw.stage_states(None, None, None), None, {})
    assert est2.percent == 0


# ---------------------------------------------------------------------------
# L. no-task state
# ---------------------------------------------------------------------------


def test_no_task_progress_zero(tmp_path):
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        None,
    )
    assert snap.has_task is False
    assert snap.progress_percent == 0
    assert snap.progress_text == prog.NO_INFO_TEXT
    assert "暂无进度信息" in snap.progress_text
    assert snap.stuck is False


def test_task_without_task_json_no_progress_info(tmp_path):
    # 任务存在但 task.json 缺失（如 Validation 失败 / 损坏）：0 + 暂无进度信息
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(tmp_path, "AAF-NOJSON", result="FAILED"),
    )
    assert snap.has_task is True
    assert snap.progress_percent == 0
    assert snap.progress_text == prog.NO_INFO_TEXT


# ---------------------------------------------------------------------------
# M. monotonic progress（正常推进序列不倒退）
# ---------------------------------------------------------------------------


def test_progress_monotonic_across_lifecycle():
    steps = [
        (_strip(), "RUNNING", {}, 0),  # 全部未开始
        (_strip(VALIDATION="SUCCESS", BOUNDARY="RUNNING"), "RUNNING", {B: 0}, 5),
        (_strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="RUNNING"), "RUNNING", {H: 600}, 14),
        (_strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="RUNNING"), "RUNNING", {H: 1800}, 21),
        (_strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS", WORKBUDDY="RUNNING"), "RUNNING", {WB: 0}, 55),
        (_strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS", WORKBUDDY="SUCCESS", CODEX="RUNNING"), "RUNNING", {C: 3600}, 85),
        (_strip(VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS", WORKBUDDY="SUCCESS", CODEX="SUCCESS", REPORT="RUNNING"), "RUNNING", {R: 1800}, 96),
        (_strip(**{s: "SUCCESS" for s in sw.STAGE_ORDER}), "SUCCESS", {}, 100),
    ]
    prev = -1
    for strip, status, elapsed, expected in steps:
        est = prog.estimate_progress(strip, status, elapsed)
        assert est.percent == expected, (status, elapsed)
        assert est.percent >= prev, f"progress regressed: {prev} → {est.percent}"
        prev = est.percent
    assert prev == 100


# ---------------------------------------------------------------------------
# N/O. stuck threshold（设计 §5.2：last_activity ≥ 10 分钟 → 可疑停滞）
# ---------------------------------------------------------------------------


def test_stuck_threshold_below():
    runtime = RuntimeState(
        task_id="T1", status="RUNNING", stage="HERMES", agent="hermes",
        last_activity_at=_now_iso(5 * 60),
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False
    assert warning == ""
    assert detail == ""


def test_stuck_threshold_exceeded():
    runtime = RuntimeState(
        task_id="T1", status="RUNNING", stage="HERMES", agent="hermes",
        last_activity_at=_now_iso(11 * 60),
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is True
    assert "任务可能已停滞" in warning
    assert "11 分钟" in detail


def test_stuck_threshold_exactly_at_boundary():
    runtime = RuntimeState(
        task_id="T1", status="RUNNING", last_activity_at=_now_iso(10 * 60),
    )
    stuck, _, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is True
    assert "10 分钟" in detail


def test_stuck_constant_is_documented_threshold():
    # 阈值集中常量化（TASK req 9）：10 分钟 = 设计 §5.2
    assert stuck_mod.STUCK_LAST_ACTIVITY_THRESHOLD_SECONDS == 10 * 60


# ---------------------------------------------------------------------------
# P/Q. stuck 不显示于 SUCCESS / FAILED
# ---------------------------------------------------------------------------


def test_stuck_not_shown_for_success():
    runtime = RuntimeState(
        task_id="T1", status="SUCCESS", stage="COMPLETED",
        last_activity_at=_now_iso(30 * 60),  # 即使活动很旧
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False
    assert warning == ""


def test_stuck_not_shown_for_failed():
    runtime = RuntimeState(
        task_id="T1", status="FAILED", stage="HERMES",
        last_activity_at=_now_iso(30 * 60),
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False


def test_stuck_not_shown_for_waiting():
    runtime = RuntimeState(
        task_id="T1", status="WAITING", stage="COMPLETED",
        last_activity_at=_now_iso(30 * 60),
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False


# ---------------------------------------------------------------------------
# R. last_activity missing（无法观察 → 不判定）
# ---------------------------------------------------------------------------


def test_stuck_last_activity_missing():
    runtime = RuntimeState(task_id="T1", status="RUNNING", stage="HERMES", agent="hermes")
    assert runtime.last_activity_at is None
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False
    assert warning == ""


def test_stuck_last_activity_invalid_iso():
    runtime = RuntimeState(
        task_id="T1", status="RUNNING", last_activity_at="not-a-date",
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False


# ---------------------------------------------------------------------------
# S. stage_started_at missing（不崩溃；stuck 判定不依赖它）
# ---------------------------------------------------------------------------


def test_stuck_stage_started_at_missing():
    # last_activity 存在且新鲜，stage_started_at 缺失 → 不判定 stuck、不崩溃
    runtime = RuntimeState(
        task_id="T1", status="RUNNING", stage="HERMES",
        stage_started_at=None, last_activity_at=_now_iso(30),
    )
    stuck, warning, detail = stuck_mod.suspected_stuck(runtime)
    assert stuck is False


def test_stuck_runtime_none():
    stuck, warning, detail = stuck_mod.suspected_stuck(None)
    assert stuck is False
    assert warning == ""


# ---------------------------------------------------------------------------
# T. Chinese strings（设计 §11.1 / §12.1）
# ---------------------------------------------------------------------------


def test_progress_chinese_strings():
    text = prog.progress_text(58, status="RUNNING")
    assert "整体进度" in text
    assert "估算" in text
    assert "58" in text
    assert prog.NO_INFO_TEXT == "整体进度：暂无进度信息"
    assert "暂无进度信息" in prog.NO_INFO_TEXT
    assert "已完成" in prog.DONE_TEXT
    assert stuck_mod.STUCK_WARNING_TEXT == "⚠ 任务可能已停滞"
    assert "任务可能已停滞" in stuck_mod.STUCK_WARNING_TEXT
    assert stuck_mod.STUCK_HINT_LABEL == "疑似卡住"


def test_stage_share_text_chinese():
    assert prog.stage_share_text(_strip(HERMES="RUNNING")) == "当前阶段占比：45%"
    assert prog.stage_share_text(_strip(WORKBUDDY="RUNNING")) == "当前阶段占比：20%"
    assert prog.stage_share_text(_strip()) == ""  # 无进行中阶段 → 空


# ---------------------------------------------------------------------------
# 权重表集中定义（TASK req 4）
# ---------------------------------------------------------------------------


def test_phase_weights_centralized_and_sum_100():
    assert prog.PHASE_WEIGHTS == {
        "VALIDATION": 5,
        "BOUNDARY": 5,
        "HERMES": 45,
        "WORKBUDDY": 20,
        "CODEX": 20,
        "REPORT": 5,
    }
    assert sum(prog.PHASE_WEIGHTS.values()) == 100


def test_no_cancelled_scope_leak():
    # Phase D 不引入 CANCELLED（Phase E 范围）
    assert "CANCELLED" not in prog.DONE_TEXT
    assert "CANCELLED" not in prog.NO_INFO_TEXT
    assert "CANCELLED" not in stuck_mod.STUCK_WARNING_TEXT


# ---------------------------------------------------------------------------
# collect_status 集成（进度 / stuck 进入快照；只读）
# ---------------------------------------------------------------------------


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


def _write_task(tmp_path, task_id, status, stage, agent, phases, last_activity_ago=30):
    out = tmp_path / task_id
    out.mkdir()
    started = _now_iso(600)
    (out / "task.json").write_text(
        dumps(
            {
                "task_id": task_id,
                "status": status,
                "updated_at": _now_iso(last_activity_ago),
                "task_path": str(tmp_path / "TASK.md"),
                "workspace": str(tmp_path),
                "report_path": str(out / "REPORT.md") if status == "SUCCESS" else None,
                "stage": stage,
                "agent": agent,
                "started_at": started,
                "last_activity_at": _now_iso(last_activity_ago),
                "phases": phases,
            }
        ),
        encoding="utf-8",
    )
    return out


def test_collect_status_progress_running(tmp_path):
    out = _write_task(
        tmp_path, "AAF-P-1", "RUNNING", "WORKBUDDY", "workbuddy",
        {
            V: {"state": "SUCCESS"},
            B: {"state": "SUCCESS"},
            H: {"state": "SUCCESS"},
            WB: {"state": "RUNNING", "started_at": _now_iso(0)},
            C: {"state": "PENDING"},
            R: {"state": "PENDING"},
        },
    )
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-P-1", result="RUNNING"),
    )
    assert snap.progress_percent == 55
    assert "整体进度" in snap.progress_text
    assert "估算" in snap.progress_text
    assert snap.stage_share_text == "当前阶段占比：20%"
    assert snap.stuck is False
    assert snap.task_dir == str(out)


def test_collect_status_progress_success(tmp_path):
    out = _write_task(
        tmp_path, "AAF-P-2", "SUCCESS", "COMPLETED", None,
        {s: {"state": "SUCCESS"} for s in sw.STAGE_ORDER},
    )
    (out / "REPORT.md").write_text("R", encoding="utf-8")
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-P-2"),
    )
    assert snap.progress_percent == 100
    assert snap.progress_text == "整体进度：100%（已完成）"
    assert snap.stuck is False


def test_collect_status_stuck_warning(tmp_path):
    out = _write_task(
        tmp_path, "AAF-P-3", "RUNNING", "HERMES", "hermes",
        {H: {"state": "RUNNING", "started_at": _now_iso(15 * 60)}},
        last_activity_ago=15 * 60,
    )
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-P-3", result="RUNNING"),
    )
    assert snap.stuck is True
    assert "任务可能已停滞" in snap.stuck_warning
    assert "15 分钟" in snap.stuck_detail


def test_collect_status_stuck_not_for_success(tmp_path):
    out = _write_task(
        tmp_path, "AAF-P-4", "SUCCESS", "COMPLETED", None,
        {s: {"state": "SUCCESS"} for s in sw.STAGE_ORDER},
        last_activity_ago=30 * 60,
    )
    (out / "REPORT.md").write_text("R", encoding="utf-8")
    snap = collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"},
        ("OK", "正常运行"),
        _launcher_with_last(out, "AAF-P-4"),
    )
    assert snap.stuck is False
    assert snap.progress_percent == 100


# ---------------------------------------------------------------------------
# GUI：进度条 / stuck 横幅 / 阶段高亮 / 查看任务目录（真实 Tk，自动 skip）
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


def _running_snapshot(tmp_path, *, stuck=False, percent=55, share="当前阶段占比：20%"):
    return StatusSnapshot(
        project="P",
        workspace="W",
        bridge_status="正常运行",
        bridge_detail="",
        hotkey="Ctrl+Alt+A",
        has_task=True,
        task_id="AAF-GUI",
        task_name="GUI 测试",
        stage="WorkBuddy",
        agent="WorkBuddy",
        elapsed="1分0秒",
        last_activity="刚刚" if not stuck else "15分钟前",
        overall="执行中",
        overall_raw="RUNNING",
        stage_strip=_strip(
            VALIDATION="SUCCESS", BOUNDARY="SUCCESS", HERMES="SUCCESS",
            WORKBUDDY="RUNNING",
        ),
        progress_percent=percent,
        progress_text=f"整体进度：约 {percent}%（估算）",
        stage_share_text=share,
        stuck=stuck,
        stuck_warning=stuck_mod.STUCK_WARNING_TEXT,
        stuck_detail="最近 15 分钟没有活动" if stuck else "",
        task_dir=str(tmp_path),
        log_dir=str(tmp_path),
        report_path=None,
        empty_hint=None,
    )


def test_window_progress_bar_rendered(tk_root, tmp_path):
    ctl = StatusWindowController(
        tk_root, provider=lambda: _running_snapshot(tmp_path)
    )
    w = ctl.open()
    assert "整体进度" in w._lbl_progress.cget("text")
    assert "估算" in w._lbl_progress.cget("text")
    items = w._progress_canvas.find_all()
    assert len(items) >= 1  # 进度条填充矩形已绘制
    w.close()


def test_window_progress_bar_zero(tk_root, tmp_path):
    snap = _running_snapshot(tmp_path, percent=0, share="")
    snap.progress_text = prog.NO_INFO_TEXT
    ctl = StatusWindowController(tk_root, provider=lambda: snap)
    w = ctl.open()
    assert w._progress_canvas.find_all() == ()  # 0% → 无填充
    assert "暂无进度信息" in w._lbl_progress.cget("text")
    w.close()


def test_window_stuck_banner_shows(tk_root, tmp_path):
    ctl = StatusWindowController(
        tk_root, provider=lambda: _running_snapshot(tmp_path, stuck=True)
    )
    w = ctl.open()
    assert "任务可能已停滞" in w._lbl_stuck.cget("text")
    assert "15 分钟" in w._lbl_stuck.cget("text")
    assert w._lbl_stuck.winfo_manager() == "grid"  # 横幅可见
    w.close()


def test_window_stuck_banner_hidden_when_not_stuck(tk_root, tmp_path):
    ctl = StatusWindowController(
        tk_root, provider=lambda: _running_snapshot(tmp_path, stuck=False)
    )
    w = ctl.open()
    assert w._lbl_stuck.cget("text") == ""
    assert w._lbl_stuck.winfo_manager() != "grid"  # 已隐藏
    w.close()


def test_window_stage_highlight_running(tk_root, tmp_path):
    ctl = StatusWindowController(
        tk_root, provider=lambda: _running_snapshot(tmp_path)
    )
    w = ctl.open()
    assert w._cells["WORKBUDDY"].cget("bg") == sw.STAGE_RUNNING_BG
    assert w._cells["HERMES"].cget("bg") == w._cell_default_bg["HERMES"]  # 非进行中不高亮
    w.close()


def test_window_task_dir_button_opens_directory(tk_root, tmp_path, monkeypatch):
    opened = []

    def fake_open(path):
        opened.append(str(path))
        return True

    monkeypatch.setattr(sw, "open_directory", fake_open)
    ctl = StatusWindowController(
        tk_root, provider=lambda: _running_snapshot(tmp_path)
    )
    w = ctl.open()
    assert w.btn_task_dir.cget("state") != "disabled"
    w._on_open_task_dir()
    assert opened and opened[0] == str(tmp_path)
    w.close()


def test_window_phase_c_snapshot_compat(tk_root, tmp_path):
    # Phase C 旧 provider（无 Phase D 字段的 SimpleNamespace）→ 不崩溃（req 22 K 兼容）
    ctl = StatusWindowController(
        tk_root,
        provider=lambda: SimpleNamespace(
            has_task=True,
            project="P",
            workspace="W",
            bridge_status="正常运行",
            bridge_detail="",
            hotkey="Ctrl+Alt+A",
            task_id="AAF-OLD",
            task_name="T",
            stage="Hermes",
            agent="Hermes",
            elapsed="1分0秒",
            last_activity="刚刚",
            overall="执行中",
            overall_raw="RUNNING",
            stage_strip=_strip(HERMES="RUNNING"),
            log_dir=str(tmp_path),
            report_path=None,
            empty_hint=None,
        ),
    )
    w = ctl.open()
    w.refresh()  # 旧快照缺 Phase D 字段 → 防御性读取，不 TclError
    assert "暂无进度信息" in w._lbl_progress.cget("text")
    w.close()
