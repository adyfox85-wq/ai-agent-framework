"""AAF Bridge — 最小入口（Phase B：无控制台后台宿主 + Tray Skeleton）。

流程：热键触发 → 读剪贴板 → 解析/校验 TASK → 确认窗口 → 落盘 .aaf/tasks/active/<Task-ID>.md → 提示。

运行：
- 后台方式（推荐）：scripts/start_bridge.pyw（pythonw，无控制台，Tray 管理）
- 调试方式：python -m bridge.main（保留控制台输出）
（Windows；零第三方依赖：ctypes RegisterHotKey / Shell_NotifyIconW + tkinter UI）

Phase B 范围：
- 无控制台后台常驻（pythonw / .pyw）
- Tray 最小菜单：打开状态窗口 / 重启 Bridge / 退出 AAF
- 最小 health 判定（listener registered + loop alive，§8）
- Restart = 旧实例退出 + 新实例接管（单实例 mutex 保证不双开）
- Exit = 只退出宿主，不写 task.json / run.json，无 cancel 语义
Phase C 范围：
- 正式状态窗口（bridge/status_window.py：只读观察 + 中文优先 + 单例复用/聚焦）
- 现有弹窗文案中文化（不改逻辑 / 解析 / 生命周期）
不实现：进度 / Stop Task / Safe Cancel（Phase D-F）。
"""
from __future__ import annotations

import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from . import config as cfg_mod
from . import duplicate as dup_mod
from . import handoff
from . import intake
from . import task_io
from . import tray as tray_mod
from . import ui
from ai_agent_framework import cancel as cancel_mod
from .launcher import (
    AlreadyRunningError,
    FrameworkLauncher,
    RESULT_FAILED,
    RESULT_FAILED_TO_START,
    RESULT_FINISHED,
    RESULT_REPORT_NOT_FOUND,
    RUNNING,
)
from .status_window import StatusWindowController, collect_status, overall_status_label
from .win32 import HotkeyConflictError, HotkeyListener, unregister_hotkey

CONFIG_CHECK_INTERVAL = 2.0  # 秒：热键触发时检查配置变化（无需重启 Bridge）
CONFIG_RELOAD_INTERVAL = 2.0  # 秒：后台轮询配置 mtime
HEALTH_POLL_INTERVAL = 5.0  # 秒：health 轮询 → Tray 图标/Tooltip

# RW-012：hotkey listener 自恢复（有界 backoff；唯一 owner = Bridge 实例）
RECOVERY_MAX_FAILURES = 3  # 连续恢复失败上限 → 停止自动恢复（不 tight loop）
RECOVERY_BACKOFF_SECONDS = (15.0, 30.0, 60.0)  # 第 1/2/3 次失败后的等待秒数

# 单实例 mutex（Restart 交接 / 防双开）
_SINGLE_INSTANCE_MUTEX = "Local\\AAF_Bridge_SingleInstance_v0_4"
_RESTART_RETRIES = 10  # 重启时旧实例退出后新实例获取 mutex 的重试次数
_RESTART_RETRY_DELAY = 1.0  # 秒

HEALTH_OK = "OK"
HEALTH_DEGRADED = "DEGRADED"
_HEALTH_LABELS = {HEALTH_OK: "正常运行", HEALTH_DEGRADED: "异常"}

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102

kernel32 = ctypes.windll.kernel32
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _log(msg: str) -> None:
    """pythonw 下 sys.stdout 为 None，print 会崩溃 → 统一安全输出。"""
    if sys.stdout is not None:
        try:
            print(msg, flush=True)
        except Exception:
            pass


