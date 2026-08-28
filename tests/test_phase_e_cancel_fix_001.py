"""Phase E FIX-001（AAF-v0.4-TASK-005-C-FIX-001）— Cancel Timestamp Timezone 兼容性回归测试。

关闭 Codex blocker：合法的 timezone-aware cancel.request timestamp 不得因与
naive datetime 直接运算而破坏 Cancel UI / force eligibility / restart recovery
（TypeError: can't subtract offset-naive and offset-aware datetimes）。

覆盖（TASK req 1–7 / acceptance 1–8）：
A. Canonical elapsed contract（cancel_mod.requested_at_elapsed_seconds）：
   - aware +08:00 / +00:00 / Z（UTC equivalent）→ 正确换算
   - legacy naive → 本地时间解释（向后兼容，req 4）
   - malformed / 非字符串 → None（fail closed，req 5）
   - 未来时间戳 → 0.0（不产生负年龄、不提前 force）
B. collect_cancel_ui 不抛异常（req 2/7）：
   - +08:00 / +00:00 / legacy naive：超时前 STOP_REQUESTED、超时后 CANCELLING
   - malformed → STOP_REQUESTED（fail closed：不提供 Force、不询问 backend）
C. force_eligible 不抛异常（req 3/8）——真实 FrameworkLauncher + registry artifact：
   - +08:00 / +00:00 / legacy naive 超时后 → eligible
   - 超时前 → 不 eligible（SOFT_CANCEL_TIMEOUT_NOT_REACHED）
   - malformed → CANCEL_REQUEST_BAD_TIMESTAMP（fail closed）
D. restart/reopen 推导（req 6）：两个独立 collect 会话从相同 aware artifacts
   得到相同 Cancel UI 状态（不进入 unknown_snapshot）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_agent_framework import cancel as cancel_mod

from bridge import launch_registry as reg_mod
from bridge import status_window as sw
from bridge.launcher import FrameworkLauncher
from bridge.status_window import CANCEL_UI_CANCELLING, CANCEL_UI_STOP_REQUESTED, collect_cancel_ui

TID = "T-TZ-FIX"

# 确定性“现在”（UTC aware），供 elapsed 纯函数测试注入
NOW_UTC = datetime(2026, 8, 28, 6, 0, 0, tzinfo=timezone.utc)


def _aware_iso(ago: timedelta, offset_hours: int) -> str:
    """offset_hours 时区的 aware ISO 时间戳：now - ago。"""
    tz = timezone(timedelta(hours=offset_hours))
    return (datetime.now(tz) - ago).isoformat(timespec="seconds")


def _z_iso(ago: timedelta) -> str:
    """UTC equivalent（Z 后缀）ISO 时间戳：now(UTC) - ago。"""
    return (datetime.now(timezone.utc) - ago).isoformat(timespec="seconds").replace("+00:00", "Z")


def _naive_iso(ago: timedelta) -> str:
    """legacy naive 本地时间戳（历史 write_cancel_request 默认格式）。"""
    return (datetime.now() - ago).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# A. Canonical elapsed contract（cancel_mod.requested_at_elapsed_seconds）
# ---------------------------------------------------------------------------


def test_elapsed_aware_plus0800():
    # 2026-08-28T14:00:00+08:00 == 06:00:00 UTC == NOW_UTC → 0s
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T14:00:00+08:00", now=NOW_UTC) == 0.0
    # 90s 前（同一时刻的 +08:00 表达）→ 90s
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T13:58:30+08:00", now=NOW_UTC) == 90.0
    # 2h 前 → 7200s
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T12:00:00+08:00", now=NOW_UTC) == 7200.0


def test_elapsed_aware_plus0000():
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T06:00:00+00:00", now=NOW_UTC) == 0.0
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T05:58:30+00:00", now=NOW_UTC) == 90.0


def test_elapsed_utc_z_equivalent():
    # UTC equivalent（Z 后缀）与 +00:00 同刻 → 同一 elapsed
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T05:58:30Z", now=NOW_UTC) == 90.0
    assert cancel_mod.requested_at_elapsed_seconds("2026-08-28T06:00:00Z", now=NOW_UTC) == 0.0


def test_elapsed_legacy_naive_local_interpretation():
    """legacy naive → 明确解释为本地时间（req 4：与历史 writer 语义一致）。"""
    local_now = NOW_UTC.astimezone()  # 本机本地时区的同一时刻
    naive_ts = (local_now - timedelta(seconds=90)).replace(tzinfo=None).isoformat(timespec="seconds")
    assert cancel_mod.requested_at_elapsed_seconds(naive_ts, now=NOW_UTC) == 90.0
    # naive now 注入（同样按本地解释）→ 一致
    assert cancel_mod.requested_at_elapsed_seconds(
        naive_ts, now=local_now.replace(tzinfo=None)) == 90.0
    # 同一时刻用 +08:00 表达 → 同样 90s（offset 无关）
    plus08 = (local_now - timedelta(seconds=90)).astimezone(timezone(timedelta(hours=8)))
    assert cancel_mod.requested_at_elapsed_seconds(
        plus08.isoformat(timespec="seconds"), now=NOW_UTC) == 90.0


def test_elapsed_malformed_fail_closed():
    """malformed / 非法 → None（fail closed：不得产生 force eligibility，req 5）。

    注：date-only（如 "2026-08-28"）按既有 parse_requested_at contract 可解析
    （recovery evidence 校验同规则），不在 malformed 之列。
    """
    for bad in ("", "not-a-date", "2026-13-99T99:99:99", None, 123, ["x"]):
        assert cancel_mod.requested_at_elapsed_seconds(bad, now=NOW_UTC) is None, repr(bad)


def test_elapsed_future_timestamp_clamped_zero():
    """未来时间戳 → 0.0（不产生负年龄；未达 timeout → 不 force）。"""
    ts = "2026-08-28T08:00:00+08:00"  # == 2026-08-28T00:00:00Z；NOW_UTC=06:00Z → 6h 前
    assert cancel_mod.requested_at_elapsed_seconds(ts, now=NOW_UTC) == 21600.0
    ts_future = "2026-08-28T20:00:00+08:00"  # == 2026-08-28T12:00:00Z > NOW_UTC → 未来
    assert cancel_mod.requested_at_elapsed_seconds(ts_future, now=NOW_UTC) == 0.0


# ---------------------------------------------------------------------------
# B. collect_cancel_ui 不抛异常（req 2/7；合法 aware 值不得破坏 Cancel UI）
# ---------------------------------------------------------------------------


class _Verdict:
    result = "VERIFIED"

    def ok(self):
        return True


class _EligibleLauncher:
    """backend 明确 eligible + ownership VERIFIED；记录 force_eligible 调用。"""

    def __init__(self):
        self.calls: list[str] = []

    def force_eligible(self, task_id):
        self.calls.append(task_id)
        return True, "soft cancel timeout reached"

    def ownership_status(self, task_id):
        return _Verdict()


def _make_out(tmp_path: Path) -> Path:
    out = tmp_path / TID
    out.mkdir(parents=True, exist_ok=True)
    (out / "task.json").write_text(json.dumps({
        "task_id": TID, "status": "RUNNING",
        "task_path": str(tmp_path / "TASK.md"), "workspace": str(tmp_path),
    }), encoding="utf-8")
    return out


@pytest.mark.parametrize("mk_ts", [
    partial(_aware_iso, offset_hours=8),
    partial(_aware_iso, offset_hours=0),
    _z_iso,
    _naive_iso,
])
def test_collect_cancel_ui_aware_before_timeout_no_exception(tmp_path, mk_ts):
    """超时前（fresh 请求）：不抛异常 → STOP_REQUESTED；backend 不被询问。"""
    out = _make_out(tmp_path)
    cancel_mod.write_cancel_request(out, TID, requested_at=mk_ts(timedelta(seconds=5)))
    launcher = _EligibleLauncher()
    cu = collect_cancel_ui(launcher, TID, out, "RUNNING")
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert not cu.can_force
    assert launcher.calls == []  # 未达 timeout → 不询问 backend


@pytest.mark.parametrize("offset_hours", [8, 0])
def test_collect_cancel_ui_aware_after_timeout_no_exception(tmp_path, offset_hours):
    """超时后 +08:00 / +00:00 aware 请求：不抛异常 → CANCELLING + Force 可用。"""
    out = _make_out(tmp_path)
    cancel_mod.write_cancel_request(out, TID, requested_at=_aware_iso(timedelta(seconds=120), offset_hours))
    launcher = _EligibleLauncher()
    cu = collect_cancel_ui(launcher, TID, out, "RUNNING")
    assert cu.state == CANCEL_UI_CANCELLING
    assert cu.can_force
    assert launcher.calls == [TID]


def test_collect_cancel_ui_legacy_naive_after_timeout(tmp_path):
    """legacy naive 超时后 → 同样 CANCELLING（向后兼容，req 4）。"""
    out = _make_out(tmp_path)
    cancel_mod.write_cancel_request(out, TID, requested_at=_naive_iso(timedelta(seconds=120)))
    cu = collect_cancel_ui(_EligibleLauncher(), TID, out, "RUNNING")
    assert cu.state == CANCEL_UI_CANCELLING and cu.can_force


def test_collect_cancel_ui_malformed_fail_closed(tmp_path):
    """malformed requested_at：不抛异常 → STOP_REQUESTED；不提供 Force；backend 不被询问。"""
    out = _make_out(tmp_path)
    (out / "cancel.request").write_text(json.dumps({
        "task_id": TID, "requested_at": "garbage-timestamp", "request": "soft_cancel",
    }), encoding="utf-8")
    launcher = _EligibleLauncher()
    cu = collect_cancel_ui(launcher, TID, out, "RUNNING")
    assert cu.state == CANCEL_UI_STOP_REQUESTED
    assert not cu.can_force and not cu.can_stop
    assert launcher.calls == []


# ---------------------------------------------------------------------------
# C. force_eligible 不抛异常（req 3/8；真实 FrameworkLauncher + registry）
# ---------------------------------------------------------------------------


def _force_ctx(tmp_path: Path, requested_at: str) -> FrameworkLauncher:
    """真实 launcher + registry artifact + cancel.request（不启动任何进程）。"""
    out = _make_out(tmp_path)
    cancel_mod.write_cancel_request(out, TID, requested_at=requested_at)
    launcher = FrameworkLauncher(registry_dir=tmp_path / "reg")
    lid = "tz-fix-" + uuid4().hex[:12]
    reg_mod.create_prepared(
        launch_id=lid,
        task_id=TID,
        workspace=str(tmp_path),
        output_dir=str(out),
        expected_runner_entry="run.py",
        expected_command_line=[str(Path("python")), "run.py"],
        launcher_instance_id="test-instance",
        root=launcher._registry_dir,
    )
    return launcher, lid


@pytest.mark.parametrize("offset_hours", [8, 0])
def test_force_eligible_aware_after_timeout(tmp_path, offset_hours):
    """+08:00 / +00:00 aware 超时后 → eligible（正确计算 timeout/eligibility）。"""
    launcher, lid = _force_ctx(tmp_path, _aware_iso(timedelta(seconds=120), offset_hours))
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert eligible, why
    assert ">=" in why and "30.0" in why  # elapsed >= timeout（elapsed 随真实墙钟略 > 120s）


def test_force_eligible_utc_z_after_timeout(tmp_path):
    launcher, lid = _force_ctx(tmp_path, _z_iso(timedelta(seconds=120)))
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert eligible, why


def test_force_eligible_legacy_naive_after_timeout(tmp_path):
    """legacy naive 超时后 → eligible（向后兼容）。"""
    launcher, lid = _force_ctx(tmp_path, _naive_iso(timedelta(seconds=120)))
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert eligible, why


def test_force_eligible_before_timeout_not_eligible(tmp_path):
    """fresh aware 请求（超时前）：不抛异常 → 不 eligible（SOFT_CANCEL_TIMEOUT_NOT_REACHED）。"""
    launcher, lid = _force_ctx(tmp_path, _aware_iso(timedelta(seconds=5), 8))
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert not eligible
    assert "SOFT_CANCEL_TIMEOUT_NOT_REACHED" in why


def test_force_eligible_future_aware_not_eligible(tmp_path):
    """未来 aware 时间戳：elapsed=0 → 不 eligible（不提前 force）。"""
    tz8 = timezone(timedelta(hours=8))
    future = (datetime.now(tz8) + timedelta(hours=1)).isoformat(timespec="seconds")
    launcher, lid = _force_ctx(tmp_path, future)
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert not eligible
    assert "SOFT_CANCEL_TIMEOUT_NOT_REACHED" in why


def test_force_eligible_malformed_fail_closed(tmp_path):
    """malformed requested_at：不抛异常 → CANCEL_REQUEST_BAD_TIMESTAMP（fail closed）。"""
    launcher, lid = _force_ctx(tmp_path, "garbage-timestamp")
    eligible, why = launcher.force_eligible(TID, lid, soft_timeout=30.0)
    assert not eligible
    assert why == "CANCEL_REQUEST_BAD_TIMESTAMP"


# ---------------------------------------------------------------------------
# D. restart/reopen 推导（req 6：不因 timezone 合法值进入 unknown_snapshot）
# ---------------------------------------------------------------------------


def test_restart_reopen_derived_state_with_aware_timestamp(tmp_path):
    """窗口/重启后：两个独立 collect 会话（零共享内存）从相同 aware artifacts
    推导出相同 Cancel UI 状态（CANCELLING），且 collect_status 快照不降级
    unknown_snapshot。"""
    out = _make_out(tmp_path)
    cancel_mod.write_cancel_request(out, TID, requested_at=_aware_iso(timedelta(seconds=120), 8))

    def derive_in_session():
        return collect_cancel_ui(_EligibleLauncher(), TID, out, "RUNNING")

    a = derive_in_session()
    b = derive_in_session()
    assert a.state == b.state == CANCEL_UI_CANCELLING
    assert a.message == b.message and a.can_force == b.can_force

    # collect_status（窗口 provider 路径）同样不抛异常 → 不进入 unknown_snapshot
    class _StatusLauncher(_EligibleLauncher):
        state = "IDLE"
        last = SimpleNamespace(
            task_id=TID, task_path=str(out / "TASK.md"), output_dir=str(out),
            report_path=None, exit_code=0, result="RUNNING",
        )
        current = None

        def load_last(self):
            return self.last

    snap = sw.collect_status(
        {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": str(tmp_path)},
        ("OK", "正常运行"), _StatusLauncher(),
    )
    assert snap.has_task
    assert snap.cancel_ui is not None
    assert snap.cancel_ui.state == CANCEL_UI_CANCELLING
