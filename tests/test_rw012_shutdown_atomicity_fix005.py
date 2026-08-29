"""RW-012 FIX-005 — shutdown/recovery 单一 lifecycle authority（TOCTOU 收口）。

针对 Codex 确认的 FIX-004 最后一个 lifecycle blocker：

`_run_lifecycle_transition()` 在获取 `_lifecycle_lock` **前**检查 `_shutting_down`，
但获取锁后未重新确认 shutdown 状态，存在合法 check-then-wait 竞态：

    Recovery:  check False → waits for lock
    Shutdown:  sets shutdown True
    Recovery:  gets lock → 仍可能 rearm / 创建 replacement（resurrection）

FIX-005 修复（全部在同一个 `_lifecycle_lock` 单一 lifecycle authority 下）：

- shutdown intent 发布（`shutdown()` / `_exit_aaf()` / `_restart_bridge()`）
  与 listener lifecycle transition 共用同一 authority：`_shutting_down=True`
  在锁内先于 stop 发布（Requirement 2/6）
- `_run_lifecycle_transition()` 取得 authority 后在锁内重新验证 shutdown——
  等待锁期间 shutdown 已发布的 recovery 观察到 True → 不 cleanup / 不
  rearm / 不 begin_attempt / 不创建 replacement（Requirement 3/4）
- `_apply_hotkey_locked()`（唯一 listener creation authority）锁内以
  shutdown 守卫：config reload / 外部触发在 shutdown 后不创建 / 不重启
  listener（Requirement 10/12）
- `_clear_pending_ownership_locked()` 的 rearm 只在非 shutdown 时发生：
  shutdown 期间 delayed-exit cleanup 只做 ownership bookkeeping、绝不
  rearm（Requirement 9/17）

覆盖（全部非 GUI / 不注册真实热键 / 不弹 modal / 不触碰用户会话）：
1.  精确 Codex TOCTOU（真实线程 + 确定性门闩）：pre-lock check False →
    暂停在锁前 → shutdown 在 authority 下发布 → recovery 取得锁 → 锁内
    重验证 → 不 rearm / 不 begin_attempt / 不创建（Req 13）
2.  reverse interleaving：transition 持锁创建合法 listener → shutdown 等待
    authority → transition 完成 → shutdown 接管发布并安全 stop → 之后
    poll / recovery / config reload 触发无新 listener（Req 14）
3.  delayed exit during shutdown：pending old 迟延退出 → cleanup 清理但不
    rearm、epoch 不变、无 replacement（Req 15）
4.  config reload during shutdown：mtime + hotkey 变化 → 不 restart /
    不新创建（Req 16）
5.  poll during shutdown：不 recover / 不 rearm / 不创建（Req 11）；
    shutdown() 幂等
6.  shutdown() 发布顺序可观察：flag 在 stop 之前发布、stop 在 authority
    临界区内执行（Req 2/6）
7.  _exit_aaf 取消 → authority 内回滚，恢复常规运行后 recovery 仍可工作
    （Acceptance 5/18）；_exit_aaf 确认 → shutdown 保持发布
8.  _restart_bridge：authority 内发布 + stop；Popen 失败 → authority 内
    回滚并恢复热键（无 shutdown 守卫抑制）
9.  _apply_hotkey_locked 锁内 shutdown 守卫：shutdown 后直接触发不创建
10. 并发 shutdown + transition + apply + delayed cleanup 无死锁（Req 18）
11. 非 shutdown 的 config reload hotkey 变更仍正常 restart（无回归）
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


class GateFirstAcquire:
    """测试用门闩锁：第一次 acquire 确定性阻塞在 gate 上（作为 recovery
    「pre-lock check 后、取得锁前」的暂停点）；后续 acquire 直接放行到
    真实锁。entered 在第一次 acquire 进入时置位（供主线程同步）。"""

    def __init__(self, real, entered, gate):
        self._real = real
        self._entered = entered
        self._gate = gate
        self._gated = False

    def acquire(self, blocking=True, timeout=-1):
        if not self._gated:
            self._gated = True
            self._entered.set()
            if not self._gate.wait(5.0):
                raise TimeoutError("gate not released")
        return self._real.acquire(blocking, timeout)

    def release(self):
        return self._real.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def locked(self):
        return self._real.locked()


def _wait_until(predicate, timeout=3.0):
    """有界等待谓词为真（测试确定性同步辅助）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------- 1：精确 Codex TOCTOU（Req 13） ----------


