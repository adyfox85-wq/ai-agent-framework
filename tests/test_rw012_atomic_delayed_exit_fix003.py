"""RW-012 FIX-003 — atomic delayed-exit recovery（单一 lifecycle authority）。

针对 Codex 确认的 FIX-002 遗留两个同根 lifecycle blocker：

A. `_poll_health()` 的 delayed-exit check-and-clear 未受 _lifecycle_lock 保护：
   poll check pending old exited →（锁内另一路 _apply_hotkey 清旧建新）→
   poll 恢复后 self.listener = None → 新 listener 仍存活但 ownership reference
   丢失（TOCTOU / orphan）。FIX-003 将 check-and-clear 收进受锁保护的
   `_delayed_exit_cleanup()` 原子单元，并在锁内重新确认 identity
   （pending is old / listener is old / not alive）后才清理（Requirement 1/2/3）。

B. recovery budget exhausted（_stopped=True）后旧 listener 才迟延退出：
   FIX-002 会清理引用，但 should_attempt 因 _stopped 永久 False → Bridge 可
   永久停留在 listener=None / DEGRADED。FIX-003 引入 `HotkeyRecovery.rearm()`：
   delayed-exit ownership release 是真实 lifecycle 状态变化 → 开启一次新的
   有界 recovery epoch（epoch+1）；replacement 失败仍受 max_failures/backoff
   有界约束，不每 poll 重置、不 tight loop（Requirement 5/6/7）。

覆盖（全部非 GUI / 不注册真实热键 / 不触碰用户会话）：
- A.  delayed-exit cleanup 在 lifecycle lock 内（持锁时阻塞，锁内执行）
- B.  精确 Codex TOCTOU race（真实双线程 check/transition 交错，多轮）
- C.  identity-safe old listener clear（pending 与 listener 双身份校验）
- D.  stale cleanup 不能清掉 replacement（self.listener is B → 拒绝清空）
- E.  recovery exhausted + old 仍存活 → 无 replacement
- F.  old 在 exhaustion 后退出 → 恰好一次有界 rearm + 恢复
- G.  无 infinite rearm loop（epoch 只随真实 exit 事件增长）
- H.  delayed exit 后 exactly one replacement → healthy（Req 10 全场景）
- I.  replacement 失败仍 bounded（backoff 生效、max_failures 停止）
- J.  并发 poll + config/recovery → exactly one listener
- K.  intentional shutdown → 不 rearm / 不重启
- L.  readiness truth 回归（wait_ready=false 不 healthy 不 reset）
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
    b.tray = None
    b._last_health = None
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


class DeadListener:
    """已确认退出的 listener（is_alive False；stop 立即确认）。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = False
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
        return True


class ReadyListener:
    """正常 listener：wait_ready=True、无 error、stop 立即确认退出。"""

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
        self._alive = False
        return True


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