class SingleInstance:
    """Windows 命名 mutex 单实例保护（ctypes，零第三方依赖）。

    - 创建即持有（bInitialOwner=True）：持有 = 本实例存活标记
    - 二次启动：CreateMutexW 得 ERROR_ALREADY_EXISTS + WaitForSingleObject(0)
      → WAIT_TIMEOUT = 另一实例存活 → 返回 False（调用方退出）
    - 重启交接：旧实例退出（进程终止）→ mutex 变为 abandoned →
      新实例 WaitForSingleObject 返回 WAIT_ABANDONED → 取得所有权继续
    - 不实现任何 Phase E 内容（无 launch registry / ownership verification）
    """

    def __init__(self, name: str = _SINGLE_INSTANCE_MUTEX, retries: int = _RESTART_RETRIES, delay: float = _RESTART_RETRY_DELAY):
        self.name = name
        self.retries = max(1, retries)
        self.delay = max(0.0, delay)
        self._handle = None

    def acquire(self) -> bool:
        """尝试获取单实例所有权；已存在存活实例时返回 False。"""
        for attempt in range(self.retries):
            handle = kernel32.CreateMutexW(None, True, self.name)
            if not handle:
                return False
            last_err = kernel32.GetLastError()
            if last_err != ERROR_ALREADY_EXISTS:
                # 新建（或已 abandoned 但本次创建成功）→ 拥有所有权
                self._handle = handle
                return True
            # 对象已存在：判断是否被存活实例持有
            wait = kernel32.WaitForSingleObject(handle, 0)
            if wait == WAIT_TIMEOUT:
                # 另一实例存活
                kernel32.CloseHandle(handle)
                if attempt + 1 < self.retries:
                    time.sleep(self.delay)
                    continue
                return False
            # WAIT_OBJECT_0 / WAIT_ABANDONED → 已取得所有权（abandoned = 旧实例刚退出）
            self._handle = handle
            return True
        return False

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self):
        self.release()


def classify_bridge_health(listener) -> tuple[str, str]:
    """最小 health 判定（设计 §8.2，Phase B 范围）：(status, detail)。

    - OK：listener 已注册且消息循环线程存活
    - DEGRADED：未注册 / 注册失败（冲突）/ 线程已退出
    不实现 heartbeat / self-healing / RW-020（Phase B 明确排除）。
    """
    if listener is None:
        return HEALTH_DEGRADED, "热键未注册"
    err = listener.error()
    if err is not None:
        return HEALTH_DEGRADED, f"热键注册失败: {err}"
    if not listener.is_alive():
        return HEALTH_DEGRADED, "热键监听线程已退出"
    return HEALTH_OK, "正常运行"


class HotkeyRecovery:
    """RW-012：hotkey listener 自恢复策略（纯逻辑，可单测）。

    - 唯一 lifecycle owner：Bridge 实例——本策略只回答「何时允许尝试恢复」，
      实际恢复动作（重建 listener）由 Bridge._try_recover_hotkey 执行；
      不允许其他组件各自重启 listener。
    - 有界：连续失败 >= max_failures 后停止自动恢复（不 tight loop）
    - backoff：失败后按递增间隔再尝试（默认 15s / 30s / 60s）
    - 合并：恢复进行中（begin_attempt 后）重复触发被拒绝 → 不会产生多个 listener
    - 主动退出：shutting_down=True 时任何尝试都被拒绝（退出期间不复活）
    """

    def __init__(
        self,
        max_failures: int = RECOVERY_MAX_FAILURES,
        backoff: tuple[float, ...] = RECOVERY_BACKOFF_SECONDS,
    ):
        self.max_failures = max(1, int(max_failures))
        self.backoff = tuple(max(0.0, float(b)) for b in backoff)
        self.consecutive_failures = 0
        self._next_attempt_at = 0.0
        self._recovering = False
        self._stopped = False

    # ---------- 只读状态 ----------

    @property
    def stopped(self) -> bool:
        """连续失败已达上限 → 自动恢复已停止（失败仍可见，不再重试）。"""
        return self._stopped

    @property
    def recovering(self) -> bool:
        """一次恢复正在进行（用于合并重复触发）。"""
        return self._recovering

    # ---------- 状态转换 ----------

    def reset(self) -> None:
        """热键成功应用（启动 / 配置热键变更 / 恢复成功）→ 允许重新自恢复。"""
        self.consecutive_failures = 0
        self._next_attempt_at = 0.0
        self._recovering = False
        self._stopped = False

    def should_attempt(self, now: float, shutting_down: bool = False) -> bool:
        """是否允许发起一次恢复尝试（四重门：主动退出 / 已停止 / 恢复中 / backoff）。"""
        if shutting_down or self._stopped or self._recovering:
            return False
        return now >= self._next_attempt_at

    def begin_attempt(self) -> None:
        """标记恢复进行中；后续触发 coalesce（不重复发起）。"""
        self._recovering = True

    def record_success(self) -> None:
        """恢复成功：清零失败计数，解除进行中标记。"""
        self.consecutive_failures = 0
        self._next_attempt_at = 0.0
        self._recovering = False

    def record_failure(self, now: float) -> None:
        """记录一次失败；达到上限 → 停止自动恢复（有界）。"""
        self.consecutive_failures += 1
        self._recovering = False
        if self.consecutive_failures >= self.max_failures:
            self._stopped = True
            return
        idx = min(self.consecutive_failures - 1, len(self.backoff) - 1)
        self._next_attempt_at = now + self.backoff[idx]

    def note(self) -> str:
        """面向用户的可观察说明（失败必须可见：状态窗口 / Tray Tooltip / 日志）。"""
        if self._recovering:
            return "正在自动恢复热键…"
        if self._stopped:
            return (
                f"自动恢复已停止（连续 {self.max_failures} 次失败），"
                "请检查热键占用或重启 Bridge"
            )
        if self.consecutive_failures > 0:
            idx = min(self.consecutive_failures - 1, len(self.backoff) - 1)
            wait = int(self.backoff[idx])
            return f"第 {self.consecutive_failures} 次自动恢复失败，{wait} 秒后重试"
        return ""


