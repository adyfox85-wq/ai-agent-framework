"""RW-012 FIX-001 — listener-owned hotkey lifecycle（线程所有权 + stop 契约）。

针对 Codex 确认的 lifecycle ownership defect：
- RegisterHotKey(NULL, ...) 由 listener 线程调用 → registration 归该线程所有
- 注销（UnregisterHotKey）必须发生在同一个 listener 线程内（thread-owned），
  外部线程直接注销不能可靠释放
- listener 有显式 stop 契约：request_stop() + stop(timeout)（有界 join），
  不依赖 daemon 线程自然消失

本文件用真实 HotkeyListener 线程 + mock 的 Win32 热键调用验证 ownership /
execution context semantic（记录实际执行线程身份，而非仅 mock "函数被调用过"）。
全部非 GUI / 不注册真实热键 / 不触碰用户会话。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import pytest

from bridge import win32 as win32_mod
from bridge.win32 import WM_HOTKEY, HotkeyConflictError, HotkeyListener


class RecordingHotkey:
    """记录 register/unregister 调用发生的线程身份与参数。"""

    def __init__(self, monkeypatch):
        self.reg_thread = None
        self.unreg_thread = None
        self.reg_args = None
        self.unreg_ids = []
        monkeypatch.setattr(win32_mod, "register_hotkey", self._register)
        monkeypatch.setattr(win32_mod, "unregister_hotkey", self._unregister)

    def _register(self, mods, vk, hotkey_id=1):
        self.reg_thread = threading.get_ident()
        self.reg_args = (mods, vk, hotkey_id)

    def _unregister(self, hotkey_id=1):
        self.unreg_thread = threading.get_ident()
        self.unreg_ids.append(hotkey_id)


def _fake_get_message(return_codes):
    """构造假 GetMessageW：按序返回 return_codes（0 = WM_QUIT 语义）。"""

    def fake(lp_msg, hwnd, lo, hi):
        return return_codes.pop(0) if return_codes else 0

    return fake


# ---------- A. thread-owned register + unregister ----------


def test_register_and_unregister_both_in_listener_thread(monkeypatch):
    """A：register 与 unregister 都发生在 listener 线程内（同一线程、非主线程）。

    验证 execution context semantic：注销实际由注册线程执行，而不是
    "unregister_hotkey 被调用过" 这种弱断言。
    """
    rec = RecordingHotkey(monkeypatch)
    # 消息循环立即返回 0（模拟 WM_QUIT）→ run() 退出 → finally 中线程内注销
    monkeypatch.setattr(win32_mod.user32, "GetMessageW", _fake_get_message([0]))
    calls = []
    listener = HotkeyListener(0, 0x41, lambda: calls.append(1), hotkey_id=1)
    listener.start()
    assert listener.wait_ready(3.0)
    listener.join(3.0)
    assert not listener.is_alive()

    # 注册发生在 listener 线程
    assert rec.reg_thread == listener.ident
    # 注销发生在同一个 listener 线程（thread-owned unregister）
    assert rec.unreg_thread == listener.ident
    # 两者都不发生在创建线程（测试主线程）——主线程绝不直接注销
    assert rec.reg_thread != threading.get_ident()
    assert rec.unreg_thread != threading.get_ident()
    assert rec.reg_args == (0, 0x41, 1)
    assert rec.unreg_ids == [1]
    assert calls == []  # 未投递 WM_HOTKEY → 回调不触发
    assert listener.wait_unregistered(1.0)  # 线程内注销完成标记


def test_wm_hotkey_callback_runs_in_listener_thread_then_stop(monkeypatch):
    """A'：WM_HOTKEY 回调发生在 listener 线程；随后 stop 仍在线程内注销。"""
    rec = RecordingHotkey(monkeypatch)
    cb_thread = []
    state = {"first": True}

    def fake_get_message(lp_msg, hwnd, lo, hi):
        msg = ctypes.cast(lp_msg, ctypes.POINTER(wintypes.MSG)).contents
        if state["first"]:
            state["first"] = False
            msg.message = WM_HOTKEY
            msg.wParam = 1
            return 1  # 有消息 → 回调
        return 0  # WM_QUIT → 退出循环

    monkeypatch.setattr(win32_mod.user32, "GetMessageW", fake_get_message)
    listener = HotkeyListener(0, 0x41, lambda: cb_thread.append(threading.get_ident()), hotkey_id=1)
    listener.start()
    assert listener.wait_ready(3.0)
    listener.join(3.0)
    assert not listener.is_alive()
    assert cb_thread == [listener.ident]  # 回调在 listener 线程执行
    assert rec.unreg_thread == listener.ident  # 注销也在 listener 线程


