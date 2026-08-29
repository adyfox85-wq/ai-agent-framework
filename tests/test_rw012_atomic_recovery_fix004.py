"""RW-012 FIX-004 — atomic recovery transition consolidation（单一锁内 lifecycle transition）。

针对 Codex 确认的 FIX-003 遗留 blocker：

FIX-003 的 delayed-exit cleanup 与 replacement start 仍是多段 ownership
transition：`_poll_health` 在 lock 内做 cleanup/rearm → **释放 lock** →
lock 外判定 recovery eligibility → 再次获取 lock 创建 replacement。因此
cleanup 与 replacement start 之间存在 exposed intermediate state：
`listener=None / pending=None / recovery=rearmed` 但 transition 未
reserved/owned——可被另一 lifecycle trigger（config reload / 另一路 recovery）
利用，产生第二个 replacement 或 stale clear。

FIX-004 把 delayed-exit recovery 收敛为一个明确、可测试、单一 authority 的
lifecycle transition（`Bridge._run_lifecycle_transition`）：

    old pending 确认退出 → 锁内 identity 重验证 → clear old ownership
    → rearm 恰好一次 → eligibility 判定 → reserve attempt → exactly one
    replacement

全部在同一个 `_lifecycle_lock` 临界区内完成；`_apply_hotkey_locked` 是唯一的
listener replace/start transition owner（config reload / health recovery /
delayed cleanup / 外部入口全部汇入）。持锁状态不再调用自行获取锁的
`_apply_hotkey`（非重入锁：非阻塞获取失败 = coalesce，无死锁）。

覆盖（全部非 GUI / 不注册真实热键 / 不触碰用户会话）：
1.  单一锁内 transition：cleanup→rearm→reserve→replacement 无锁外 gap；
    rearmed 但未 owned 的中间态只在锁内存在，同线程再触发被合并
2.  精确 Codex interleaving（真实线程）：transition 持锁期间另一 config
    reload trigger + stale cleanup 并发 → 无第二 authority / 无 duplicate /
    stale 不清 replacement
3.  recovery exhausted + old 存活 → 无 replacement；old 迟延退出 → 恰好一次
    rearm / 一个 epoch；多个 poll 不再次增长（Req 8/9/15）
4.  新 epoch replacement 失败 → backoff 生效、bounded、epoch 不随 poll 自增
5.  healthy replacement 终态：引用正确 / pending=None / ready / 无 error /
    恢复成功态 / 后续 poll 不无谓 restart
6.  config reload 同 hotkey → healthy listener 不 restart（Req 18）
7.  listener=None（无 ownership release）→ 有界尝试但 epoch 不增长（Req 8）
8.  热键冲突（RegisterHotKey failure）→ 错误可观察 / bounded / 无 duplicate /
    恢复路径无 modal（Req 19，不把文案当 external conflict 证明）
9.  shutdown → transition 不 cleanup / 不 rearm / 不创建（Req 13）
10. readiness truth：wait_ready=false 不 healthy 不 reset（Req 11 回归）
11. public `_apply_hotkey` 持锁时仍 coalesce（Req 2 回归：无死锁、无第二创建）
12. transition 内 stop-before-replace + stop 失败 fail safe（Req 12）
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


class ErrorAliveListener:
    """旧 listener：alive + error（热键不可用但线程活着）→ DEGRADED；stop 确认退出。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = True
        self._err = RuntimeError("热键注册失败")
        self.stop_calls = 0
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
        return self._alive

    def request_stop(self):
        self.stop_calls += 1

    def stop(self, timeout=5.0):
        self.stop_calls += 1
        self._alive = False
        return True


class ErrorAliveStuckListener:
    """旧 listener：alive + error → DEGRADED；stop 永远 False（卡死不退出）。"""

    def __init__(self, mods, vk, on_hotkey, hotkey_id):
        self._alive = True
        self._err = RuntimeError("热键注册失败")
        self.stop_calls = 0
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
        return self._alive

    def request_stop(self):
        self.stop_calls += 1

    def stop(self, timeout=5.0):
        self.stop_calls += 1
        return False


