"""RW-012 — hotkey listener self-recovery（有界 backoff；唯一 owner = Bridge 实例）。

实际 gap（来自代码勘察，非仅 backlog 标题）：HotkeyListener 是 daemon 线程
（bridge/win32.py：GetMessageW 消息循环），线程意外退出（GetMessageW <= 0 /
异常）后 OS 自动注销该线程关联的热键；classify_bridge_health 只能检测出
DEGRADED（"热键监听线程已退出"），此前无任何自恢复——用户只能手动重启 Bridge。

RW-012 FIX-001（listener-owned lifecycle）：修复 Codex 确认的 lifecycle
ownership defect——registration 归 listener 线程所有，注销必须在 listener
线程内完成（thread-owned unregister），Bridge 主线程只请求 stop（stop 契约：
request_stop + 有界 join），stop-before-replace，旧 listener 超时未退出 →
fail safe（不启动 duplicate replacement），并发 lifecycle transition 由
_lifecycle_lock 合并为单一 owner。

RW-012 FIX-002（ownership retention + readiness truth）：stop 超时不再清空
self.listener（旧 listener 未确认退出前 Bridge 持续持有其引用，记入
_pending_stop → DEGRADED / recovery pending，跨 recovery cycle 不启动
replacement）；wait_ready 返回值参与 start success 判定（初始化超时 /
error 均不 reset recovery、不报告 healthy）；健康判定区分 alive / ready /
error（thread alive != hotkey usable）。

本文件覆盖（全部非 GUI / 不注册真实热键 / 不触碰用户会话）：
A. listener 意外退出 → 恢复尝试 → 只有一个活跃 listener
B. 恢复成功 → Bridge 保持可用（健康 OK）；stop-before-replace 顺序
C. 恢复反复失败 / 旧 listener 卡死 → 有界重试/backoff → 可见 warning/状态 → 无 tight loop
D. 主动退出 → 不触发恢复；intentional shutdown → stop 契约收尾、不复活
E. 多次恢复触发 → coalesce → 无重复 listener / 无重复热键注册
F. Bridge 退出期间 → 无复活（shutting_down 阻止）
G. listener 健康 → 不无谓重启
H. 配置热加载热键变化 → 旧 registration 完整释放后新 listener 注册
I. 连续失败 → 有界行为；concurrency guard → 单一 transition owner
"""
from __future__ import annotations

import threading
import time

import pytest

from bridge import main as bridge_main


# ---------- 测试桩 ----------


class FakeListener:
    """模拟 HotkeyListener 的最小健康接口（error / is_alive / is_ready）+ stop 契约。"""

    def __init__(self, error=None, alive=True, ready=True, stop_result=True):
        self._error = error
        self._alive = alive
        self._ready = ready
        self._stop_result = stop_result
        self.stop_requests = 0  # stop 契约调用计数

    def error(self):
        return self._error

    def is_alive(self):
        return self._alive

    def is_ready(self):
        return self._ready

    def request_stop(self):
        self.stop_requests += 1

    def stop(self, timeout=5.0):
        self.stop_requests += 1
        if self._stop_result:
            self._alive = False  # 模拟线程确认退出（thread-owned unregister 已完成）
        return self._stop_result


class StubRoot:
    """替代 tk.Tk：只记录 after 调度，不进入事件循环。"""

    def __init__(self):
        self.afters: list[tuple[int, object]] = []

    def after(self, ms, callback=None):
        self.afters.append((ms, callback))


class _Clock:
    """可控 monotonic 时钟（模拟时间推进，避免真实 sleep）。"""

    def __init__(self, start=1000.0):
        self.t = start

    def monotonic(self):
        return self.t


def _stub_bridge(listener=None, recovery=None, shutting_down=False, tray=None):
    """object.__new__ 构造 Bridge 桩：不触 tkinter / ctypes / 真实热键。"""
    b = object.__new__(bridge_main.Bridge)
    b.root = StubRoot()
    b._shutting_down = shutting_down
    b._recovery = recovery if recovery is not None else bridge_main.HotkeyRecovery()
    b.listener = listener
    b._pending_stop = None
    b.tray = tray
    b._last_health = None
    b._lifecycle_lock = threading.Lock()
    return b


# ---------- HotkeyRecovery 策略（纯逻辑） ----------


def test_fresh_policy_allows_attempt():
    r = bridge_main.HotkeyRecovery()
    assert r.should_attempt(100.0) is True
    assert r.note() == ""


def test_backoff_gates_next_attempt():
    r = bridge_main.HotkeyRecovery()
    r.begin_attempt()
    r.record_failure(100.0)
    # 失败后立即 / 未到 backoff 终点 → 不允许（无 tight loop）
    assert r.should_attempt(100.0) is False
    assert r.should_attempt(114.99) is False
    assert r.should_attempt(115.0) is True  # 默认 15s 后允许重试
    assert r.consecutive_failures == 1
    assert "重试" in r.note()


def test_backoff_schedule_increases():
    r = bridge_main.HotkeyRecovery()
    r.begin_attempt()
    r.record_failure(100.0)  # 失败 #1 → 15s
    assert r._next_attempt_at == pytest.approx(115.0)
    r.begin_attempt()
    r.record_failure(115.0)  # 失败 #2 → 30s
    assert r._next_attempt_at == pytest.approx(145.0)
    r.begin_attempt()
    r.record_failure(145.0)  # 失败 #3 → 达上限
    assert r.stopped is True


def test_max_failures_stops_recovery_bounded():
    r = bridge_main.HotkeyRecovery(max_failures=3)
    for i, now in enumerate((100.0, 115.0, 145.0)):
        assert r.should_attempt(now) is True
        r.begin_attempt()
        r.record_failure(now)
    assert r.stopped is True
    # 停止后任何时刻都不再尝试（有界）
    assert r.should_attempt(99999.0) is False
    assert "停止" in r.note()


def test_success_resets_failures_and_reenables():
    r = bridge_main.HotkeyRecovery()
    r.begin_attempt()
    r.record_failure(100.0)
    r.begin_attempt()
    r.record_success()
    assert r.consecutive_failures == 0
    assert r.stopped is False
    assert r.should_attempt(100.0) is True  # 成功 → 立即可再次恢复


def test_reset_reenables_after_stopped():
    r = bridge_main.HotkeyRecovery(max_failures=2)
    for now in (100.0, 115.0):
        r.begin_attempt()
        r.record_failure(now)
    assert r.stopped is True
    r.reset()  # 用户改配置 / 手动重启 → 恢复能力重新开放
    assert r.stopped is False
    assert r.consecutive_failures == 0
    assert r.should_attempt(100.0) is True


def test_shutdown_blocks_attempts():
    r = bridge_main.HotkeyRecovery()
    # 即使恢复到期，主动退出期间也不允许尝试（退出不复活）
    assert r.should_attempt(100.0, shutting_down=True) is False
    r.begin_attempt()
    r.record_failure(100.0)
    assert r.should_attempt(200.0, shutting_down=True) is False


def test_recovering_coalesces_duplicate_triggers():
    r = bridge_main.HotkeyRecovery()
    r.begin_attempt()  # 恢复进行中
    # 第二次触发被拒绝 → 不会重复发起 / 不会产生第二个 listener
    assert r.should_attempt(99999.0) is False
    assert r.recovering is True
    r.record_success()
    assert r.recovering is False


def test_note_states_observable():
    r = bridge_main.HotkeyRecovery()
    assert r.note() == ""
    r.begin_attempt()
    assert "正在自动恢复" in r.note()
    r.record_failure(100.0)
    assert "第 1 次自动恢复失败" in r.note()
    r.record_failure(115.0)
    r.record_failure(145.0)
    assert "停止" in r.note()


# ---------- Bridge._poll_health 集成（A/B/C/D/E/F/G） ----------


def test_poll_health_recovers_dead_listener_exactly_once(monkeypatch):
    """A/G：listener 意外退出 → 恢复尝试 → 恰好一个活跃 listener；健康 → 不无谓重启。"""
    monkeypatch.setattr(bridge_main.time, "monotonic", _Clock().monotonic)
    b = _stub_bridge(listener=FakeListener(alive=False))
    calls = []

    def recover():
        calls.append(1)
        b.listener = FakeListener(alive=True)  # 恢复成功：重建 listener
        return True

    b._try_recover_hotkey = recover

    b._poll_health()
    assert len(calls) == 1
    assert b.listener.is_alive()  # 恢复后 Bridge 可用（B）
    assert b._recovery.consecutive_failures == 0
    assert b._recovery.note() == ""

    b._poll_health()  # 再次轮询：已健康 → 不再恢复
    assert len(calls) == 1  # 无重复触发 / 无第二个 listener


def test_poll_health_no_recovery_when_healthy():
    """G：listener 健康 → 不无谓重启。"""
    b = _stub_bridge(listener=FakeListener(alive=True))
    calls = []
    b._try_recover_hotkey = lambda: calls.append(1) or True
    b._poll_health()
    assert calls == []


def test_poll_health_no_recovery_when_shutting_down():
    """D/F：主动退出 / 退出期间 → 不触发恢复（不复活）。"""
    b = _stub_bridge(listener=FakeListener(alive=False), shutting_down=True)
    calls = []
    b._try_recover_hotkey = lambda: calls.append(1) or True
    b._poll_health()
    assert calls == []
    # 轮询链仍被调度（退出确认取消时 Bridge 继续运行）
    assert len(b.root.afters) >= 1


def test_poll_health_repeated_failure_bounded_three_then_stop(monkeypatch):
    """C：反复失败 → 有界重试/backoff → 停止 → 可见状态 → 无 tight loop。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    b = _stub_bridge(listener=FakeListener(alive=False))
    calls = []
    b._try_recover_hotkey = lambda: calls.append(1) or False  # 恢复一直失败

    b._poll_health()  # t=1000：失败 #1 → 15s backoff
    assert len(calls) == 1
    assert "重试" in b._recovery.note()

    b._poll_health()  # t=1000 未到 backoff → 不重试（无 tight loop）
    assert len(calls) == 1

    clock.t = 1015.0
    b._poll_health()  # 失败 #2 → 30s backoff
    assert len(calls) == 2

    clock.t = 1045.0
    b._poll_health()  # 失败 #3 → 达上限，停止自动恢复
    assert len(calls) == 3
    assert b._recovery.stopped is True

    clock.t = 2000.0
    b._poll_health()  # 停止后不再尝试
    assert len(calls) == 3
    assert "停止" in b._recovery.note()  # 失败保持可观察


def test_poll_health_no_duplicate_trigger_while_recovering():
    """E：恢复进行中的重复触发被 coalesce（策略层 + 轮询层双重验证）。"""
    b = _stub_bridge(listener=FakeListener(alive=False))
    calls = []
    b._try_recover_hotkey = lambda: calls.append(1) or False
    b._recovery.begin_attempt()  # 模拟一次恢复已在进行
    b._poll_health()
    assert calls == []  # 不重复发起


# ---------- Bridge._apply_hotkey / _stop_listener / _try_recover_hotkey ----------


def _make_recording_listener_class(created, events, err=None, stop_result=True):
    """构造记录型 Fake HotkeyListener：记录创建 / stop 请求 / 确认退出的顺序事件。"""

    class FakeHK:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            created.append(self)
            self._err = err
            self._alive = True
            self._stop_result = stop_result
            self.stop_requests = 0
            self._hotkey_args = (mods, vk, hotkey_id)
            events.append(("create", self))

        def start(self):
            pass

        def wait_ready(self, timeout):
            return True  # FIX-002：wait_ready 返回值参与 start success 判定

        def is_ready(self):
            return True

        def error(self):
            return self._err

        def is_alive(self):
            return self._alive

        def request_stop(self):
            self.stop_requests += 1

        def stop(self, timeout=5.0):
            self.stop_requests += 1
            if self._stop_result:
                self._alive = False  # 模拟线程确认退出（thread-owned unregister 已完成）
                events.append(("old-exited", self))
            return self._stop_result

    return FakeHK


def _stub_bridge_with_hotkey(b, hotkey="ctrl+alt+a"):
    b.cfg = {"hotkey": hotkey}
    b.hotkey_id = 1
    b._on_hotkey = lambda: None
    return b


def test_apply_hotkey_stop_before_replace(monkeypatch):
    """B：重建前旧 listener 先收到 stop 请求并确认退出，然后才创建新 listener。"""
    created = []
    events = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_recording_listener_class(created, events)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())

    b._apply_hotkey()
    first = b.listener
    b._apply_hotkey()  # 再次应用（配置热加载 / 恢复）→ stop-before-replace
    assert len(created) == 2
    assert first.stop_requests >= 1  # 旧 listener 收到 stop 请求（不再主线程直接注销）
    # 顺序：旧 listener 确认退出（thread-owned unregister 完成）→ 新 listener 创建
    assert events.index(("old-exited", first)) < events.index(("create", created[1]))
    assert b.listener is created[1]  # 当前唯一活跃 listener = 最新实例
    assert b.listener is not first


def test_apply_hotkey_old_listener_stuck_fails_safe_no_duplicate(monkeypatch):
    """C：旧 listener 未能在限时内退出 → 不创建 replacement；warning 可见；
    FIX-002：ownership reference 保留（不伪装健康、不丢引用、跨 cycle 不重复）。"""
    created = []
    events = []
    logs = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_recording_listener_class(created, events, stop_result=False),
    )
    monkeypatch.setattr(bridge_main, "_log", lambda m: logs.append(m))
    b = _stub_bridge_with_hotkey(_stub_bridge())

    b._apply_hotkey()
    assert len(created) == 1
    first = b.listener
    b._apply_hotkey()  # 旧 listener 卡死 → fail safe
    assert len(created) == 1  # 没有第二个 listener（无重复注册）
    assert first.stop_requests >= 1  # stop 契约确实被调用（有界等待后放弃）
    # FIX-002：stop 未确认退出 → Bridge 仍持有 old listener 的 ownership reference
    assert b.listener is first
    assert b._pending_stop is first
    assert any("限时内退出" in m and "fail safe" in m for m in logs)  # warning 可观察
    # health 不伪装 healthy（pending → DEGRADED）
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "未确认退出" in detail


def test_apply_hotkey_concurrency_guard_single_transition_owner(monkeypatch):
    """G：lifecycle transition 进行中（锁被持有）→ 并发触发被合并，不创建 listener。"""
    created = []
    events = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_recording_listener_class(created, events)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    assert b._lifecycle_lock.acquire(blocking=False)  # 模拟已有 transition owner
    try:
        b._apply_hotkey()
    finally:
        b._lifecycle_lock.release()
    assert created == []  # 被合并：无 listener / 无重复注册


def test_apply_hotkey_hotkey_change_releases_old_then_registers_new(monkeypatch):
    """H：热键变化 → 旧 listener stop（thread-owned 释放旧 registration）→
    新 listener 以新 mods/vk 注册；无 orphan listener 残留。"""
    created = []
    events = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_recording_listener_class(created, events)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge(), hotkey="ctrl+alt+a")
    b._apply_hotkey()
    old = b.listener
    b.cfg = {"hotkey": "ctrl+alt+shift+k"}
    b._apply_hotkey()  # 配置热加载 → 旧 registration 完整释放后注册新热键
    assert len(created) == 2
    # 旧 listener 已确认退出（无 orphan），新 listener 接管同一 hotkey_id
    assert ("old-exited", old) in events
    assert b.listener is created[1]
    assert b.listener.is_alive()
    # 新热键参数（shift 参与 mods）与旧热键不同
    assert created[1]._hotkey_args != created[0]._hotkey_args


def test_shutdown_stops_listener_without_recovery():
    """F：intentional shutdown → listener stop 契约收尾；不触发恢复。"""
    b = _stub_bridge(listener=FakeListener(alive=True))
    b.shutdown()
    assert b._shutting_down is True  # 恢复被策略拒绝（退出不复活）
    assert b.listener is None
    assert b._recovery.consecutive_failures == 0  # 无恢复尝试发生


def test_shutdown_idempotent():
    """F：shutdown 幂等（listener 已停止后再调用无副作用）。"""
    b = _stub_bridge()
    b.shutdown()
    b.shutdown()
    assert b.listener is None


def test_apply_hotkey_recovery_mode_suppresses_dialog(monkeypatch):
    """恢复路径不弹窗（避免重试期间 dialog 轰炸；失败经状态可见）。"""
    shown = []

    class FakeHK:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            self._err = RuntimeError("热键被占用")

        def start(self):
            pass

        def wait_ready(self, timeout):
            return True  # FIX-002：wait_ready 返回值参与 start success 判定

        def is_ready(self):
            return True

        def error(self):
            return self._err

        def is_alive(self):
            return False

        def stop(self, timeout=5.0):
            return True

    monkeypatch.setattr(bridge_main, "HotkeyListener", FakeHK)
    monkeypatch.setattr(bridge_main.ui, "show_error", lambda *a, **k: shown.append(a))

    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey(show_error=False)  # 恢复路径
    assert shown == []
    # 默认路径（用户操作 / 启动）仍弹窗
    b._apply_hotkey()
    assert len(shown) == 1


def test_try_recover_hotkey_success_replaces_dead_listener():
    """A/B：恢复 = 重建 listener（不重启 Bridge）；成功后 Bridge 健康可用。"""
    b = _stub_bridge(listener=FakeListener(alive=False))
    b._apply_hotkey = lambda show_error=True: setattr(
        b, "listener", FakeListener(alive=True)
    )
    assert b._try_recover_hotkey() is True
    assert b.listener.is_alive()  # Bridge 保持可用


def test_try_recover_hotkey_failure_returns_false():
    b = _stub_bridge(listener=FakeListener(alive=False))
    b._apply_hotkey = lambda show_error=True: setattr(
        b, "listener", FakeListener(alive=False)  # 恢复仍失败（如冲突未解除）
    )
    assert b._try_recover_hotkey() is False


def test_try_recover_hotkey_exception_fails_safely():
    b = _stub_bridge(listener=FakeListener(alive=False))

    def boom(show_error=True):
        raise RuntimeError("unexpected")

    b._apply_hotkey = boom
    assert b._try_recover_hotkey() is False
    assert b.listener is None  # 失败不留半态


def test_stop_listener_bounded_timeout_returns_false():
    """stop 契约有界：listener.stop 超时 → _stop_listener 返回 False（fail safe 信号）；
    FIX-002：stop 未确认退出 → 不清空 self.listener（ownership retention）。"""
    old = FakeListener(alive=True, stop_result=False)
    b = _stub_bridge(listener=old)
    assert b._stop_listener(timeout=0.5) is False
    # 旧 listener 仍可能存活 → Bridge 必须持续持有其引用（不 orphan、不伪装成功）
    assert b.listener is old
    assert b._pending_stop is old


def test_stop_listener_returns_true_when_no_listener():
    b = _stub_bridge()
    assert b._stop_listener() is True


def test_stop_listener_dead_listener_returns_true():
    """恢复路径：旧线程已意外退出 → stop 立即确认（join 不阻塞），可启动 replacement。"""
    b = _stub_bridge(listener=FakeListener(alive=False))
    assert b._stop_listener() is True


def test_poll_config_hotkey_change_stops_old_then_starts_new(monkeypatch):
    """H：配置热加载（mtime 变化 + hotkey 变化）→ stop-before-replace 全流程。"""
    created = []
    events = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_recording_listener_class(created, events)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    monkeypatch.setattr(b, "_config_mtime", lambda: 999.0)
    b._cfg_mtime = 1.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+shift+k"}
    )
    b._poll_config()
    assert len(created) == 2
    assert ("old-exited", old) in events  # 旧 listener 退出（无 orphan）
    assert b.listener is created[1]
    assert created[1]._hotkey_args[1] != created[0]._hotkey_args[1]  # 新热键生效


def test_poll_health_rebuild_conflict_bounded_three_then_stop(monkeypatch):
    """I：重建连续失败（新 listener 注册冲突，如旧 registration 未释放/热键占用）
    → 有界重试（真实 _apply_hotkey 路径）→ 自动恢复停止 → 无 tight loop。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []

    class FailingHK:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            created.append(self)
            self._err = RuntimeError("热键被占用")

        def start(self):
            pass

        def wait_ready(self, timeout):
            return True  # FIX-002：wait_ready 返回值参与 start success 判定

        def is_ready(self):
            return True

        def error(self):
            return self._err

        def is_alive(self):
            return False

        def stop(self, timeout=5.0):
            return True

    monkeypatch.setattr(bridge_main, "HotkeyListener", FailingHK)
    b = _stub_bridge_with_hotkey(_stub_bridge(listener=FakeListener(alive=False)))

    b._poll_health()  # t=1000：失败 #1 → 15s backoff
    assert len(created) == 1
    assert "重试" in b._recovery.note()

    b._poll_health()  # 未到 backoff 终点 → 不重试（无 tight loop）
    assert len(created) == 1

    clock.t = 1015.0
    b._poll_health()  # 失败 #2 → 30s backoff
    assert len(created) == 2

    clock.t = 1045.0
    b._poll_health()  # 失败 #3 → 达上限，停止自动恢复
    assert len(created) == 3
    assert b._recovery.stopped is True

    clock.t = 5000.0
    b._poll_health()  # 停止后不再尝试
    assert len(created) == 3
    assert "停止" in b._recovery.note()  # 失败保持可观察


# ---------- 可观察性 ----------


def test_current_health_includes_recovery_note():
    """恢复失败必须可观察：状态窗口 / Tray detail 带恢复说明。"""
    b = _stub_bridge(listener=FakeListener(alive=False))
    b._recovery.begin_attempt()
    b._recovery.record_failure(100.0)
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "热键监听线程已退出" in detail
    assert "第 1 次自动恢复失败" in detail


def test_current_health_ok_without_note():
    b = _stub_bridge(listener=FakeListener(alive=True))
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_OK
    assert "正常" in detail
