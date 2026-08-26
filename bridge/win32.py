"""AAF Bridge — Windows 本地热键 + 剪贴板（ctypes 薄封装，零第三方依赖）。"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ctypes 默认 restype=c_int（32 位），会截断 64 位句柄/指针——必须显式声明
HANDLE = wintypes.HANDLE
LPVOID = wintypes.LPVOID
BOOL = wintypes.BOOL
UINT = wintypes.UINT

user32.RegisterHotKey.restype = BOOL
user32.UnregisterHotKey.restype = BOOL
user32.OpenClipboard.restype = BOOL
user32.EmptyClipboard.restype = BOOL
user32.GetClipboardData.restype = HANDLE
user32.SetClipboardData.restype = HANDLE
user32.CloseClipboard.restype = BOOL
kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalLock.restype = LPVOID
kernel32.GlobalUnlock.restype = BOOL
kernel32.GlobalFree.restype = HANDLE

# argtypes：句柄/指针参数必须显式声明，否则默认 int 转换会溢出（64 位句柄）
HWND = wintypes.HWND
user32.RegisterHotKey.argtypes = [HWND, ctypes.c_int, UINT, UINT]
user32.UnregisterHotKey.argtypes = [HWND, ctypes.c_int]
user32.OpenClipboard.argtypes = [HWND]
user32.CloseClipboard.argtypes = []
user32.EmptyClipboard.argtypes = []
user32.GetClipboardData.argtypes = [UINT]
user32.SetClipboardData.argtypes = [UINT, HANDLE]
kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalSize.argtypes = [HANDLE]
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalFree.argtypes = [HANDLE]

WM_HOTKEY = 0x0312
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

# RegisterHotKey 所需常量（单一来源：bridge.config）
from .config import (  # noqa: E402
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
)


class HotkeyConflictError(RuntimeError):
    pass


def register_hotkey(mods: int, vk: int, hotkey_id: int = 1) -> None:
    """注册全局热键；被占用时抛 HotkeyConflictError。"""
    if not user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
        raise HotkeyConflictError(f"热键注册失败（可能被其他程序占用）: mods={mods:#x} vk={vk}")


def unregister_hotkey(hotkey_id: int = 1) -> None:
    user32.UnregisterHotKey(None, hotkey_id)


class HotkeyListener(threading.Thread):
    """独立线程跑 GetMessageW 消息循环，收到 WM_HOTKEY 时回调 on_hotkey()。

    daemon 线程；注册热键必须在该线程内完成（消息队列归属线程）。
    """

    def __init__(self, mods: int, vk: int, on_hotkey, hotkey_id: int = 1):
        super().__init__(daemon=True, name="aaf-bridge-hotkey")
        self.mods = mods
        self.vk = vk
        self.hotkey_id = hotkey_id
        self.on_hotkey = on_hotkey
        self._ready = threading.Event()
        self._error: Exception | None = None

    def run(self) -> None:
        try:
            register_hotkey(self.mods, self.vk, self.hotkey_id)
        except Exception as e:  # 注册失败（冲突）→ 记录并退出线程
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY:
                try:
                    self.on_hotkey()
                except Exception:
                    pass

    def wait_ready(self, timeout: float = 5.0) -> None:
        self._ready.wait(timeout)

    def error(self) -> Exception | None:
        return self._error


def read_clipboard_text() -> str:
    """读取系统剪贴板 Unicode 文本；空/失败返回 ''。

    使用 GlobalSize 按实际分配大小读取，避免固定长度越界或截断。
    """
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        size = kernel32.GlobalSize(handle)  # 字节数（含终止符）
        if not size or size > 4 * 1024 * 1024:  # 上限 4MB，防异常
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            data = ctypes.string_at(ptr, size)
            text = data.decode("utf-16-le", errors="ignore")
            return text.split("\x00", 1)[0]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    """写入系统剪贴板 Unicode 文本；成功返回 True。"""
    data = (text + "\x00").encode("utf-16-le")
    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
    if not hmem:
        return False
    try:
        ptr = kernel32.GlobalLock(hmem)
        if not ptr:
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(hmem)
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
                kernel32.GlobalFree(hmem)  # 失败时释放，避免泄漏
                return False
        finally:
            user32.CloseClipboard()
        return True
    finally:
        pass  # hmem 所有权已转移给系统剪贴板（SetClipboardData 成功后）