def test_exact_shutdown_toctou_no_resurrection(monkeypatch):
    """Req 13 exact Codex interleaving（真实线程 + 确定性门闩）：

    Thread/Transition A:
      - 评估 pre-lock shutdown 状态 = False
      - 暂停在取得 lifecycle lock 之前（gate 阻塞）
    Shutdown B:
      - 取得 lifecycle authority，发布 _shutting_down=True，stop，释放
    A 恢复：
      - 取得 lifecycle lock → 锁内重新验证 shutdown = True

    Expected: 不 rearm / 不 begin_attempt / 不创建 HotkeyListener /
    不 start replacement（无 resurrection）。
    """
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old  # 若无修复：B 的 shutdown 清掉 old 后，A 会因
    # listener=None → DEGRADED → begin_attempt + 创建 replacement（resurrection）

    entered = threading.Event()
    gate = threading.Event()
    b._lifecycle_lock = GateFirstAcquire(threading.Lock(), entered, gate)

    errors = []

    def worker():
        try:
            b._run_lifecycle_transition()
        except Exception as e:  # noqa: BLE001 —— 测试线程收集异常
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(5.0)  # A 已完成 pre-lock 检查并暂停在锁获取前

    b.shutdown()  # B：authority 下发布 shutdown + stop 契约（old 确认退出 → 清空）

    assert b._shutting_down is True
    gate.set()  # A 恢复：取得 lifecycle lock
    t.join(5.0)
    assert not t.is_alive()
    assert not errors, f"transition 线程异常: {errors}"

    # A 锁内重新验证 → 不 rearm / 不 begin_attempt / 不创建 / 不接管
    assert created == []
    assert b._recovery.epoch == 0
    assert b._recovery.recovering is False
    assert b.listener is None  # 无 replacement 接管（shutdown 已清空 ownership）
    assert b._pending_stop is None
    assert b._lifecycle_lock.locked() is False  # 锁已释放（无泄漏）


# ---------- 2：reverse interleaving（Req 14） ----------


def test_reverse_interleaving_shutdown_takes_over_after_transition(monkeypatch):
    """Req 14 reverse ordering（真实线程）：

    Transition A 先取得 lifecycle lock 并正在完成合法 transition（安装
    exactly one replacement）；Shutdown B 等待 lock（不与 A 并发修改
    ownership）。A 完成 → B 取得 authority → 发布 shutdown → 安全 stop
    listener。B 接管后：poll / recovery / config reload 触发 → 无新
    listener creation / 无新 rearm。
    """
    created = []
    entered = threading.Event()
    release = threading.Event()

    def factory(mods, vk, on_hotkey, hotkey_id):
        entered.set()
        assert release.wait(5.0)  # 持锁阻塞：replacement 安装前暂停
        inst = ReadyListener(mods, vk, on_hotkey, hotkey_id)
        created.append(inst)
        return inst

    monkeypatch.setattr(bridge_main, "HotkeyListener", factory)
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    errors = []

    def worker():
        try:
            b._run_lifecycle_transition()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(5.0)  # A 持锁创建中

    shut_errors = []

    def shutdown_worker():
        try:
            b.shutdown()
        except Exception as e:  # noqa: BLE001 —— 测试线程收集异常
            shut_errors.append(e)

    t2 = threading.Thread(target=shutdown_worker)
    t2.start()  # B：shutdown 请求 → 等待 lifecycle authority
    assert _wait_until(lambda: t2.is_alive() and not b._shutting_down)
    assert t2.is_alive()  # B 阻塞在锁上（不与 A 并发修改 ownership）
    assert b._shutting_down is False  # B 尚未取得 authority → 未发布

    release.set()  # A 完成合法 transition（安装 replacement 后释放锁）
    t.join(5.0)
    t2.join(5.0)
    assert not t.is_alive() and not t2.is_alive()
    assert not errors and not shut_errors
    assert len(created) == 1  # A：exactly one 合法 replacement
    assert b._shutting_down is True  # B 取得 authority → 发布 shutdown
    assert b.listener is None  # B 安全 stop 了 listener（确认退出 → 引用清空）
    assert b._pending_stop is None

    # B 接管后：进一步 poll / recovery / config reload → 无 listener creation
    b._apply_hotkey()
    b._run_lifecycle_transition()
    assert b._delayed_exit_cleanup() is False
    b._cfg_mtime = 1.0
    b._config_mtime = lambda: 2.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+x"}
    )
    b._poll_config()
    assert len(created) == 1  # 无新 listener
    assert b.listener is None
    assert b._recovery.epoch == 1  # 仅 A 的 delayed-exit rearm 一次；shutdown 后无新 rearm
    assert b._recovery.recovering is False  # 无 begin_attempt


