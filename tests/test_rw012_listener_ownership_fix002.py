"""RW-012 FIX-002 — listener ownership retention + readiness truth（跨 recovery cycle）。

针对 Codex REQUEST_CHANGE 确认的最后两个同根 lifecycle blocker（FIX-001 遗留）：

A. `_stop_listener` 在 stop(timeout) 确认退出之前就执行 `self.listener = None`：
   stop 超时时旧线程仍可能存活，但 Bridge 已丢失其 reference → 下一轮
   recovery 误判无 listener → 可启动 replacement → orphan / duplicate 风险。
   FIX-002 建立跨 recovery cycle 的 one-listener ownership invariant：
   旧 listener 未确认退出前 Bridge 必须持续持有其引用（_pending_stop 标记
   degraded / recovery pending），不得启动 replacement、不得伪装 healthy。

B. `wait_ready(3.0)` 返回值被忽略：初始化 timeout 可能被误判为 healthy /
   successful start。FIX-002 强制 wait_ready 返回值参与 start success 判定，
   健康判定区分 alive / ready / error（thread alive != hotkey usable）。

覆盖（全部非 GUI / 不注册真实热键 / 不触碰用户会话）：
- Req 15：stop timeout 跨 cycle —— cycle1/2 保留引用不替换，cycle3 迟延退出后
  恰好一个 replacement
- Req 16：readiness —— wait_ready=false 不 healthy 不 reset；wait_ready=true+
  error 启动失败；wait_ready=true+无 error 才 healthy；alive 但未 ready 不 healthy
- Req 17：ownership —— stop timeout 不清引用 / confirmed stop 清引用 /
  无 orphan / 旧 listener 存活不替换 / 迟延退出单 replacement /
  并发 trigger 不 duplicate / intentional shutdown 不复活 / config reload 等旧退出
- Req 14：旧 listener 长时间无法退出 → 有界 backoff → 停止自动恢复 → 可见 warning
"""
from __future__ import annotations

import threading
import time

import pytest

from bridge import main as bridge_main


# ---------- 测试桩 ----------


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


def _stub_bridge(listener=None, recovery=None, shutting_down=False):
    """object.__new__ 构造 Bridge 桩：不触 tkinter / ctypes / 真实热键。"""
    b = object.__new__(bridge_main.Bridge)
    b.root = StubRoot()
    b._shutting_down = shutting_down
    b._recovery = recovery if recovery is not None else bridge_main.HotkeyRecovery()
    b.listener = listener
    b._pending_stop = None
    b._lifecycle_lock = threading.Lock()
    return b


def _stub_bridge_with_hotkey(b, hotkey="ctrl+alt+a"):
    b.cfg = {"hotkey": hotkey}
    b.hotkey_id = 1
    b._on_hotkey = lambda: None
    return b


def _make_factory(listener_cls, created, **cls_kwargs):
    """构造 monkeypatch 用 HotkeyListener 工厂：记录每次创建的实例。"""

    def factory(mods, vk, on_hotkey, hotkey_id):
        inst = listener_cls(mods, vk, on_hotkey, hotkey_id, **cls_kwargs)
        created.append(inst)
        return inst

    return factory


class StuckListener:
    """stop 前 stuck_stops 次返回 False（模拟线程卡死不响应 stop），
    之后返回 True（迟延退出，thread-owned unregister 已完成）。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id, stuck_stops=0):
        self._alive = True
        self.stop_calls = 0
        self.stuck_stops = stuck_stops
        self._hotkey_args = (mods, vk, hotkey_id)

    def start(self):
        pass

    def wait_ready(self, timeout):
        return True

    def is_ready(self):
        return True

    def error(self):
        return None

    def is_alive(self):
        return self._alive

    def request_stop(self):
        self.stop_calls += 1

    def stop(self, timeout=5.0):
        self.stop_calls += 1
        if self.stop_calls > self.stuck_stops:
            self._alive = False  # 迟延退出：线程已退出（unregister 已完成）
            return True
        return False


class SpontaneousExitListener:
    """stop 永远返回 False（不响应 stop）；可被外部置为自行退出（迟延退出）。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = True
        self._hotkey_args = (mods, vk, hotkey_id)

    def start(self):
        pass

    def wait_ready(self, timeout):
        return True

    def is_ready(self):
        return True

    def error(self):
        return None

    def is_alive(self):
        return self._alive

    def request_stop(self):
        pass

    def stop(self, timeout=5.0):
        return False