def build_restart_argv() -> list[str]:
    """构造重启命令：pythonw + scripts/start_bridge.pyw（无控制台）。

    无 pythonw 时回退 sys.executable（Popen 侧用 CREATE_NO_WINDOW 抑制控制台）。
    """
    repo_root = Path(__file__).resolve().parent.parent
    start_script = repo_root / "scripts" / "start_bridge.pyw"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        return [str(pythonw), str(start_script)]
    return [sys.executable, str(start_script)]


def build_status_rows(cfg: dict, health: tuple[str, str], last) -> list[tuple[str, str]]:
    """最小状态窗口内容（Phase C 预留接入点）。rows = [(label, value)]。"""
    status_code, detail = health
    label = _HEALTH_LABELS.get(status_code, status_code)
    detail_text = f"（{detail}）" if detail and detail != label else ""
    hotkey = cfg.get("hotkey", "ctrl+alt+a")
    parsed = cfg_mod.parse_hotkey(hotkey)
    desc = cfg_mod.describe_hotkey(*parsed) if parsed else repr(hotkey)
    last_line = "（无）" if last is None else f"{last.task_id} — {last.result}"
    return [
        ("Bridge 状态", f"{label}{detail_text}"),
        ("热键", desc),
        ("当前项目", str(cfg.get("current_project") or "（未设置）")),
        ("当前 Workspace", str(cfg.get("current_workspace") or "（未设置）")),
        ("最近 Task", last_line),
    ]


