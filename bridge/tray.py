"""AAF Bridge — Windows Tray 图标（ctypes Shell_NotifyIconW，零第三方依赖）。

Phase B 最小 Tray Skeleton（设计文档 §7 / §8 / §12.2）：
- 消息专用窗口（HWND_MESSAGE）+ Shell_NotifyIconW 图标，独立 daemon 线程
- 右键菜单最小三项：打开状态 / Bridge 信息、重启 Bridge、退出 AAF
- 双击图标 → 打开状态
- 健康显示：图标 + Tooltip 反映 Bridge / listener 健康（§8 最小模型：registered + loop alive）
- 事件通过 on_event(str) 回调：回调在 Tray 线程执行，调用方入队、主线程处理

明确不实现（Phase C-F）：完整状态窗口 / Chinese-first UI 体系 / 进度条 /
停止当前任务 / cancel 语义。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# ---------- 常量 ----------

WM_APP = 0x8000
WM_NULL = 0x0000
WM_QUIT = 0x0012
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
HWND_MESSAGE = -3

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001

TPM_RETURNCMD = 0x00000100
TPM_RIGHTBUTTON = 0x00000002

IDI_APPLICATION = 32512
IDI_WARNING = 32515

# 健康标签（UI 展示层中文；技术状态码见 bridge.main.classify_bridge_health）
HEALTH_LABELS = {"OK": "正常运行", "DEGRADED": "异常"}

# 菜单事件（入队字符串，由 Bridge 主线程分派）
EVENT_OPEN_STATUS = "tray:open_status"
EVENT_RESTART = "tray:restart"
EVENT_EXIT = "tray:exit"

# 菜单项 ID（TrackPopupMenu TPM_RETURNCMD 返回值）
MENU_ID_OPEN = 1
MENU_ID_RESTART = 2
MENU_ID_EXIT = 3

_EVENT_BY_ID = {
    MENU_ID_OPEN: EVENT_OPEN_STATUS,
    MENU_ID_RESTART: EVENT_RESTART,
    MENU_ID_EXIT: EVENT_EXIT,
}


# ---------- Win32 类型/函数声明 ----------

class NOTIFYICONDATAW(ctypes.Structure):
    """NOTIFYICONDATAW（x64 cbSize=980，由 ctypes 自然对齐计算，不硬编码）。"""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", wintypes.UINT),  # union uTimeout/uVersion
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


LRESULT = ctypes.c_ssize_t  # LONG_PTR（x64 为 64 位；wintypes 无 LRESULT）

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.CreatePopupMenu.argtypes = []
user32.AppendMenuW.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
]
user32.DestroyMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


# ---------- 纯函数（可单测） ----------


def build_tray_menu_spec(health_label: str = "正常运行", health_detail: str = "") -> list[tuple]:
    """Tray 菜单规格：[(kind, label, menu_id)]，kind ∈ {info, sep, item}。

    info = 灰显信息行（健康状态），sep = 分隔线，item = 可点菜单项。
    Phase B 最小三项：打开状态 / Bridge 信息、重启 Bridge、退出 AAF。
    """
    status_line = f"状态：{health_label}"
    if health_detail:
        status_line += f"（{health_detail}）"
    return [
        ("info", status_line, 0),
        ("sep", None, 0),
        ("item", "打开状态 / Bridge 信息", MENU_ID_OPEN),
        ("sep", None, 0),
        ("item", "重启 Bridge", MENU_ID_RESTART),
        ("item", "退出 AAF", MENU_ID_EXIT),
    ]


def menu_event_for_id(menu_id: int) -> str:
    """菜单 ID → 事件字符串（未知 ID → ''）。"""
    return _EVENT_BY_ID.get(menu_id, "")


# ---------- Tray 图标（独立线程） ----------


class TrayIcon(threading.Thread):
    """最小 Windows Tray 图标宿主（daemon 线程 + 消息专用窗口）。

    - start() 后通过 on_event(str) 接收菜单/双击事件（在 Tray 线程调用）
    - set_health(ok) 线程安全：PostMessage 到本线程窗口，由 WNDPROC 执行 NIM_MODIFY
    - stop() 删除图标并退出线程
    """

    TRAY_MSG = WM_APP + 1
    HEALTH_MSG = WM_APP + 2
    ICON_ID = 1

    def __init__(self, on_event, tooltip_prefix: str = "AAF Bridge"):
        super().__init__(daemon=True, name="aaf-bridge-tray")
        self.on_event = on_event
        self.tooltip_prefix = tooltip_prefix
        self.hwnd = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._added = False
        self._health_ok = True
        self._health_label = "正常运行"
        self._health_detail = ""
        self._wndproc = WNDPROC(self._on_wndproc)  # 保持引用，防止 GC
        self._taskbar_created = None
        self._icon_normal = None
        self._icon_warning = None

    # ---------- 线程体 ----------

    def run(self) -> None:
        try:
            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            self._icon_normal = user32.LoadIconW(None, IDI_APPLICATION)
            self._icon_warning = user32.LoadIconW(None, IDI_WARNING)
            self.hwnd = self._create_message_window()
            if not self.hwnd:
                raise RuntimeError("创建 Tray 消息窗口失败")
            self._add_icon()
            self._ready.set()
        except Exception as e:  # noqa: BLE001 —— Tray 失败不致命，Bridge 仍可运行
            self._error = e
            self._ready.set()
            return
        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._added:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)

    def wait_ready(self, timeout: float = 5.0) -> None:
        self._ready.wait(timeout)

    def error(self) -> Exception | None:
        return self._error

    # ---------- 对外接口 ----------

    def set_health(self, ok: bool, label: str, detail: str = "") -> None:
        """更新健康显示（线程安全：投递到 Tray 线程处理）。"""
        self._health_ok = bool(ok)
        self._health_label = label or ("正常运行" if ok else "异常")
        self._health_detail = detail or ""
        if self.hwnd:
            user32.PostMessageW(self.hwnd, self.HEALTH_MSG, int(self._health_ok), 0)

    def stop(self, timeout: float = 2.0) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_QUIT, 0, 0)
        self.join(timeout)

    # ---------- 内部实现 ----------

    def _create_message_window(self) -> int:
        cls_name = "AAF_Bridge_TrayWindow"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = cls_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            # 已注册（重启场景罕见）→ 忽略 ERROR_CLASS_ALREADY_EXISTS
            pass
        return user32.CreateWindowExW(
            0,
            cls_name,
            None,
            0,
            0,
            0,
            0,
            0,
            wintypes.HWND(HWND_MESSAGE),
            None,
            wc.hInstance,
            None,
        )

    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = self.ICON_ID
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.TRAY_MSG
        nid.hIcon = self._icon_normal if self._health_ok else self._icon_warning
        tip = self._tooltip()
        nid.szTip = tip[:127]
        return nid

    def _tooltip(self) -> str:
        base = f"{self.tooltip_prefix} — {self._health_label}"
        if self._health_detail:
            base += f"（{self._health_detail}）"
        return base

    def _add_icon(self) -> None:
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid())):
            self._added = True
        else:
            raise RuntimeError(f"Shell_NotifyIcon NIM_ADD 失败（error={kernel32.GetLastError()}）")

    def _apply_health(self, ok: int) -> None:
        self._health_ok = bool(ok)
        if not self._added:
            return
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid()))

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for kind, label, menu_id in build_tray_menu_spec(
                self._health_label, self._health_detail
            ):
                if kind == "sep":
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                elif kind == "info":
                    user32.AppendMenuW(menu, MF_GRAYED, 0, label)
                else:
                    user32.AppendMenuW(menu, MF_STRING, menu_id, label)
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            # 让菜单能被点击外部区域关闭
            user32.SetForegroundWindow(self.hwnd)
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            cmd = user32.TrackPopupMenu(
                menu,
                TPM_RETURNCMD | TPM_RIGHTBUTTON,
                pt.x,
                pt.y,
                0,
                self.hwnd,
                None,
            )
            event = menu_event_for_id(cmd)
            if event:
                self.on_event(event)
        finally:
            user32.DestroyMenu(menu)

    def _on_wndproc(self, hwnd, msg, wparam, lparam) -> int:
        try:
            if msg == self.TRAY_MSG:
                mouse_msg = lparam & 0xFFFF
                if mouse_msg == WM_RBUTTONUP:
                    self._show_menu()
                    return 0
                if mouse_msg == WM_LBUTTONDBLCLK:
                    self.on_event(EVENT_OPEN_STATUS)
                    return 0
            elif msg == self.HEALTH_MSG:
                self._apply_health(wparam)
                return 0
            elif self._taskbar_created and msg == self._taskbar_created:
                # Explorer 重启后重新添加图标
                if not self._added:
                    try:
                        self._add_icon()
                    except Exception:
                        pass
                else:
                    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid()))
                return 0
            elif msg == WM_QUIT:
                return 0
        except Exception:  # noqa: BLE001 —— 回调异常不得破坏消息循环
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