# ---------- 3：delayed exit during shutdown（Req 15） ----------


def test_delayed_exit_during_shutdown_cleanup_no_rearm_no_replacement(monkeypatch):
    """Req 15：pending old listener → shutdown 发布（stop 未确认 → ownership
    retention）→ old 稍后迟延退出 → delayed cleanup 运行。

    Expected: cleanup 可做 ownership bookkeeping（清理引用），但 epoch 不变、
    recovery 不 rearm、无 replacement / 无 begin_attempt（不复活）。
    """
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = SpontaneousExitListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b.shutdown()  # 发布 shutdown（authority 内）；stop 未确认 → pending 保留
    assert b._shutting_down is True
    assert b.listener is old and b._pending_stop is old
    assert b._recovery.epoch == 0
    assert created == []

    old._alive = False  # 迟延退出（shutdown 之后）
    assert b._delayed_exit_cleanup() is True  # 清理发生（bookkeeping）
    assert b.listener is None and b._pending_stop is None
    assert b._recovery.epoch == 0  # shutdown 中：不 rearm
    assert created == []  # 无 replacement

    # 后续 poll / transition 触发 → 锁内重验证 → 仍不复活
    b._run_lifecycle_transition()
    b._poll_health()
    assert b._recovery.epoch == 0
    assert b._recovery.recovering is False  # 无 begin_attempt
    assert created == []


# ---------- 4：config reload during shutdown（Req 16） ----------


def test_config_reload_during_shutdown_no_restart_no_creation(monkeypatch):
    """Req 16：shutdown 已发布 + config mtime / hotkey 变化并发 reload →
    不 restart listener / 不新创建（shutdown authority wins once published）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    assert len(created) == 1

    b.shutdown()  # 发布 shutdown → stop 契约（确认退出 → 引用清空）
    assert b._shutting_down is True
    assert b.listener is None

    # 配置变化（mtime + hotkey 均不同）→ reload 不得 restart / 不得新创建
    b._cfg_mtime = 1.0
    b._config_mtime = lambda: 2.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+x"}
    )
    b._poll_config()
    assert len(created) == 1
    assert b.listener is None
    assert b._shutting_down is True

    # 直接触发唯一 creation authority → 同样被 shutdown 守卫拒绝
    b._apply_hotkey()
    assert len(created) == 1
    assert b.listener is None


# ---------- 5：poll during shutdown（Req 11） ----------


def test_poll_during_shutdown_no_recover_no_rearm_no_create(monkeypatch):
    """Req 11：_poll_health / delayed-exit transition 在 shutdown 状态 →
    may observe/report，但 must not recover / rearm / create listener；
    shutdown() 幂等可安全重复调用。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b.shutdown()  # 幂等性：重复调用安全
    b.shutdown()
    b._poll_health()
    b._poll_health()
    b._run_lifecycle_transition()
    assert b._shutting_down is True
    assert created == []
    assert b._recovery.epoch == 0
    assert b._recovery.recovering is False
    assert b._lifecycle_lock.locked() is False