class FailingListener:
    """wait_ready=True + error：注册失败（热键冲突）——replacement 持续失败。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._err = RuntimeError("热键被占用")
        self._hotkey_args = (mods, vk, hotkey_id)

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


# ---------- HotkeyRecovery.rearm：recovery epoch 语义（Req 5/6/7） ----------


def test_rearm_opens_new_bounded_epoch_after_stopped():
    """F 的单元层：budget exhausted（_stopped）→ rearm 一次 → 新的有界 epoch；
    新 epoch 内再失败仍受 max_failures 约束，不会自动无限 rearm。"""
    r = bridge_main.HotkeyRecovery(max_failures=2)
    for now in (100.0, 115.0):
        assert r.should_attempt(now) is True
        r.begin_attempt()
        r.record_failure(now)
    assert r.stopped is True
    assert r.epoch == 0

    r.rearm()  # ownership release（旧 listener 确认退出）→ 一次新 epoch
    assert r.stopped is False
    assert r.consecutive_failures == 0
    assert r.epoch == 1
    assert r.should_attempt(200.0) is True

    # 新 epoch 仍有界：再失败 2 次 → 再次停止（无自动 rearm）
    r.begin_attempt()
    r.record_failure(200.0)
    r.begin_attempt()
    r.record_failure(215.0)
    assert r.stopped is True
    assert r.epoch == 1  # 没有真实 exit 事件 → 不自动 rearm
    assert r.should_attempt(9999.0) is False


def test_reset_and_success_do_not_bump_epoch():
    """rearm 语义与 reset/record_success 区分：只有真实 ownership release 产生
    新 epoch；成功 / 手动 reset 不 bump。"""
    r = bridge_main.HotkeyRecovery()
    assert r.epoch == 0
    r.begin_attempt()
    r.record_failure(100.0)
    r.record_success()
    assert r.epoch == 0  # success ≠ new epoch
    r.reset()
    assert r.epoch == 0  # manual reset ≠ new epoch
    r.rearm()
    assert r.epoch == 1


# ---------- A/C/D：delayed-exit cleanup 原子性与 identity-safety ----------


def test_delayed_exit_cleanup_blocks_on_lifecycle_lock():
    """A（Req 1/2）：check-and-clear 是锁内原子单元——锁被另一路 transition
    持有时 cleanup 阻塞在锁上（不在锁外执行 check/clear）；锁释放后在其内部
    重新确认状态：pending 已被过渡清掉 → 无操作，replacement 存活。"""
    old = DeadListener(0, 0x41, lambda: None, 1)
    b = _stub_bridge(listener=old)
    b._pending_stop = old

    assert b._lifecycle_lock.acquire(blocking=False)  # 另一路 transition 持锁
    results = []
    started = threading.Event()

    def worker():
        started.set()
        results.append(b._delayed_exit_cleanup())

    try:
        t = threading.Thread(target=worker)
        t.start()
        assert started.wait(3.0)
        time.sleep(0.05)  # 给线程时间进入 lock.acquire 阻塞
        assert t.is_alive()  # 阻塞在锁上：绝无锁外 check/clear
        # 锁内另一路完成 transition：安装 replacement B
        b.listener = replacement = ReadyListener(0, 0x41, lambda: None, 1)
        b._pending_stop = None
    finally:
        b._lifecycle_lock.release()
    t.join(3.0)
    assert not t.is_alive()
    assert results == [False]  # 锁内重验：无 pending → 无操作
    assert b.listener is replacement  # replacement 未被清掉（无 orphan）
    assert b._recovery.epoch == 0  # 无真实 delayed-exit clear → 无 rearm


def test_identity_safe_clear_requires_both_identities():
    """C（Req 2/3）：清理必须在锁内重新确认 pending 身份 + listener 身份 +
    退出状态；任一不满足 → 拒绝清理、不做任何改动。"""
    old = DeadListener(0, 0x41, lambda: None, 1)

    # pending 身份不符（pending 已变 None）→ 拒绝
    b1 = _stub_bridge(listener=old)
    b1._pending_stop = None
    assert b1._delayed_exit_cleanup() is False
    assert b1.listener is old

    # listener 身份不符（self.listener 已是 replacement B）→ 拒绝（Req 12）
    b2 = _stub_bridge()
    b2.listener = old
    b2._pending_stop = old
    b2.listener = replacement = ReadyListener(0, 0x41, lambda: None, 1)
    assert b2._delayed_exit_cleanup() is False
    assert b2.listener is replacement  # replacement 绝不被清掉
    assert b2._pending_stop is old  # 保持原样（不做任何改动）
    assert b2._recovery.epoch == 0  # 无 rearm

    # 双身份 + 退出状态全部满足 → 清理 + rearm 一次
    b3 = _stub_bridge()
    b3.listener = old
    b3._pending_stop = old
    assert b3._delayed_exit_cleanup() is True
    assert b3.listener is None and b3._pending_stop is None
    assert b3._recovery.epoch == 1
    assert b3._recovery.stopped is False


def test_stale_cleanup_cannot_clear_replacement():
    """D（Req 12 精确回归）：cleanup 路径针对 old=A 时 self.listener 已是
    replacement=B → 必须拒绝 self.listener=None（B 存活但引用不丢）。"""
    old_a = DeadListener(0, 0x41, lambda: None, 1)
    b = _stub_bridge()
    b.listener = old_a
    b._pending_stop = old_a
    # 过渡：锁内另一路 apply 清旧建新 —— A 已被替换为 B
    replacement_b = ReadyListener(0, 0x41, lambda: None, 1)
    b.listener = replacement_b
    # poll 恢复：对 stale old_a 执行 identity-safe clear → 拒绝
    assert b._clear_pending_ownership_locked(old_a) is False
    assert b.listener is replacement_b
    assert b._pending_stop is old_a
    assert b._recovery.epoch == 0
    # 同一保护经 _delayed_exit_cleanup 路径同样生效
    assert b._delayed_exit_cleanup() is False
    assert b.listener is replacement_b


# ---------- B/J：精确 Codex TOCTOU race（真实线程交错） ----------


def test_codex_toctou_race_threaded_no_orphan_no_duplicate(monkeypatch):
    """B/J（Req 11）：真实双线程复现 Codex 描述的 check/transition 交错——
    Poll A（_poll_health 的 locked delayed-exit 单元）与 Transition B
    （_apply_hotkey）在 barrier 后并发；多轮覆盖两种真实调度顺序。

    不变量（两种顺序都必须成立）：
    - replacement 必存活：恰好一个 alive listener 且它是 self.listener
    - 无 orphan：非 owner 的已创建 listener 均已被 stop 确认退出
    - 无 duplicate：任意时刻只有一个活跃 listener
    - old 引用已被正确处置（不残留为 owner）
    """
    for _ in range(40):
        created = []
        monkeypatch.setattr(
            bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
        )
        b = _stub_bridge_with_hotkey(_stub_bridge())
        old = DeadListener(0, 0x41, lambda: None, 1)
        b.listener = old
        b._pending_stop = old
        barrier = threading.Barrier(2)
        errs = []

        def poll_a():
            try:
                barrier.wait(timeout=5)
                b._poll_health()  # 真实 poll 路径：locked cleanup + 恢复判定
            except Exception as e:  # noqa: BLE001 —— 测试线程收集异常
                errs.append(e)

        t = threading.Thread(target=poll_a)
        t.start()
        barrier.wait(timeout=5)
        b._apply_hotkey()  # Transition B（config/recovery 路径）
        t.join(5.0)

        assert not errs, f"poll 线程异常: {errs}"
        assert not t.is_alive()
        # 恰好一个活跃 listener 且它就是 owner reference（无 orphan / 无 duplicate）
        alive = [lst for lst in created if lst.is_alive()]
        assert len(alive) == 1, f"活跃 listener 数 != 1: {len(alive)}"
        assert b.listener is alive[0]
        assert b.listener is not old
        assert b._pending_stop is None
        # 非 owner 的已创建 listener 均已确认退出（无 orphan daemon）
        for lst in created:
            if lst is not b.listener:
                assert not lst.is_alive()


def test_config_reload_under_lifecycle_transition_coalesces(monkeypatch):
    """J（Req 17）：health recovery 与 config reload 共用同一 lifecycle ownership
    guard——transition 进行中 config 热加载触发被合并，不创建 duplicate；锁释放
    后正常执行恰好一个 listener。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._cfg_mtime = 1.0
    b._config_mtime = lambda: 2.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+shift+k"}
    )

    assert b._lifecycle_lock.acquire(blocking=False)  # 另一路 transition 持锁
    try:
        b._poll_config()  # 并发 config 热加载 → _apply_hotkey 被合并
        assert created == []  # 无 duplicate listener
    finally:
        b._lifecycle_lock.release()
    b._apply_hotkey()  # 锁释放后的正常执行
    assert len(created) == 1  # exactly one
    assert created[0]._hotkey_args[1] == 0x4B  # 新热键 ctrl+alt+shift+k 生效