# ---------- 1：单一锁内 transition（Req 1/2/5） ----------


def test_transition_single_lock_no_exposed_gap(monkeypatch):
    """Req 1/5：cleanup → rearm → reserve → replacement 在同一个锁内完成。

    工厂钩子（replacement 创建点）验证：锁仍由本线程持有（锁外不存在
    listener=None/pending=None/rearmed 但未 owned 的可竞争状态）；同线程
    再触发 `_apply_hotkey` → 非阻塞获取失败 → 合并（无第二 creation
    authority、无死锁）。
    """
    created = []
    observed = {}

    def factory(mods, vk, on_hotkey, hotkey_id):
        observed["lock_held"] = not b._lifecycle_lock.acquire(blocking=False)
        observed["listener_before"] = b.listener
        observed["pending_before"] = b._pending_stop
        observed["epoch"] = b._recovery.epoch
        observed["recovering"] = b._recovery.recovering
        b._apply_hotkey(show_error=False)  # 持锁内再触发 → 必须被合并（无死锁）
        inst = ReadyListener(mods, vk, on_hotkey, hotkey_id)
        created.append(inst)
        return inst

    monkeypatch.setattr(bridge_main, "HotkeyListener", factory)
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b._run_lifecycle_transition()

    assert observed["lock_held"] is True  # 锁全程持有 → 无锁外 gap
    assert observed["listener_before"] is None  # old 已 clear
    assert observed["pending_before"] is None
    assert observed["epoch"] == 1  # rearmed 恰好一次
    assert observed["recovering"] is True  # attempt 已 reserve（owned）
    assert len(created) == 1  # nested trigger 未创建第二个 replacement
    assert b.listener is created[0]  # final owner = replacement
    assert b._pending_stop is None
    assert b._recovery.epoch == 1
    assert b._lifecycle_lock.locked() is False  # 锁已释放
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK


# ---------- 2：精确 Codex interleaving（Req 14，真实线程） ----------


def test_interleaving_second_trigger_and_stale_cleanup_no_duplicate(monkeypatch):
    """Req 14 exact Codex interleaving（真实线程）：

    A. pending old 退出 → cleanup transition 开始
    B. 在 old clear 与 replacement creation 之间，另一 lifecycle trigger
       （config reload 路径）并发出现 → 不得获得独立 creation authority
    C. stale cleanup 并发出现 → 阻塞在锁上，锁内重验证后不得清掉 replacement

    最终：exactly one replacement；self.listener is replacement；stale 路径
    无法清掉它。
    """
    created = []
    entered = threading.Event()
    release = threading.Event()

    def factory(mods, vk, on_hotkey, hotkey_id):
        entered.set()
        assert release.wait(5.0)  # 持锁阻塞：replacement 尚未安装
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
        except Exception as e:  # noqa: BLE001 —— 测试线程收集异常
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(5.0)  # transition 已进入 creation（锁持有中）

    # B：另一 lifecycle trigger（config reload 路径）此刻触发 → 必须被合并
    b._apply_hotkey()
    assert created == []  # 未创建第二个 replacement（无第二 creation authority）

    # C：stale cleanup 此刻触发 → 阻塞在锁上（不锁外 check/clear）
    stale_results = []
    t2 = threading.Thread(
        target=lambda: stale_results.append(b._delayed_exit_cleanup())
    )
    t2.start()
    time.sleep(0.05)
    assert t2.is_alive()  # 阻塞在锁上

    release.set()
    t.join(5.0)
    t2.join(5.0)
    assert not t.is_alive() and not t2.is_alive()
    assert not errors, f"transition 线程异常: {errors}"
    assert len(created) == 1  # exactly one replacement
    assert b.listener is created[0]  # final owner = replacement
    assert b._pending_stop is None
    assert b._recovery.epoch == 1  # 恰好一次 rearm
    assert stale_results == [False]  # stale cleanup：锁内重验无 pending → 无操作
    assert b.listener is created[0]  # replacement 未被 stale 路径清掉
    assert b.listener.is_alive()
    assert b._lifecycle_lock.locked() is False


# ---------- 3：exhaustion → delayed exit（Req 8/9/15） ----------


def _exhaust_with_old_alive(monkeypatch, b, old):
    """驱动 poll 直到 recovery budget exhausted（old 仍存活）。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    for now in (1000.0, 1015.0, 1045.0):
        clock.t = now
        b._poll_health()
    assert b._recovery.stopped is True
    assert b.listener is old and b._pending_stop is old
    return clock


def test_exhausted_then_delayed_exit_exactly_one_rearm_one_epoch(monkeypatch):
    """Req 9/15：old pending → recovery exhausted → old 仍存活 → 无 replacement；
    old 最终退出 → 单一 transition 内恰好一次 rearm + 一个新有界 epoch +
    exactly one replacement；之后多个 poll → epoch 不再次增长。"""
    created = []
    monkeypatch.setattr(
        bridge_main,
        "HotkeyListener",
        _make_factory(SpontaneousExitListener, created),
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()
    old = b.listener
    assert b._stop_listener() is False  # pending（stop 永远 False）
    clock = _exhaust_with_old_alive(monkeypatch, b, old)

    assert len(created) == 1  # 全程无 replacement
    assert b._recovery.epoch == 0  # old 未退出 → 无 rearm

    old._alive = False  # old 终于迟延退出（真实 ownership release 事件）
    clock.t = 5000.0
    b._poll_health()  # 单一 transition：cleanup + rearm + reserve + replacement
    assert b._recovery.epoch == 1  # exactly one rearm
    assert b._pending_stop is None
    assert b._recovery.stopped is False  # 新的有界 recovery opportunity
    assert b._recovery.consecutive_failures == 0
    assert len(created) == 2  # exactly one replacement
    assert b.listener is created[1]
    assert b.listener is not old
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK

    # 多个 poll：epoch 不再次增长、无第二个 replacement、不无谓 restart
    for now in (5005.0, 5010.0, 5015.0, 5020.0, 5025.0, 5030.0, 5040.0, 5050.0, 5060.0, 5070.0):
        clock.t = now
        b._poll_health()
    assert b._recovery.epoch == 1
    assert len(created) == 2


# ---------- 4：failed new epoch bounded（Req 16） ----------


def test_failed_new_epoch_bounded_no_epoch_growth(monkeypatch):
    """Req 16：delayed-exit 后新 replacement 失败 → 正常失败计数增长、
    backoff 生效、retry bounded、epoch 不因 polling 自增、达上限停止。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(FailingListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b._poll_health()  # t=1000：rearm(epoch 1) + attempt #1 失败 → 15s backoff
    assert b._recovery.epoch == 1
    assert b._recovery.consecutive_failures == 1
    assert b._recovery._next_attempt_at == pytest.approx(1015.0)
    assert len(created) == 1

    b._poll_health()  # 未到 backoff 终点 → 不重试（无 tight loop / 预算不重置）
    assert len(created) == 1
    assert b._recovery.consecutive_failures == 1
    assert b._recovery.epoch == 1

    clock.t = 1015.0
    b._poll_health()  # attempt #2 失败 → 30s backoff
    assert b._recovery.consecutive_failures == 2
    assert b._recovery._next_attempt_at == pytest.approx(1045.0)
    assert b._recovery.epoch == 1

    clock.t = 1045.0
    b._poll_health()  # attempt #3 失败 → 停止自动恢复
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 1  # 无新 exit 事件 → 不自动 rearm

    clock.t = 9999.0
    b._poll_health()  # 停止后无更多尝试
    assert len(created) == 3
    assert b._recovery.epoch == 1  # 无 infinite epoch 重建
    assert "停止" in b._recovery.note()


# ---------- 5：healthy replacement 终态（Req 17/18） ----------


def test_healthy_replacement_state_no_further_restart(monkeypatch):
    """Req 17：replacement 成功 → listener reference 正确 / pending=None /
    ready=true / error=None / recovery success 态；后续 poll 不无谓 restart。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = SpontaneousExitListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old
    old._alive = False  # delayed exit

    b._poll_health()
    assert len(created) == 1
    replacement = b.listener
    assert replacement is created[0]
    assert replacement is not old
    assert b._pending_stop is None
    assert replacement.is_ready() is True
    assert replacement.error() is None
    assert replacement.is_alive() is True
    assert b._recovery.consecutive_failures == 0
    assert b._recovery.stopped is False
    assert b._recovery.epoch == 1
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_OK
    assert "正常" in detail

    b._poll_health()  # healthy → 不无谓 restart
    b._poll_health()
    assert len(created) == 1
    assert b.listener is replacement


def test_config_reload_same_hotkey_no_restart(monkeypatch):
    """Req 18：healthy listener 已存在且配置无需变更 → config reload / health
    recovery 均不 restart（不 stop/start 健康 listener）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    b._apply_hotkey()  # 初始 healthy listener
    assert len(created) == 1

    apply_calls = []
    b._apply_hotkey = lambda show_error=True: apply_calls.append(1)
    b._cfg_mtime = 1.0
    b._config_mtime = lambda: 2.0
    monkeypatch.setattr(
        bridge_main.cfg_mod, "load_config", lambda: {"hotkey": "ctrl+alt+a"}
    )
    b._poll_config()  # mtime 变化但 hotkey 相同 → 不 restart
    assert apply_calls == []
    assert len(created) == 1

    b._poll_health()  # healthy → transition 无动作
    assert len(created) == 1
    assert b.listener.is_alive()


# ---------- 6：listener=None 不 rearm（Req 8） ----------


def test_listener_none_bounded_attempts_epoch_does_not_grow(monkeypatch):
    """Req 8：listener=None（无 ownership release 事件）→ 正常有界重试
    （每次尝试恰好一个 listener，无 duplicate），但 epoch 不增长——rearm
    只随真实 delayed-exit ownership release 发生，不因 None/DEGRADED/poll
    自动反复。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(FailingListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())  # listener=None, pending=None

    for now in (1000.0, 1015.0, 1045.0):
        clock.t = now
        b._poll_health()
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 0  # 无 rearm（无真实 exit 事件）
    assert len(created) == 3  # 有界尝试

    clock.t = 9999.0
    b._poll_health()
    assert len(created) == 3  # 停止后无更多尝试
    assert b._recovery.epoch == 0  # 无 infinite rearm loop


# ---------- 7：热键冲突行为（Req 19） ----------


def test_conflict_error_observable_bounded_no_duplicate_no_modal(monkeypatch):
    """Req 19：RegisterHotKey failure（error listener）→ 错误/降级可观察、
    有界 recovery、每次尝试恰好一个 listener（无 duplicate / 无 orphan）、
    恢复路径不弹 modal。不把「可能被其他程序占用」文案当作 external conflict
    的证明——断言基于 error 对象/状态。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ErrorListener, created)
    )
    shown = []
    monkeypatch.setattr(bridge_main.ui, "show_error", lambda *a, **k: shown.append(a))
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old  # delayed exit → rearm 后 replacement 持续冲突

    b._poll_health()  # t=1000：rearm + attempt #1 → 冲突（恢复路径）
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "注册失败" in detail  # error 可观察（基于 error 对象状态，非文案证明）
    assert shown == []  # 恢复路径不弹 modal（无 dialog 轰炸）

    clock.t = 1015.0
    b._poll_health()  # attempt #2
    clock.t = 1045.0
    b._poll_health()  # attempt #3 → 停止自动恢复
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 1  # 无新 exit 事件 → 不自动 rearm
    assert len(created) == 3  # 每次尝试恰好一个（无 duplicate / 无 orphan）
    assert shown == []  # 全程无 modal

    clock.t = 9999.0
    b._poll_health()  # 停止后无 tight loop
    assert len(created) == 3


# ---------- 8：shutdown（Req 13） ----------


def test_shutdown_transition_no_cleanup_no_rearm_no_create(monkeypatch):
    """Req 13：_shutting_down=true → transition 不 cleanup / 不 rearm /
    不启动 replacement（退出不复活）。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge(shutting_down=True))
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b._run_lifecycle_transition()
    assert b._pending_stop is old  # 不清理
    assert b.listener is old
    assert b._recovery.epoch == 0  # 不 rearm
    assert created == []  # 不创建 replacement

    b._poll_health()  # poll 路径同样跳过
    assert created == []
    assert b._recovery.epoch == 0


# ---------- 9：readiness truth（Req 11 回归） ----------


def test_readiness_truth_via_transition(monkeypatch):
    """Req 11：wait_ready=false（初始化超时）→ 不 healthy、不 reset recovery；
    经 transition 的失败计数正常有界增长；epoch 不随 poll 自增。"""
    clock = _Clock(start=1000.0)
    monkeypatch.setattr(bridge_main.time, "monotonic", clock.monotonic)
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(NotReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = DeadListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = old

    b._poll_health()  # attempt #1：wait_ready=False → 不 healthy 不 reset
    assert b._recovery.consecutive_failures == 1
    assert b._recovery.epoch == 1  # delayed-exit rearm 一次（旧 exit 是真实事件）
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert len(created) == 1

    clock.t = 1015.0
    b._poll_health()  # attempt #2
    clock.t = 1045.0
    b._poll_health()  # attempt #3 → 停止
    assert b._recovery.stopped is True
    assert b._recovery.epoch == 1  # 无新 exit → 不自动 rearm
    assert len(created) == 3


# ---------- 10：public _apply_hotkey 持锁时 coalesce（Req 2 回归） ----------


def test_apply_hotkey_public_coalesces_while_lock_held(monkeypatch):
    """Req 2：public `_apply_hotkey` 在锁被另一路 transition 持有时被合并
    （非阻塞获取失败，无死锁）；锁释放后的下一次触发正常创建 exactly one。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())

    assert b._lifecycle_lock.acquire(blocking=False)
    try:
        b._apply_hotkey()
        assert created == []
    finally:
        b._lifecycle_lock.release()
    b._apply_hotkey()
    assert len(created) == 1