# ---------- 6：shutdown() 发布顺序可观察（Req 2/6） ----------


def test_shutdown_publishes_before_stop_inside_authority(monkeypatch):
    """Req 2/6：shutdown() 在 lifecycle authority 内先发布 _shutting_down=True
    再执行 stop（stop 回调内可观察 flag 已置位且锁仍由本线程持有）；
    shutdown 后任何触发不复活 listener。"""
    holder: dict = {"created": []}

    class StopFlagListener:
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
            holder["flag_at_stop"] = holder["bridge"]._shutting_down
            # 非重入锁：同一线程再次 acquire(blocking=False) 返回 False
            # ⟹ 返回 True 表示锁正被本线程持有（stop 在 authority 临界区内）
            holder["lock_held_at_stop"] = not holder["bridge"]._lifecycle_lock.acquire(
                blocking=False
            )
            self._alive = False
            return True

    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(StopFlagListener, holder["created"])
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    holder["bridge"] = b
    b._apply_hotkey()
    assert len(holder["created"]) == 1

    b.shutdown()
    assert holder["flag_at_stop"] is True  # flag 先于 stop 发布
    assert holder["lock_held_at_stop"] is True  # stop 在 authority 临界区内
    assert b.listener is None
    assert b._shutting_down is True

    b._apply_hotkey()  # shutdown 后触发 → 守卫拒绝
    b._run_lifecycle_transition()
    assert len(holder["created"]) == 1  # 无复活


# ---------- 7：_exit_aaf 确认 / 取消（Acceptance 5/18） ----------


def test_exit_aaf_cancel_restores_running_state_and_recovery(monkeypatch):
    """用户取消 Exit 确认 → shutdown intent 在 authority 内回滚（False）；
    恢复常规运行后正常非 shutdown recovery 仍可工作（Acceptance 18）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    monkeypatch.setattr(bridge_main.ui, "ask_exit_aaf", lambda root: False)
    b = _stub_bridge_with_hotkey(_stub_bridge())

    b._exit_aaf()
    assert b._shutting_down is False  # 取消 → 回滚

    # 取消后 delayed-exit recovery 正常（重新允许自恢复）
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old
    b._run_lifecycle_transition()
    assert len(created) == 1
    assert b.listener is created[0]
    assert b._recovery.epoch == 1  # 正常 rearm 一次
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK


def test_exit_aaf_confirm_keeps_shutdown_published(monkeypatch):
    """用户确认 Exit → shutdown intent 保持发布（authority 内），后续触发
    不复活 listener。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    monkeypatch.setattr(bridge_main.ui, "ask_exit_aaf", lambda root: True)
    b = _stub_bridge_with_hotkey(_stub_bridge())
    quits = []
    b.root.quit = lambda: quits.append(1)

    b._exit_aaf()
    assert b._shutting_down is True
    assert quits == [1]

    b._apply_hotkey()
    b._run_lifecycle_transition()
    assert created == []
    assert b._recovery.epoch == 0


# ---------- 8：_restart_bridge（Req 2/6，authority 内发布 + 回滚） ----------