# ---------- E/F/G/H：recovery exhaustion + delayed exit ----------


def _exhaust_recovery_with_old_alive(monkeypatch, b, old):
    """驱动 poll 直到 recovery budget exhausted（old 仍存活）。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    for now in (1000.0, 1015.0, 1045.0):
        clock.t = now
        b._poll_health()
    assert b._recovery.stopped is True
    assert b.listener is old and b._pending_stop is old
    return clock


def test_recovery_exhausted_old_alive_no_replacement(monkeypatch):
    """E（Req 5/6A）：recovery budget exhausted 且旧 listener 仍存活 →
    无 duplicate replacement、无 rearm（epoch 0）、引用保留、停止可见。"""
    created = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_factory(StuckListener, created, stuck_stops=999),
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b._apply_hotkey()  # 制造 pending（stop 永远 false）
    clock = _exhaust_recovery_with_old_alive(monkeypatch, b, old)

    assert len(created) == 1  # 全程无 replacement
    assert b._recovery.epoch == 0  # old 未退出 → 无 rearm
    clock.t = 5000.0
    b._poll_health()  # 停止后 + old 仍存活 → 仍无任何动作
    assert len(created) == 1
    assert b._recovery.epoch == 0
    assert b.listener is old and b._pending_stop is old


def test_old_exits_after_exhaustion_rearms_once_and_recovers(monkeypatch):
    """F（Req 5/6B/10）：old 在 exhaustion 后最终退出 → 下一次 lifecycle 观察
    → 锁内 identity 重验证 → 清理 → 恰好一次 rearm（epoch+1）→ 一次 replacement
    尝试成功 → healthy；后续 poll 不重复 rearm。"""
    created = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_factory(SpontaneousExitListener, created),
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    assert b._stop_listener() is False  # pending
    clock = _exhaust_recovery_with_old_alive(monkeypatch, b, old)

    old._alive = False  # 旧 listener 终于迟延退出
    clock.t = 5000.0
    b._poll_health()
    assert b._recovery.epoch == 1  # 恰好一次 rearm
    assert b._pending_stop is None
    assert b._recovery.stopped is False
    assert len(created) == 2  # exactly one replacement
    assert b.listener is created[1]
    assert b.listener is not old
    assert b._recovery.consecutive_failures == 0
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK

    clock.t = 5010.0
    b._poll_health()  # 已 healthy → 无新 rearm / 无新创建
    assert b._recovery.epoch == 1
    assert len(created) == 2


def test_delayed_exit_full_scenario_exactly_one_replacement(monkeypatch):
    """H（Req 10 完整场景）：cycle1 stop 超时 → pending 保留；cycle2 budget
    耗尽时 old 仍存活 → 无 duplicate；old 最终退出 → 下一 lifecycle 观察 →
    清理 + rearm 一次 → 恰好一次 replacement → healthy。"""
    created = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_factory(StuckListener, created, stuck_stops=999),
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()  # cycle 0：初始 healthy listener
    old = b.listener
    b._apply_hotkey()  # cycle 1：stop timeout → pending（old 保留）
    assert b._pending_stop is old
    assert len(created) == 1
    clock = _exhaust_recovery_with_old_alive(monkeypatch, b, old)  # cycle 2

    old._alive = False  # later: old finally exits
    clock.t = 2000.0
    b._poll_health()  # next lifecycle observation
    assert b._recovery.epoch == 1  # re-armed once
    assert b._pending_stop is None
    assert len(created) == 2  # exactly one replacement attempted
    assert b.listener is created[1]
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK  # replacement 成功 → healthy


def test_replacement_failure_after_rearm_stays_bounded(monkeypatch):
    """I（Req 7）：rearm 后 replacement 失败仍 bounded——backoff 间隔生效、
    连续 3 次失败停止；每个 poll tick 不重置预算、不无限重试。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(FailingListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = SpontaneousExitListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old
    old._alive = False  # delayed exit → cleanup + rearm（epoch 1）+ 尝试 #1

    b._poll_health()  # t=1000：rearm + 尝试 #1 失败 → 15s backoff
    assert b._recovery.epoch == 1
    assert b._recovery.consecutive_failures == 1
    assert b._recovery._next_attempt_at == pytest.approx(1015.0)
    assert len(created) == 1

    b._poll_health()  # 未到 backoff 终点 → 不重试（无 tight loop / 无预算重置）
    assert len(created) == 1
    assert b._recovery.consecutive_failures == 1  # 预算未被每 poll 重置

    clock.t = 1015.0
    b._poll_health()  # 尝试 #2 失败 → 30s backoff
    assert b._recovery.consecutive_failures == 2
    assert b._recovery._next_attempt_at == pytest.approx(1045.0)
    clock.t = 1045.0
    b._poll_health()  # 尝试 #3 失败 → 停止
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 1  # 无新 exit 事件 → 不自动 rearm

    clock.t = 5000.0
    b._poll_health()  # 停止后无更多尝试
    assert len(created) == 3
    assert b._recovery.epoch == 1  # 无 infinite rearm loop
    assert "停止" in b._recovery.note()


def test_no_infinite_rearm_loop_across_polls(monkeypatch):
    """G（Req 5/7 精确回归）：rearm 只随真实 delayed-exit 事件发生一次；
    反复 poll 不重复 rearm（epoch 稳定）、无无限预算重置。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(FailingListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = SpontaneousExitListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old
    old._alive = False

    for now in (1000.0, 1005.0, 1010.0, 1015.0, 1020.0, 1025.0):
        clock.t = now
        b._poll_health()
    # 只有第一次 poll 触发 rearm（旧 exited）；后续 poll 无新 rearm
    assert b._recovery.epoch == 1
    assert b._recovery.consecutive_failures == 2  # backoff 门控，未无限重置
    assert len(created) == 2

    clock.t = 1045.0
    b._poll_health()  # 尝试 #3 → 停止
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 1
    clock.t = 9999.0
    b._poll_health()
    assert b._recovery.epoch == 1  # 停止后也不自动 rearm
    assert len(created) == 3


# ---------- K：intentional shutdown ----------


def test_shutdown_no_rearm_no_restart(monkeypatch):
    """K（Req 16）：intentional shutdown 期间旧 listener 迟延退出 → 不清理 /
    不 rearm / 不启动 replacement（delayed-exit cleanup 不得在 shutdown 状态
    复活 listener）；shutdown() 只走 stop 契约收尾。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge(shutting_down=True))
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b._poll_health()  # shutdown 中：跳过 cleanup / recovery
    assert b._pending_stop is old  # 不清理（不 rearm）
    assert b._recovery.epoch == 0
    assert created == []  # 不启动 replacement

    b.shutdown()  # stop 契约收尾（锁内）；old 已退出 → 引用清空
    assert b._shutting_down is True
    assert b.listener is None
    assert b._recovery.epoch == 0  # 无 rearm
    assert created == []  # 无 replacement / 无复活