class Bridge:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = cfg_mod.load_config()
        self.hotkey_id = 1
        self.listener: HotkeyListener | None = None
        self.events: queue.Queue = queue.Queue()
        self.busy = False  # 防抖：一次只处理一个热键
        self.launcher = FrameworkLauncher(on_finished=self._on_framework_finished)
        # Phase E / TASK-005-B（§6B.13）：restart 后重新认证既有 launch 的 ownership
        # （registry + control + live process 三方验证；只读恢复 force capability，
        # 不自动 force kill、不改写 canonical；launcher_instance_id 不要求相同）。
        # 失败 / 无 launch：无副作用，不影响 Bridge 正常启动。
        try:
            self.launcher.recover_launches()
        except Exception:  # noqa: BLE001 —— restart 恢复失败不阻断 Bridge 启动
            pass
        self.tray: tray_mod.TrayIcon | None = None
        # Phase C：正式状态窗口控制器（单例：复用/聚焦；关闭不退出 Bridge）
        self.status_ctl = StatusWindowController(
            root,
            provider=lambda: collect_status(
                self.cfg, self._current_health(), self.launcher
            ),
            on_restart=self._restart_bridge,
            on_exit=self._exit_aaf,
            on_close=None,
            # Phase E / TASK-005-C：Stop / Force 动作接线（只发请求；不直接 kill /
            # 不写 canonical terminal——req 7）
            on_stop_request=self._request_stop,
            on_force_request=self._request_force_stop,
        )
        self._last_health: str | None = None
        self._cfg_mtime = self._config_mtime()
        # RW-012：listener 自恢复策略 + 主动退出标志（生命周期 owner = 本 Bridge 实例）
        self._recovery = HotkeyRecovery()
        self._shutting_down = False
        self._apply_hotkey()
        self._start_tray()
        self.root.after(100, self._poll_events)
        self.root.after(int(CONFIG_RELOAD_INTERVAL * 1000), self._poll_config)
        self.root.after(int(HEALTH_POLL_INTERVAL * 1000), self._poll_health)

    # ---------- 热键 ----------

    def _config_mtime(self) -> float:
        try:
            return cfg_mod.CONFIG_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def _apply_hotkey(self, show_error: bool = True) -> None:
        parsed = cfg_mod.parse_hotkey(self.cfg.get("hotkey", "ctrl+alt+a"))
        if parsed is None:
            if show_error:
                ui.show_error("AAF Bridge", f"热键配置无效: {self.cfg.get('hotkey')!r}（示例: ctrl+alt+a）")
            return
        mods, vk = parsed
        # 先注销旧热键，避免热加载后旧热键残留（改回原热键时冲突）
        if self.listener is not None:
            try:
                unregister_hotkey(self.hotkey_id)
            except Exception:
                pass
            self.listener = None  # 旧 daemon 线程进入 GetMessageW 等待，热键已注销不再触发
        self.listener = HotkeyListener(mods, vk, self._on_hotkey, self.hotkey_id)
        self.listener.start()
        self.listener.wait_ready(3.0)
        err = self.listener.error()
        if err is not None:
            if show_error:
                ui.show_error(
                    "AAF Bridge — 热键冲突",
                    f"{err}\n请在 ~/.aaf-bridge/config.json 修改 hotkey 后等待配置热加载。",
                )
            return
        # RW-012：成功应用（启动 / 热键变更 / 自动恢复）→ 恢复策略归零（允许重新自恢复）
        self._recovery.reset()

    def _current_health(self) -> tuple[str, str]:
        """健康判定 + 恢复状态说明（供 Tray / 状态窗口观察；失败必须可见）。"""
        status, detail = classify_bridge_health(self.listener)
        note = self._recovery.note()
        if note and status == HEALTH_DEGRADED:
            detail = f"{detail}；{note}" if detail else note
        return status, detail

    def _try_recover_hotkey(self) -> bool:
        """RW-012：仅重建 listener（不重启 Bridge）；失败不弹窗（状态可见即可）。"""
        try:
            self._apply_hotkey(show_error=False)
        except Exception:
            self.listener = None
            return False
        status, _ = classify_bridge_health(self.listener)
        return status == HEALTH_OK

    def _poll_config(self) -> None:
        try:
            mtime = self._config_mtime()
            if mtime != self._cfg_mtime:
                self._cfg_mtime = mtime
                new_cfg = cfg_mod.load_config()
                if new_cfg.get("hotkey") != self.cfg.get("hotkey"):
                    self.cfg = new_cfg
                    self._apply_hotkey()  # 热键变化 → 无需重启
                else:
                    self.cfg = new_cfg
        except Exception:
            pass
        self.root.after(int(CONFIG_RELOAD_INTERVAL * 1000), self._poll_config)

    # ---------- Tray / 生命周期（Phase B） ----------

    def _start_tray(self) -> None:
        """启动 Tray 图标；失败不致命（热键仍可用），仅提示一次。"""
        try:
            tray = tray_mod.TrayIcon(on_event=self.events.put)
            tray.start()
            tray.wait_ready(3.0)
            err = tray.error()
            if err is not None:
                self.tray = None
                ui.show_error(
                    "AAF Bridge — Tray 启动失败",
                    f"{err}\n热键功能不受影响；可用 [重启 Bridge]（调试模式 Ctrl+C 退出后重新启动）恢复。",
                )
                return
            self.tray = tray
            self._apply_health_to_tray()
        except Exception as e:  # noqa: BLE001
            self.tray = None
            ui.show_error("AAF Bridge — Tray 启动失败", f"{e}\n热键功能不受影响。")

    def _apply_health_to_tray(self) -> None:
        if self.tray is None:
            return
        status, detail = self._current_health()
        self._last_health = status
        self.tray.set_health(status == HEALTH_OK, _HEALTH_LABELS.get(status, status), detail)

    def _poll_health(self) -> None:
        """每 5s 健康轮询：DEGRADED → RW-012 有界自恢复（只重建 listener，不重启 Bridge）。

        - 主动退出（shutting_down）期间不触发恢复（退出不复活）
        - 恢复进行中/已停止/backoff 期内重复触发被策略拒绝（无重复 listener / 无 tight loop）
        - 失败保持在 Tray 图标 / Tooltip / 状态窗口可见（note 并入 detail）
        """
        try:
            if not self._shutting_down:
                status, detail = classify_bridge_health(self.listener)
                if status == HEALTH_DEGRADED:
                    if self._recovery.should_attempt(time.monotonic()):
                        self._recovery.begin_attempt()
                        try:
                            recovered = self._try_recover_hotkey()
                        except Exception:
                            recovered = False
                        if recovered:
                            self._recovery.record_success()
                            _log("AAF Bridge: hotkey listener 自动恢复成功。")
                        else:
                            self._recovery.record_failure(time.monotonic())
                            _log(
                                "AAF Bridge: hotkey listener 自动恢复失败"
                                f"（第 {self._recovery.consecutive_failures} 次）。"
                                f"{self._recovery.note()}"
                            )
                        status, detail = classify_bridge_health(self.listener)
                    note = self._recovery.note()
                    if note:
                        detail = f"{detail}；{note}" if detail else note
                self._last_health = status
                if self.tray is not None:
                    self.tray.set_health(
                        status == HEALTH_OK, _HEALTH_LABELS.get(status, status), detail
                    )
        except Exception:
            pass
        self.root.after(int(HEALTH_POLL_INTERVAL * 1000), self._poll_health)

    def _on_tray_event(self, event: str) -> None:
        """Tray 事件分派（主线程）。"""
        if event == tray_mod.EVENT_OPEN_STATUS:
            self._open_status_window()
        elif event == tray_mod.EVENT_RESTART:
            self._restart_bridge()
        elif event == tray_mod.EVENT_EXIT:
            self._exit_aaf()

    def _open_status_window(self) -> None:
        """打开正式状态窗口（Phase C）。

        单例：已存在窗口则复用并聚焦，不无限创建重复窗口；
        关闭窗口只销毁 Toplevel，不退出 Bridge（acceptance 4）。
        """
        self.status_ctl.open()

    def _restart_bridge(self) -> None:
        """重启 Bridge 宿主：注销热键 → 启动新实例（pythonw）→ 本实例立即退出。

        - 不修改正在执行 Task 的 canonical terminal state（不写 task.json / run.json）
        - 重启本身不触发 cancel / force kill（Phase E 停止动作只在用户从状态窗口显式触发）
        - 单实例 mutex 保证新旧不双开：旧实例退出后新实例取得所有权
        """
        if self.listener is not None:
            try:
                unregister_hotkey(self.hotkey_id)
            except Exception:
                pass
            self.listener = None
        argv = build_restart_argv()
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            env = dict(os.environ)
            env["AAF_BRIDGE_RESTART"] = "1"  # 新实例据此重试等待旧实例退出（交接）
            subprocess.Popen(
                argv,
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                creationflags=flags,
            )
        except OSError as e:
            ui.show_error("AAF Bridge — 重启失败", f"无法启动新 Bridge 进程: {e}\n当前实例继续运行。")
            self._apply_hotkey()  # 恢复热键
            return
        # RW-012：重启是主动退出——禁止任何自恢复/复活（新实例由 mutex 交接接管）
        self._shutting_down = True
        os._exit(0)  # 立即退出：kernel 释放 mutex，新实例接管

    def _exit_aaf(self) -> None:
        """退出 AAF：只退出 Bridge / Tray 宿主，与 Stop Current Task 语义分离。

        不写 cancel.request / control.json，不写 task.json / run.json，
        不产生 CANCELLED / FAILED 终态（acceptance 8 / Do Not Do D）。

        RW-012：确认退出期间置 shutting_down——禁止触发 listener 自恢复
        （退出不复活）；用户取消 → 恢复常规运行（自恢复重新允许）。
        """
        self._shutting_down = True
        confirm = ui.ask_exit_aaf(self.root)
        if confirm:
            self.root.quit()
        else:
            self._shutting_down = False

    # ---------- Phase E / TASK-005-C：Stop / Force 动作（req 3/4/5/7） ----------

    def _request_stop(self, task_id: str, output_dir: str | None) -> None:
        """[停止当前任务]：确认 → 只写 cancel.request（soft cancel 优先，req 3）。

        - 只允许对当前 RUNNING 任务（req 1：terminal / 无任务 / 不可验证不提供）
        - 写入走 Core-owned cancel 模块（state.lock 序列化，§6B.19/FIX-003）
        - UI 绝不直接写 SUCCESS / FAILED / WAITING / CANCELLED（req 3/7）
        """
        if self.launcher.state != RUNNING or self.launcher.current is None:
            ui.show_error("无法停止", "当前没有正在执行的任务。")
            return
        if self.launcher.current.task_id != task_id:
            ui.show_error("无法停止", "任务已变化，请刷新后重试。")
            return
        if not output_dir:
            ui.show_error("无法停止", "找不到任务输出目录，无法发送停止请求。")
            return
        if not ui.ask_stop_task(self.root, task_id):
            return  # 用户取消
        try:
            cancel_mod.write_cancel_request(Path(output_dir), task_id)
        except cancel_mod.CancelRequestIdentityError as exc:
            ui.show_error("无法停止", f"任务身份不匹配，停止请求未发送：{exc}")
            return
        except Exception as exc:  # noqa: BLE001 —— 锁超时/OS 错误显式失败，不静默
            ui.show_error("无法停止", f"停止请求发送失败：{type(exc).__name__}: {exc}")
            return
        ui.show_info("停止请求已发送", "停止请求已发送，正在等待任务安全退出。\n任务会在当前阶段自然结束后停止。")

    @staticmethod
    def _force_refusal_cn(reason: str) -> str:
        """request_force_cancel 拒绝原因 → 中文主文案（技术代码附括号作诊断，req 10）。"""
        r = reason or ""
        if r.startswith("OWNERSHIP_"):
            return f"无法安全强制停止：任务所有权无法确认（可能已结束、已被接管或进程已退出）。未执行终止操作。（{r[:120]}）"
        if r.startswith("NOT_ELIGIBLE"):
            return f"尚不能强制停止：任务仍在软取消等待期内或取消请求无效。（{r[:120]}）"
        if r.startswith("TERMINATION_FAILED"):
            return "强制终止失败：任务进程未能被终止。"
        if r.startswith("EVIDENCE_WRITE_FAILED"):
            return "强制终止失败：无法记录终止证据。"
        if r.startswith("CONTROL_UPDATE_FAILED"):
            return "强制停止失败：无法更新任务控制记录。"
        if r.startswith("NO_ACTIVE_LAUNCH"):
            return "无法强制停止：找不到该任务的启动记录。"
        return f"无法安全强制停止：{r[:200]}"

    def _request_force_stop(self, task_id: str) -> None:
        """[强制停止]：第二次明确中文确认（req 4/5）→ verified force-cancel backend。

        不绕过：ownership verification / canonical registry / force evidence /
        recovery finalizer（全部由 launcher.request_force_cancel 强制，§6B.17）。
        """
        if not ui.ask_force_stop(self.root, task_id):
            return  # 用户取消第二次确认 → 不执行任何终止
        try:
            res = self.launcher.request_force_cancel(task_id)
        except Exception as exc:  # noqa: BLE001 —— 动作异常显式失败
            ui.show_error("强制停止失败", f"强制停止调用失败：{type(exc).__name__}: {exc}")
            return
        if res.ok:
            status_cn = overall_status_label(res.canonical_status) if res.canonical_status else "已终止"
            ui.show_info(
                "已强制停止",
                f"任务已强制停止，最终状态：{status_cn}。\n"
                "终止证据与已取消终态由任务框架收敛。",
            )
        else:
            ui.show_error("无法安全强制停止", self._force_refusal_cn(res.refusal_reason or ""))

    # ---------- 事件 ----------

    def _on_hotkey(self) -> None:
        """热键线程回调（非主线程）：仅入队，主线程处理。"""
        self.events.put("hotkey")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event == "hotkey":
                    self._handle_hotkey()
                elif isinstance(event, str) and event.startswith("tray:"):
                    self._on_tray_event(event)
                elif isinstance(event, tuple) and event[0] == "framework_finished":
                    self._handle_framework_finished(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _on_framework_finished(self, last, output: str) -> None:
        """launcher 等待线程回调：入队，主线程提示（tkinter 线程安全）。"""
        self.events.put(("framework_finished", last, output))

    def _handle_framework_finished(self, last, output: str) -> None:
        if last.result == RESULT_FINISHED:
            ui.show_finished(
                self.root,
                last.task_id,
                str(last.report_path or ""),
                on_copy=lambda: self._copy_last_report(),
            )
        elif last.result == RESULT_REPORT_NOT_FOUND:
            ui.show_error(
                "未找到报告",
                f"Task ID: {last.task_id} 执行结束（exit=0）但未找到 REPORT.md。\n"
                f"不得视为任务成功。",
            )
        elif last.result == RESULT_FAILED:
            ui.show_error(
                "任务执行失败",
                f"Task ID: {last.task_id}\nexit={last.exit_code}\n"
                f"详见输出目录中的 REPORT/日志。",
            )
        elif last.result == RESULT_FAILED_TO_START:
            ui.show_error(
                "启动失败",
                f"Task ID: {last.task_id} 启动失败（TASK.md 已保留）。",
            )

    def _copy_last_report(self) -> bool:
        """Copy Last Report → Planner Handoff → 剪贴板（不调用 Agent，不启动 TASK）。

        RW-024：复制动作不再弹第二个「报告已复制」modal——返回 bool 供完成窗口
        就地显示「已复制 ✓ / 复制失败」。handoff 构建与剪贴板写逻辑保持不变。
        """
        last = handoff.load_last_run()
        if last is None:
            return False
        report_text = handoff.read_report(last.report_path)
        if report_text is None:
            return False
        closure = handoff.git_snapshot(Path(last.task_path).parent if last.task_path else ".")
        payload = handoff.build_handoff(last, report_text, closure)
        return ui.clipboard_set_text(self.root, payload)

    def _handle_hotkey(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            self._process_clipboard()
        except Exception as e:  # noqa: BLE001 —— Bridge 不应因单次异常崩溃
            ui.show_error("AAF Bridge", f"处理异常: {e}")
        finally:
            self.busy = False

    def _process_clipboard(self) -> None:
        text = ui.clipboard_get_text(self.root).strip()
        if not text:
            ui.show_error("AAF Bridge", "剪贴板为空或正被其他程序占用，请重试。")
            return

        # Phase F / TASK-006：决策与 UI 分离（intake 纯逻辑可单测；req 1–13）
        plan = intake.plan_submission(text, self.cfg, self.launcher)

        # 1) reject：明确原因；duplicate 附带状态卡片（req 8/9/10）
        if plan.is_reject:
            if plan.duplicate is not None:
                self._show_duplicate_card(plan.duplicate)
                return
            title = "当前任务正在运行" if plan.running_blocked else "AAF Bridge — TASK 校验失败"
            ui.show_error(title, "\n".join(plan.reasons))
            return

        # 2) 项目切换确认（已知/陌生 workspace；取消 = 不切换、不执行、不写任何文件）
        if plan.action in (intake.ACTION_CONFIRM_SWITCH, intake.ACTION_CONFIRM_UNKNOWN):
            if not ui.show_workspace_switch(self.root, plan):
                return

        # 3) 确认后执行：切换持久化（如需）→ 落盘 TASK.md（save_task duplicate 兜底仍在）
        try:
            target = intake.apply_submission(plan, cfg_mod.CONFIG_PATH)
        except cfg_mod.ConfigError as e:
            # FIX-001：原子保存失败 → 显式失败（不静默声称切换成功）；旧 config 原样
            # 保留（save_config contract），任务未启动
            ui.show_error(
                "AAF Bridge — 配置保存失败",
                f"项目切换未能持久化，任务未启动：{e}\n"
                f"原配置保持不变，请检查磁盘空间 / 文件权限后重试。",
            )
            return
        except task_io.TaskParseError as e:
            # 兜底：plan 后出现竞态 duplicate（文件已存在）→ 尽力展示状态卡片
            dup_info = dup_mod.inspect_duplicate(plan.task_id, plan.workspace, None)
            if dup_info is not None:
                self._show_duplicate_card(dup_info)
            else:
                ui.show_error("AAF Bridge", str(e))
            return
        if plan.switch_workspace:
            self.cfg = cfg_mod.load_config()  # 状态窗口/后续提交立即反映新项目

        # 4) 自动启动 Framework 执行链（subprocess 调用 run.py，后台运行）
        output_dir = self.launcher.default_output_dir(plan.workspace, plan.task_id)
        try:
            started = self.launcher.launch(target, plan.workspace, output_dir, plan.task_id)
        except AlreadyRunningError:
            ui.show_error(
                "任务已在执行",
                f"已有 Framework TASK 在执行中，不允许并发。\n"
                f"新任务已保留：{target}\n"
                f"请等待当前任务结束后重新提交。",
            )
            return
        if not started:
            ui.show_error(
                "启动失败",
                f"Framework 启动失败（TASK.md 已保留）:\n{target}\n"
                f"Last result: {self.launcher.last.result if self.launcher.last else 'n/a'}",
            )
            return
        ui.show_info("任务已启动", f"Task ID: {plan.task_id}\nTASK.md: {target}\nFramework 已在后台执行。")

    # ---------- Phase F / TASK-006：Duplicate 状态卡片（req 8/9/10，只读） ----------

    def _show_duplicate_card(self, info) -> None:
        """展示 duplicate 状态卡片（设计 §10.1）；只读，不改写任何 canonical / artifacts。"""
        ui.show_duplicate_card(
            self.root,
            info,
            on_view_status=self._open_status_window,
            on_open_report=self._open_report_path,
        )

    def _open_report_path(self, report_path: str) -> None:
        """用系统默认编辑器打开 REPORT.md（设计 §10.3；归档任务自动定位）。"""
        try:
            os.startfile(report_path)  # type: ignore[attr-defined]  # Windows only
        except OSError as e:
            ui.show_error("打开 REPORT 失败", f"无法打开 {report_path}\n{e}")


def main() -> int:
    # 单实例保护：防双开；重启场景下新实例（env AAF_BRIDGE_RESTART=1）重试等待旧实例退出
    restart_mode = os.environ.get("AAF_BRIDGE_RESTART") == "1"
    guard = SingleInstance(
        retries=_RESTART_RETRIES if restart_mode else 2, delay=_RESTART_RETRY_DELAY
    )
    if not guard.acquire():
        _log("AAF Bridge 已在运行（单实例保护：本次启动退出）。")
        if restart_mode:
            ui.show_error(
                "AAF Bridge — 重启失败",
                "新实例未能在超时内接管（旧实例可能仍在运行）。\n请关闭旧实例后重新启动。",
            )
        else:
            ui.show_info(
                "AAF Bridge",
                "AAF Bridge 已在运行。\n请使用系统托盘图标管理（打开状态 / 重启 / 退出）。",
            )
        return 0

    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口；Bridge 为后台进程 + 热键触发
    bridge = Bridge(root)
    # 启动时打印状态（便于用户确认热键就绪；pythonw 下无输出）
    hotkey_desc = cfg_mod.parse_hotkey(bridge.cfg.get("hotkey", "ctrl+alt+a"))
    desc = (
        cfg_mod.describe_hotkey(*hotkey_desc)
        if hotkey_desc
        else repr(bridge.cfg.get("hotkey"))
    )
    _log(f"AAF Bridge 运行中 | 热键: {desc} | 项目: {bridge.cfg.get('current_project')!r}")
    _log("后台模式请使用 Tray 菜单（打开状态 / 重启 / 退出）；调试模式按 Ctrl+C 退出。")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    if bridge.tray is not None:
        try:
            bridge.tray.stop()
        except Exception:
            pass
    guard.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