# ---------- B. stop 契约（真实消息循环 + 真实 WM_QUIT 唤醒） ----------


def test_request_stop_wakes_real_message_loop_and_unregisters_in_thread(monkeypatch):
    """B：request_stop → 真实 PostThreadMessageW WM_QUIT 唤醒真实 GetMessageW
    → 线程退出 → 线程内注销；stop(timeout) 有界返回 True。"""
    rec = RecordingHotkey(monkeypatch)
    # 不 mock GetMessageW / PostThreadMessageW：验证真实唤醒机制（无真实热键）
    listener = HotkeyListener(0, 0x41, lambda: None, hotkey_id=1)
    listener.start()
    assert listener.wait_ready(3.0)
    assert listener.is_alive()  # 阻塞在真实 GetMessageW 消息循环

    assert listener.stop(3.0) is True  # request_stop + 有界 join → 确认退出
    assert not listener.is_alive()
    assert rec.unreg_thread == listener.ident  # 注销在 listener 线程完成
    assert listener.wait_unregistered(1.0)


def test_stop_is_bounded_when_thread_wont_exit(monkeypatch):
    """D：线程卡死（不响应 stop）→ stop(timeout) 有界返回 False（不无限等待）；
    释放后线程正常退出并在线程内注销。"""
    rec = RecordingHotkey(monkeypatch)
    blocked = threading.Event()

    def never_exit(lp_msg, hwnd, lo, hi):
        blocked.wait(10)  # 模拟消息循环卡死（不消费 WM_QUIT）
        return 0

    monkeypatch.setattr(win32_mod.user32, "GetMessageW", never_exit)
    listener = HotkeyListener(0, 0x41, lambda: None, hotkey_id=1)
    listener.start()
    assert listener.wait_ready(3.0)

    t0 = time.monotonic()
    assert listener.stop(timeout=0.5) is False  # 有界：0.5s 内返回
    assert time.monotonic() - t0 < 5.0
    assert listener.is_alive()  # 线程仍在（调用方必须 fail safe）

    blocked.set()  # 释放卡死的消息循环 → 线程退出并执行线程内注销
    listener.join(3.0)
    assert not listener.is_alive()
    assert rec.unreg_thread == listener.ident


# ---------- C. 注册失败（冲突）路径 ----------


def test_registration_conflict_reports_error_no_unregister_no_leak(monkeypatch):
    """C：注册失败（热键冲突）→ error 可见、线程退出、无未释放项、无注销调用。"""
    def conflict(*a, **k):
        raise HotkeyConflictError("热键被占用")

    monkeypatch.setattr(win32_mod, "register_hotkey", conflict)
    unreg_calls = []
    monkeypatch.setattr(win32_mod, "unregister_hotkey", lambda hid: unreg_calls.append(hid))
    listener = HotkeyListener(0, 0x41, lambda: None, hotkey_id=1)
    listener.start()
    assert listener.wait_ready(3.0)
    listener.join(3.0)
    assert not listener.is_alive()
    assert isinstance(listener.error(), HotkeyConflictError)
    assert unreg_calls == []  # 注册失败 → 无可释放项（无泄漏）
    assert listener.wait_unregistered(1.0)  # 注销标记已置（trivially satisfied）


# ---------- 启动竞态 / 幂等 ----------


def test_stop_requested_before_init_never_registers(monkeypatch):
    """竞态：stop 请求早于线程初始化 → 线程不注册、干净退出。"""
    rec = RecordingHotkey(monkeypatch)
    monkeypatch.setattr(win32_mod.user32, "GetMessageW", _fake_get_message([0]))
    listener = HotkeyListener(0, 0x41, lambda: None, hotkey_id=1)
    listener.request_stop()  # start 之前请求停止
    listener.start()
    listener.join(3.0)
    assert not listener.is_alive()
    assert rec.reg_thread is None  # 从未注册
    assert rec.unreg_thread is None  # 也无需注销
    assert listener.wait_unregistered(1.0)


def test_stop_idempotent(monkeypatch):
    """幂等：重复 stop 安全（已退出线程再次 stop 立即确认）。"""
    rec = RecordingHotkey(monkeypatch)
    monkeypatch.setattr(win32_mod.user32, "GetMessageW", _fake_get_message([0]))
    listener = HotkeyListener(0, 0x41, lambda: None, hotkey_id=1)
    listener.start()
    listener.join(3.0)
    assert listener.stop(1.0) is True  # 线程已退出 → 立即确认
    assert listener.stop(1.0) is True  # 再次调用无副作用
    assert rec.unreg_thread == listener.ident