def test_restart_bridge_publishes_shutdown_stops_listener(monkeypatch):
    """重启成功路径：shutdown intent 在 authority 内发布，listener 经 stop
    契约安全停止（无 orphan / 无 main-thread unregister）；进程立即退出。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    pops = []
    monkeypatch.setattr(
        bridge_main.subprocess, "Popen", lambda *a, **k: pops.append((a, k))
    )
    exits = []
    monkeypatch.setattr(bridge_main.os, "_exit", lambda code: exits.append(code))
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    assert len(created) == 1

    b._restart_bridge()
    assert b._shutting_down is True  # authority 内发布
    assert b.listener is None  # listener 已确认退出（ReadyListener.stop → True）
    assert b._pending_stop is None
    assert len(pops) == 1
    assert exits == [0]


def test_restart_bridge_popen_failure_rolls_back_and_restores(monkeypatch):
    """重启启动失败：shutdown intent 在 authority 内回滚（False）→ 本实例
    继续运行，_apply_hotkey 恢复热键（不被 shutdown 守卫抑制）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )

    def raising_popen(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(bridge_main.subprocess, "Popen", raising_popen)
    shown = []
    monkeypatch.setattr(
        bridge_main.ui, "show_error", lambda *a, **k: shown.append(a)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    assert len(created) == 1

    b._restart_bridge()
    assert b._shutting_down is False  # 回滚（authority 内）
    assert len(shown) == 1
    assert len(created) == 2  # 热键恢复（非 shutdown 状态 → 正常创建）
    assert b.listener is created[1]
    assert b._recovery.epoch == 0


# ---------- 9：唯一 creation authority 锁内 shutdown 守卫（Req 3/12） ----------


def test_apply_hotkey_locked_guard_during_shutdown(monkeypatch):
    """Req 3/12：_apply_hotkey_locked（唯一 listener creation authority）在
    锁内以 shutdown 守卫拒绝创建——shutdown 后直接触发也不创建。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge(shutting_down=True))

    with b._lifecycle_lock:
        b._apply_hotkey_locked(show_error=False)
    assert created == []
    assert b.listener is None

    b._apply_hotkey()  # public 入口同样被守卫
    assert created == []


# ---------- 10：并发无死锁（Req 18） ----------


def test_concurrent_shutdown_and_triggers_no_deadlock(monkeypatch):
    """Req 18：shutdown / recovery transition / config reload / delayed
    cleanup 并发（真实线程）→ 全部有界完成（无 deadlock / 无 recursive
    lock）；最终无 listener 复活（shutdown 接管后无新 recovery）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    results = []

    def t_run(name, fn):
        try:
            results.append((name, fn()))
        except Exception as e:  # noqa: BLE001
            results.append((name, f"EXC:{type(e).__name__}"))

    threads = [
        threading.Thread(target=t_run, args=("shutdown", b.shutdown)),
        threading.Thread(target=t_run, args=("transition", b._run_lifecycle_transition)),
        threading.Thread(target=t_run, args=("apply", lambda: b._apply_hotkey())),
        threading.Thread(target=t_run, args=("cleanup", b._delayed_exit_cleanup)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10.0)
    assert all(not t.is_alive() for t in threads), "死锁：并发 lifecycle 路径未在限时内完成"
    assert not [r for r in results if isinstance(r[1], str) and r[1].startswith("EXC")]

    # 无论交错顺序：shutdown 最终发布；listener 被安全 stop（无复活 / 无 orphan）
    assert b._shutting_down is True
    assert b.listener is None
    assert b._pending_stop is None
    assert b._recovery.epoch <= 1  # 只有 shutdown 前的合法 rearm 可能发生
    assert b._lifecycle_lock.locked() is False


# ---------- 11：非 shutdown 正常路径无回归 ----------


def test_config_reload_hotkey_change_normal_path_still_restarts(monkeypatch):
    """非 shutdown：config reload hotkey 变化仍正常 restart（FIX-005 守卫
    不得抑制正常生命周期行为）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    assert len(created) == 1

    b._cfg_mtime = 1.0
    b._config_mtime = lambda: 2.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+x"}
    )
    b._poll_config()
    assert len(created) == 2  # 正常 restart（stop-before-replace）
    assert b._shutting_down is False
    assert b.listener is created[1]
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK
