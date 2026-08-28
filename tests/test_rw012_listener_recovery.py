"""RW-012 — hotkey listener self-recovery（有界 backoff；唯一 owner = Bridge 实例）。

实际 gap（来自代码勘察，非仅 backlog 标题）：HotkeyListener 是 daemon 线程
（bridge/win32.py：GetMessageW 消息循环），线程意外退出（GetMessageW <= 0 /
异常）后 OS 自动注销该线程关联的热键；classify_bridge_health 只能检测出
DEGRADED（"热键监听线程已退出"），此前无任何自恢复——用户只能手动重启 Bridge。

本文件覆盖（全部非 GUI / 不注册真实热键 / 不触碰用户会话）：
A. listener 意外退出 → 恢复尝试 → 只有一个活跃 listener
B. 恢复成功 → Bridge 保持可用（健康 OK）
C. 恢复反复失败 → 有界重试/backoff → 可见 warning/状态 → 无 tight loop
D. 主动退出 → 不触发恢复
E. 多次恢复触发 → coalesce → 无重复 listener / 无重复热键注册
F. Bridge 退出期间 → 无复活（shutting_down 阻止）
G. listener 健康 → 不无谓重启
"""
from __future__ import annotations

import time

import pytest

from bridge import main as bridge_main


# ---------- 测试桩 ----------


class FakeListener:
    """模拟 HotkeyListener 的最小健康接口（error / is_alive）。"""

    def __init__(self, error=None, alive=True):
        self._error = error
        self._alive = alive

    def error(self):
        return self._error

    def is_alive(self):
        return self._alive


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
    b.tray = tray
    b._last_health = None
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


# ---------- Bridge._apply_hotkey / _try_recover_hotkey ----------


def test_apply_hotkey_single_owner_replaces_listener(monkeypatch):
    """E：唯一 owner 语义——重建前先注销旧热键；当前只保留一个 listener。"""
    created = []

    class FakeHK:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            created.append(self)
            self._err = None

        def start(self):
            pass

        def wait_ready(self, timeout):
            pass

        def error(self):
            return self._err

        def is_alive(self):
            return True

    monkeypatch.setattr(bridge_main, "HotkeyListener", FakeHK)
    unregistered = []
    monkeypatch.setattr(bridge_main, "unregister_hotkey", lambda hid: unregistered.append(hid))

    b = _stub_bridge()
    b.cfg = {"hotkey": "ctrl+alt+a"}
    b.hotkey_id = 1
    b._on_hotkey = lambda: None

    b._apply_hotkey()
    first = b.listener
    b._apply_hotkey()  # 再次应用（如配置热加载 / 恢复）→ 先注销旧热键再注册
    assert len(created) == 2
    assert unregistered == [1]  # 重建前注销旧热键一次（首次无旧 listener 可注销）
    assert b.listener is created[1]  # 当前唯一活跃 listener = 最新实例
    assert b.listener is not first


def test_apply_hotkey_recovery_mode_suppresses_dialog(monkeypatch):
    """恢复路径不弹窗（避免重试期间 dialog 轰炸；失败经状态可见）。"""
    shown = []

    class FakeHK:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            self._err = RuntimeError("热键被占用")

        def start(self):
            pass

        def wait_ready(self, timeout):
            pass

        def error(self):
            return self._err

    monkeypatch.setattr(bridge_main, "HotkeyListener", FakeHK)
    monkeypatch.setattr(bridge_main, "unregister_hotkey", lambda hid: None)
    monkeypatch.setattr(bridge_main.ui, "show_error", lambda *a, **k: shown.append(a))

    b = _stub_bridge()
    b.cfg = {"hotkey": "ctrl+alt+a"}
    b.hotkey_id = 1
    b._on_hotkey = lambda: None

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