# ---------- 11：transition 内 stop-before-replace（Req 12） ----------


def test_stop_before_replace_inside_transition(monkeypatch):
    """Req 12：transition 内替换已退化（alive + error）的旧 listener 时先
    stop 并确认退出 → 才创建 replacement；旧 listener 无 orphan。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = ErrorAliveListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = None

    b._run_lifecycle_transition()
    assert old.stop_calls == 1  # 先 stop
    assert old.is_alive() is False  # 确认退出（无 orphan）
    assert len(created) == 1  # exactly one replacement
    assert b.listener is created[0]
    assert b.listener is not old
    assert b._recovery.epoch == 0  # 非 pending-exit 场景 → 无 rearm
    assert b._recovery.consecutive_failures == 0
    status, _ = b._current_health()
    assert status == bridge_main.HEALTH_OK


def test_stop_fail_safe_inside_transition_no_replacement(monkeypatch):
    """Req 12/9：transition 内旧 listener（alive + error）stop 未确认退出 →
    fail safe：不创建 replacement、保留 ownership reference（pending）、
    DEGRADED 可观察、失败计数有界。"""
    created = []
    monkeypatch.setattr(
        bridge_main, "HotkeyListener", _make_factory(ReadyListener, created)
    )
    b = _stub_bridge_with_hotkey(_stub_bridge())
    old = ErrorAliveStuckListener(0, 0x41, lambda: None, 1)
    b.listener = old
    b._pending_stop = None

    b._run_lifecycle_transition()
    assert created == []  # fail safe：无 replacement
    assert b.listener is old  # ownership retention（不 orphan）
    assert b._pending_stop is old
    assert b._recovery.consecutive_failures == 1
    assert b._recovery.epoch == 0  # 无 delayed-exit 事件 → 无 rearm
    status, detail = b._current_health()
    assert status == bridge_main.HEALTH_DEGRADED
    assert "未确认退出" in detail  # pending 状态可观察