class ReadyListener:
    """正常 listener：wait_ready=True、无 error、stop 立即确认退出。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = True

    def start(self):
        pass

    def wait_ready(self, timeout):
        return True

    def is_ready(self):
        return True

    def error(self):
        return None

    def is_alive(self):
        return self._alive

    def request_stop(self):
        pass

    def stop(self, timeout=5.0):
        self._alive = False
        return True


class NotReadyListener:
    """wait_ready=False + 无 error：初始化超时场景（线程仍 alive 但未 ready）。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = True
        self.stop_calls = 0

    def start(self):
        pass

    def wait_ready(self, timeout):
        return False

    def is_ready(self):
        return False

    def error(self):
        return None

    def is_alive(self):
        return self._alive

    def request_stop(self):
        self.stop_calls += 1

    def stop(self, timeout=5.0):
        self.stop_calls += 1
        self._alive = False
        return True


class ErrorListener:
    """wait_ready=True + error：注册失败（如热键冲突）场景。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._err = RuntimeError("热键被占用")

    def start(self):
        pass

    def wait_ready(self, timeout):
        return True

    def is_ready(self):
        return True

    def error(self):
        return self._err

    def is_alive(self):
        return False

    def request_stop(self):
        pass

    def stop(self, timeout=5.0):
        return True


# ---------- Req 15：stop timeout 跨 recovery cycle ----------


def test_stop_timeout_cross_cycle_retains_ownership_no_replacement(monkeypatch):
    """Req 15 Cycle 1/2：old listener.stop() → false（且仍存活）→ self.listener
    仍为 old → 跨 recovery cycle 不启动 replacement。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=2)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())

    b._apply_hotkey()  # 初始启动：healthy listener
    old = b.listener
    assert len(created) == 1

    b._apply_hotkey()  # Cycle 1：stop → false（仍存活）
    assert b.listener is old  # ownership reference 保留
    assert b._pending_stop is old  # degraded / recovery pending 可观察
    assert len(created) == 1  # 无 replacement

    b._apply_hotkey()  # Cycle 2：old 仍存活 → 再次 recovery
    assert b.listener is old
    assert b._pending_stop is old
    assert len(created) == 1  # 仍无 replacement（跨 cycle invariant）
    # 未伪装 healthy：pending → DEGRADED
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED


def test_stop_timeout_cross_cycle_delayed_exit_single_replacement(monkeypatch):
    """Req 15 Cycle 3：old listener 迟延退出 → 引用清理 → exactly one replacement。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=2)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())

    b._apply_hotkey()
    old = b.listener
    b._apply_hotkey()  # cycle 1：stop → false
    b._apply_hotkey()  # cycle 2：stop → false
    assert len(created) == 1

    b._apply_hotkey()  # cycle 3：stop → true（迟延退出）→ 清引用 → 启动 replacement
    assert b._pending_stop is None  # 引用已清理
    assert len(created) == 2  # exactly one replacement
    assert b.listener is created[1]
    assert b.listener is not old
    # replacement 就绪且无 error → healthy
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_OK
    assert "正常" in detail


def test_poll_health_cross_cycle_bounded_until_old_exits(monkeypatch):
    """Req 15（recovery 门控路径）+ Req 14：旧 listener 卡死 → 有界 backoff、
    无 replacement；迟延退出后恰好一个 replacement。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=2)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b._apply_hotkey()  # 制造 pending（stop call 1 → false）

    b._poll_health()  # t=1000：recovery → stop call 2 → false → 失败 #1 → backoff 15
    assert b.listener is old and b._pending_stop is old
    assert len(created) == 1
    assert "重试" in b._recovery.note()

    b._poll_health()  # 未到 backoff 终点 → 不重试（无 tight loop）
    assert len(created) == 1

    clock.t = 1015.0
    b._poll_health()  # stop call 3 → true（迟延退出）→ 清引用 → replacement → success
    assert len(created) == 2
    assert b.listener is created[1]
    assert b._pending_stop is None
    assert b._recovery.consecutive_failures == 0  # 成功 → 归零


def test_poll_health_stuck_forever_bounded_stop_no_replacement(monkeypatch):
    """Req 14：旧 listener 长时间无法退出 → 不 tight loop、有界 backoff →
    连续 3 次失败停止自动恢复 → warning/状态可观察 → 无 duplicate listener。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=999)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b._apply_hotkey()  # 制造 pending（stop 永远 false）

    b._poll_health()  # 失败 #1 → 15s backoff
    assert len(created) == 1
    clock.t = 1015.0
    b._poll_health()  # 失败 #2 → 30s backoff
    assert len(created) == 1
    clock.t = 1045.0
    b._poll_health()  # 失败 #3 → 停止自动恢复
    assert b._recovery.stopped is True
    assert len(created) == 1  # 全程无 replacement

    clock.t = 5000.0
    b._poll_health()  # 停止后不再尝试
    assert len(created) == 1
    # 状态可观察：旧 listener 引用保留 + 停止说明
    assert b.listener is old and b._pending_stop is old
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "停止" in detail


# ---------- Req 16：readiness truth ----------


def test_wait_ready_false_not_healthy_no_recovery_reset(monkeypatch):
    """Req 16A：wait_ready=false → 启动不成功：不 reset recovery/backoff、不 healthy。"""
    created = []
    logs = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(NotReadyListener, created)
    )
    monkeypatch.setattr(bridge_main, "_log", lambda m: logs.append(m))
    b = _stub_bridge_with_hotkey(_stub_bridge())
    # 预先存在一次恢复失败（backoff 生效中）
    b._recovery.begin_attempt()
    b._recovery.record_failure(100.0)
    assert b._recovery.consecutive_failures == 1

    b._apply_hotkey()
    # 不 reset：失败计数与 backoff 终点保持不变
    assert b._recovery.consecutive_failures == 1
    assert b._recovery._next_attempt_at == pytest.approx(115.0)
    assert "第 1 次自动恢复失败" in b._recovery.note()
    assert any("未能在限时内就绪" in m for m in logs)  # 失败可观察
    # 不报告 healthy
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED


def test_wait_ready_true_with_error_startup_failure(monkeypatch):
    """Req 16B：wait_ready=true + error（注册失败）→ 启动失败：不 reset、不 healthy。"""
    created = []
    monkeypatch.setattr(bridge_main, "HotkeyListener", _make_factory(ErrorListener, created))
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._recovery.begin_attempt()
    b._recovery.record_failure(100.0)

    b._apply_hotkey(show_error=False)  # 恢复路径不弹窗；失败经状态可见
    assert b._recovery.consecutive_failures == 1  # 未 reset
    assert b._recovery._next_attempt_at == pytest.approx(115.0)
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "注册失败" in detail  # error 可见


def test_wait_ready_true_no_error_healthy_resets_recovery(monkeypatch):
    """Req 16C：wait_ready=true + 无 error → healthy + recovery/backoff reset。"""
    created = []
    monkeypatch.setattr(bridge_main, "HotkeyListener", _make_factory(ReadyListener, created))
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._recovery.begin_attempt()
    b._recovery.record_failure(100.0)
    assert b._recovery.consecutive_failures == 1

    b._apply_hotkey()
    assert b._recovery.consecutive_failures == 0  # successful ready 才允许 reset
    assert b._recovery._next_attempt_at == 0.0
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_OK
    assert "正常" in detail


def test_alive_but_not_ready_not_healthy():
    """Req 16D + Req 9：thread alive != ready/healthy（健康判定区分 alive/ready/error）。"""

    class AliveNotReady:
        def error(self):
            return None

        def is_alive(self):
            return True

        def is_ready(self):
            return False

    b = _stub_bridge(listener=AliveNotReady())
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "未就绪" in detail


# ---------- Req 17：ownership ----------


def test_confirmed_stop_clears_reference():
    """Req 17B：confirmed stop（stop() == true）→ 才允许清空 self.listener。"""
    old = StuckListener(0, 0x41, lambda: None, 1, stuck_stops=0)
    b = _stub_bridge(listener=old)
    assert b._stop_listener() is True
    assert b.listener is None
    assert b._pending_stop is None


def test_no_orphan_reference_loss_after_timeout():
    """Req 17A/C：stop timeout 不清空引用；Bridge 始终持有同一 listener 的
    reference（不存在 still-alive listener 而 Bridge 无其引用的 orphan 窗口）。"""
    old = StuckListener(0, 0x41, lambda: None, 1, stuck_stops=999)
    b = _stub_bridge(listener=old)
    assert b._stop_listener() is False
    assert b.listener is old  # ownership reference 保留
    assert b._pending_stop is old  # 同一对象可观察
    # 下一轮 recovery 继续针对同一个旧 listener
    assert b._stop_listener() is False
    assert b.listener is old and b._pending_stop is old
    # 恢复路径异常也不盲目清空仍存活的引用（orphan prevention）
    b._apply_hotkey = lambda show_error=True: (_ for _ in ()).throw(RuntimeError("unexpected"))
    assert b._try_recover_hotkey() is False
    assert b.listener is old and b._pending_stop is old


def test_delayed_spontaneous_exit_cleaned_then_single_replacement(monkeypatch):
    """Req 6 + Req 17E：旧 listener 第一次 stop timeout → 之后自己迟延退出 →
    下一轮 recovery 检测退出 → 清理引用 → 恰好一个 replacement（不永久卡死）。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(SpontaneousExitListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    assert b._stop_listener() is False  # 第一次 stop timeout
    assert b.listener is old and b._pending_stop is old

    old._alive = False  # 旧 listener 之后自行退出（不经 stop 确认）
    b._poll_health()  # 下一轮 recovery：检测退出 → 清理引用 → 启动 replacement
    assert b._pending_stop is None
    assert len(created) == 2  # exactly one replacement
    assert b.listener is created[1]
    assert b.listener is not old
    assert b._recovery.consecutive_failures == 0


def test_concurrent_triggers_with_pending_no_duplicate(monkeypatch):
    """Req 11 + Req 17F：pending 状态下并发 recovery/config reload trigger →
    单一 transition owner（_lifecycle_lock）→ 不 duplicate、不清引用。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=999)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    assert b._stop_listener() is False  # 第一个 transition：stop 超时 → pending
    assert b._pending_stop is old

    assert b._lifecycle_lock.acquire(blocking=False)  # 已有 transition owner
    try:
        b._apply_hotkey()  # 并发触发 → 被合并
    finally:
        b._lifecycle_lock.release()
    assert len(created) == 1  # 无重复 listener
    assert b.listener is old and b._pending_stop is old

    b._apply_hotkey()  # 锁释放后的下一次触发仍针对同一个旧 listener（不替换）
    assert len(created) == 1
    assert b.listener is old


def test_intentional_shutdown_stuck_listener_no_resurrection(monkeypatch):
    """Req 12 + Req 17G：shutdown 时 listener 未确认退出 → 保留引用直到进程
    退出路径结束；不触发 recovery、不启动 replacement（无 shutdown resurrection）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=999)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b.shutdown()
    assert b._shutting_down is True
    assert b.listener is old  # 未确认退出 → 保留引用
    assert b._pending_stop is old
    assert len(created) == 1  # 无 replacement
    assert b._recovery.consecutive_failures == 0  # 无恢复尝试


def test_config_reload_waits_for_old_exit(monkeypatch):
    """Req 13 + Req 17H：配置热加载时旧 listener 未退出 → 保留旧引用、新配置
    记录在案、不启动新 listener；旧 listener 确认退出后按最新配置启动 replacement。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StuckListener, created, stuck_stops=1)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b.cfg = {"hotkey": "ctrl+alt+shift+k"}  # 配置热加载：热键变化
    b._apply_hotkey()  # 旧 listener 未退出 → 不启动新 listener
    assert b.listener is old
    assert b._pending_stop is old
    assert len(created) == 1

    b._apply_hotkey()  # 旧 listener 确认退出（stop 第 2 次 → true）→ 按最新配置替换
    assert b._pending_stop is None
    assert len(created) == 2
    assert b.listener is created[1]
    assert created[1]._hotkey_args != created[0]._hotkey_args  # 新热键生效