def test_shutdown_stuck_listener_retains_reference_no_rearm(monkeypatch):
    """K'（Req 16 补强）：shutdown 时 listener 未确认退出 → 保留引用直到进程
    退出路径结束；不 rearm、不启动 replacement。"""
    created = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_factory(StuckListener, created, stuck_stops=999),
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    b.shutdown()
    assert b._shutting_down is True
    assert b.listener is old  # 未确认退出 → 保留引用
    assert b._pending_stop is old
    assert len(created) == 1
    assert b._recovery.epoch == 0  # 无 rearm
    assert b._recovery.consecutive_failures == 0  # 无恢复尝试


# ---------- L：readiness truth 回归 ----------


def test_readiness_truth_regression(monkeypatch):
    """L（Req 14）：readiness truth 保持——wait_ready=false 不 healthy 不 reset；
    wait_ready=true+error 不 healthy；仅 successful ready + 无 error 才 healthy
    / reset（FIX-002 语义无回归）。"""
    # wait_ready=false → 不 reset、不 healthy
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(NotReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._recovery.begin_attempt()
    b._recovery.record_failure(100.0)
    b._apply_hotkey()
    assert b._recovery.consecutive_failures == 1  # 未 reset
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED

    # wait_ready=true + error → 不 healthy
    created2 = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ErrorListener, created2)
    )
    b2 = _stub_bridge_with_hotkey(_stub_bridge())
    b2._apply_hotkey(show_error=False)
    status2, detail2 = b2._current_health()
    assert status2 == bridge_main.HEALTH_DEGRADED
    assert "注册失败" in detail2  # error 可见

    # successful ready + 无 error → healthy + reset
    created3 = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created3)
    )
    b3 = _stub_bridge_with_hotkey(_stub_bridge())
    b3._recovery.begin_attempt()
    b3._recovery.record_failure(100.0)
    b3._apply_hotkey()
    assert b3._recovery.consecutive_failures == 0  # 成功才 reset
    status3, detail3 = b3._current_health()
    assert status3 == bridge_main.HEALTH_OK
    assert "正常" in detail3
