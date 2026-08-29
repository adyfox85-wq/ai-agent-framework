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
from .win32 import HotkeyConflictError, HotkeyListener

CONFIG_CHECK_INTERVAL = 2.0  # 秒：热键触发时检查配置变化（无需重启 Bridge）
CONFIG_RELOAD_INTERVAL = 2.0  # 秒：后台轮询配置 mtime
HEALTH_POLL_INTERVAL = 5.0  # 秒：health 轮询 → Tray 图标/Tooltip

# RW-012：hotkey listener 自恢复（有界 backoff；唯一 owner = Bridge 实例）
RECOVERY_MAX_FAILURES = 3  # 连续恢复失败上限 → 停止自动恢复（不 tight loop）
RECOVERY_BACKOFF_SECONDS = (15.0, 30.0, 60.0)  # 第 1/2/3 次失败后的等待秒数

# RW-012 FIX-001：旧 listener 停止确认的有界上限（stop 契约；超时 → fail safe）
LISTENER_STOP_TIMEOUT = 5.0  # 秒
# RW-012 FIX-002：新 listener 初始化就绪等待上限（wait_ready authority）
LISTENER_READY_TIMEOUT = 3.0  # 秒

# RW-012 FIX-002（one-listener ownership invariant，跨 recovery cycle 成立）：
# - 只要旧 listener 尚未确认退出（stop() == True / is_alive() == False），
#   self.listener 必须持续指向它（ownership retention），不得启动 replacement；
#   未确认退出的 listener 记入 self._pending_stop（DEGRADED / recovery pending
#   可观察状态），下一轮 recovery 继续针对同一个旧 listener 处理。
# - wait_ready(timeout) 返回值参与 start success 判定：初始化超时（线程可能
#   仍 alive 但未 ready）不 reset recovery/backoff、不报告 healthy。
# - 健康判定区分 alive / ready / error：thread alive != hotkey usable。

# RW-012 FIX-003（atomic delayed-exit recovery，单一 lifecycle authority）：
# - _poll_health 的 delayed-exit check-and-clear 是受 _lifecycle_lock 保护的原子
#   单元（_delayed_exit_cleanup）：check pending exited → 锁内重新确认 identity
#   （self._pending_stop is old、self.listener is old、old not alive）→ 才清理。
#   关闭 FIX-002 遗留的 TOCTOU：lock 外 check → 锁内另一路创建 replacement →
#   lock 外 clear 清掉新 listener reference 的合法交错路径。
# - 清理 = ownership release 的真实 lifecycle 状态变化 → HotkeyRecovery.rearm()
#   开启一次新的有界 recovery epoch（epoch+1，_stopped/backoff/失败计数复位）。
#   这不是无限预算重置：每次 delayed-exit 事件只 rearm 一次（identity-safe
#   clear 只发生一次），replacement 失败仍受 max_failures/backoff 有界约束，
#   不会每 poll tick 重置、不会 tight loop。

# RW-012 FIX-004（atomic recovery transition consolidation，单一锁内 transition）：
# - FIX-003 遗留的多段 ownership transition 被收敛：此前 _poll_health 在 lock 内
#   做 cleanup/rearm → 释放 lock → lock 外判定 recovery eligibility →
#   再次获取 lock 创建 replacement，cleanup 与 replacement start 之间存在
#   exposed intermediate state（listener=None / pending=None / rearmed 但
#   transition 未 reserved/owned，可被另一 lifecycle trigger 利用）。
# - 现在 `_run_lifecycle_transition()` 在同一个 _lifecycle_lock 临界区内完成
#   完整状态转换：old pending 确认退出 → 锁内 identity 重验证 → clear old
#   ownership → rearm 恰好一次 → eligibility 判定 → reserve attempt
#   （begin_attempt）→ exactly one replacement（_apply_hotkey_locked）。
#   锁作用域内不存在可竞争 gap：任何其他 trigger 在锁外不可见该中间态，
#   非阻塞获取失败即 coalesce（Requirement 1/5）。
# - `_apply_hotkey_locked()` 是唯一的 listener replace/start transition owner
#   （public `_apply_hotkey` 只负责获取锁后委托；config reload / health
#   recovery / delayed cleanup / restart-failure 全部汇入同一 authority，
#   Requirement 2/3/6）。持锁状态不得再调用会自行获取锁的 `_apply_hotkey`
#   （非重入锁 → 合并而非死锁；locked 内部路径一律用 _locked 变体）。
# - rearm 仍是真实的 one-shot ownership-release 事件：只有 pending old 确认
#   退出才 rearm（Requirement 7）；listener=None / DEGRADED / 每 poll 都不会
#   自动 rearm——epoch 只随真实 exit 事件增长（Requirement 8）。

# RW-012 FIX-005（shutdown/recovery 单一 lifecycle authority，TOCTOU 收口）：
# - shutdown intent 发布与 listener lifecycle transition 共用同一个
#   _lifecycle_lock：shutdown() / _exit_aaf() / _restart_bridge() 都在
#   lifecycle authority 下发布 _shutting_down=True（不再 lock 外写标志）。
# - _run_lifecycle_transition() 在 lock 内重新验证 _shutting_down：关闭
#   「pre-lock check False → 等待锁 → shutdown 发布 → 取得锁后仍 rearm/
#   创建 replacement」的 check-then-wait 竞态；等待锁期间 shutdown 已发布
#   的 recovery 在锁内观察到 True → 不 cleanup / 不 rearm / 不创建。
# - _apply_hotkey_locked()（唯一 listener creation authority）在锁内以
#   _shutting_down 守卫：config reload / 外部触发 / restart-failure 恢复
#   在 shutdown 发布后一律不创建、不重启 listener（shutdown 接管后无新
#   recovery）。
# - _clear_pending_ownership_locked() 的 rearm 只在非 shutdown 时发生：
#   shutdown 期间的 delayed-exit cleanup 允许做 ownership bookkeeping，
#   但绝不 rearm / 不开启新 recovery epoch（Requirement 9/17）。

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


def classify_bridge_health(listener, stop_pending: bool = False) -> tuple[str, str]:
    """最小 health 判定（设计 §8.2，Phase B 范围）：(status, detail)。

    - OK：listener 已注册且消息循环线程存活且初始化就绪
    - DEGRADED：未注册 / 注册失败（冲突）/ 线程已退出 / 未就绪 /
      stop 已请求但未确认退出（stop_pending）
    RW-012 FIX-002：健康判定区分 alive / ready / error 三个维度——
    线程存活（is_alive()）不等于初始化就绪（ready），未 ready 不得视为
    hotkey usable；旧 listener 未确认退出（stop_pending）时即使线程仍存活
    也视为 DEGRADED（不伪装 healthy）。
    不实现 heartbeat / self-healing / RW-020（Phase B 明确排除）。
    """
    if listener is None:
        return HEALTH_DEGRADED, "热键未注册"
    if stop_pending:
        return HEALTH_DEGRADED, "旧热键监听线程未确认退出（等待其退出后重建）"
    err = listener.error()
    if err is not None:
        return HEALTH_DEGRADED, f"热键注册失败: {err}"
    if not listener.is_alive():
        return HEALTH_DEGRADED, "热键监听线程已退出"
    if not listener.is_ready():
        return HEALTH_DEGRADED, "热键监听线程未就绪"
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
        # RW-012 FIX-003：recovery epoch 计数。每次 delayed-exit ownership
        # release（rearm）+1，用于验证「每个真实 lifecycle 变化只 rearm 一次、
        # 不每 poll 无限重置」（可观测 / 可单测）。
        self.epoch = 0

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

    def rearm(self) -> None:
        """RW-012 FIX-003：delayed-exit ownership release → 开启一次新的有界
        recovery epoch。

        语义：`_stopped` / backoff / 失败计数全部复位，epoch += 1。表示
        「旧的 unresolved ownership blocker 已真实解除（pending old listener
        确认退出）」，允许一次新的有界 replacement recovery opportunity——
        这不是无限 retry，而是新的 lifecycle condition（Requirement 5/6B）。

        与 reset() 的区别：reset 表示「当前 listener 成功」（不产生新 epoch）；
        rearm 表示「ownership blocker 已解除」这一真实状态变化，只应在
        identity-safe delayed-exit clear 内调用一次。replacement 失败仍受
        max_failures / backoff 有界约束，不会每 poll tick 重置（Requirement 7）。
        """
        self.consecutive_failures = 0
        self._next_attempt_at = 0.0
        self._recovering = False
        self._stopped = False
        self.epoch += 1

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
        # RW-012 FIX-001：lifecycle transition 互斥（同一时刻只有一个 transition
        # owner；Tk 主线程串行之外的最小并发 guard）
        self._lifecycle_lock = threading.Lock()
        # RW-012 FIX-002：stop 已请求但未确认退出的旧 listener（ownership
        # retention 的可见状态）。只要该引用非 None，Bridge 就仍持有旧 listener
        # 的 ownership reference——未确认退出前不得启动 replacement、不得伪装
        # healthy；它被确认退出（stop True / is_alive False）后清空。
        self._pending_stop: HotkeyListener | None = None
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

    def _stop_listener(self, timeout: float = LISTENER_STOP_TIMEOUT) -> bool:
        """停止当前 listener 并确认线程退出（stop 契约；thread-owned unregister）。

        - Bridge/主线程只调用 listener.stop(timeout)：请求停止 + 有界 join；
          UnregisterHotKey 由 listener 自己的线程在 run() 收尾时执行
          （registration 归 listener 线程所有，外部线程不得直接注销）。
        - 返回 True = 已确认退出（或本来就没有 listener）；
          返回 False = 超时未退出 → 调用方必须 fail safe（不得启动 replacement）。

        RW-012 FIX-002（ownership retention）：只在确认退出后才清空
        self.listener 引用——stop 超时（旧线程仍可能存活）时保留引用并把
        listener 记入 self._pending_stop（degraded / recovery pending 可观察
        状态）；下一轮 recovery 继续针对同一个旧 listener 处理。任何情况下
        都不会出现「旧 listener 仍存活但 Bridge 已丢失其 reference」的 orphan
        窗口，因此跨 recovery cycle 不会误启动 duplicate replacement。
        """
        listener = self.listener
        if listener is None:
            self._pending_stop = None
            return True
        try:
            exited = listener.stop(timeout)
        except Exception:
            exited = False
        if exited:
            # 仅确认退出后解绑（stop True ⟹ 线程已退出 ⟹ thread-owned
            # unregister 已完成）；pending 状态一并清除
            self.listener = None
            self._pending_stop = None
        else:
            # stop 超时：旧线程仍可能存活 → 保留 ownership reference，
            # 标记 pending（health = DEGRADED），不伪装 stop success
            self._pending_stop = listener
            _log(
                "AAF Bridge: 旧热键监听线程未能在限时内退出"
                f"（{timeout:.0f}s），fail safe：不启动重复 listener，"
                "保留 ownership reference，保持 DEGRADED 等待有界重试。"
            )
        return exited

    def _clear_pending_ownership_locked(self, old) -> bool:
        """RW-012 FIX-003：identity-safe delayed-exit ownership clear。

        调用方必须已持有 _lifecycle_lock（本方法自身不获取锁）。在锁内
        重新确认以下全部成立才清理（Requirement 2/3/12）：
        - self._pending_stop is old（pending 身份未变）
        - self.listener is old（self.listener 仍是同一个旧 listener——
          如果已被 replacement 接管则绝不清掉 replacement）
        - old 已确认退出（not alive 由调用方在同一个锁内检查）

        清理 = ownership release 的真实 lifecycle 状态变化 → 非 shutdown
        时 recovery rearm 一次（新有界 epoch）。RW-012 FIX-005：shutdown
        已发布（_shutting_down=True）时只做 ownership bookkeeping、绝不
        rearm / 不开启新 recovery epoch（Requirement 9/17——退出不复活）。
        返回是否发生了清理。
        """
        if self._pending_stop is not old:
            return False  # pending 已变化（另一路已处理）→ 不做任何事
        if self.listener is not old:
            return False  # self.listener 已是 replacement → 绝不清掉它
        self.listener = None
        self._pending_stop = None
        if not self._shutting_down:
            # ownership blocker 已真实解除 → 开启一次新的有界 recovery epoch
            self._recovery.rearm()
        return True

    def _delayed_exit_cleanup_locked(self) -> bool:
        """RW-012 FIX-004：delayed-exit check-and-clear 的 locked 变体。

        调用方必须已持有 _lifecycle_lock（本方法自身不获取锁）。锁内重新确认
        pending 存在且已退出 → identity-safe clear（_clear_pending_ownership_locked
        双身份校验）→ ownership release → 非 shutdown 时 rearm 恰好一次
        （FIX-005：shutdown 已发布时清理但不 rearm——Requirement 9）。

        返回是否发生了清理。
        """
        pending = self._pending_stop
        if pending is None or pending.is_alive():
            return False  # 无 pending / 旧 listener 仍存活 → 不清理
        if self._clear_pending_ownership_locked(pending):
            if self._shutting_down:
                _log(
                    "AAF Bridge: 旧热键监听线程已确认退出（迟延退出），"
                    "清理 ownership reference（退出中：不 rearm、不复活）。"
                )
            else:
                _log(
                    "AAF Bridge: 旧热键监听线程已确认退出（迟延退出），"
                    "清理 ownership reference，恢复策略 rearm 一次。"
                )
            return True
        return False

    def _delayed_exit_cleanup(self) -> bool:
        """RW-012 FIX-003：受 lifecycle lock 保护的 delayed-exit check-and-clear
        原子单元（Requirement 1/2）。

        check（pending 存在且已退出）→ clear（identity 重验证）在同一个
        _lifecycle_lock 临界区内完成，不存在 lock 外 check → 锁内另一路创建
        replacement → lock 外 clear 的 TOCTOU 窗口（Requirement 11）。

        FIX-004：生产恢复路径不再单独调用本方法（已收敛进
        _run_lifecycle_transition 的单一锁内 transition）；本方法保留为
        独立的锁内原子单元入口（测试 / 外部调用可用）。

        返回是否发生了清理（并 rearm 一次 recovery epoch）。
        """
        with self._lifecycle_lock:
            return self._delayed_exit_cleanup_locked()

    def _apply_hotkey(self, show_error: bool = True) -> None:
        """应用热键配置（启动 / 配置热加载 / 自动恢复 / 外部触发）：public 入口。

        RW-012 FIX-004：本方法只负责获取 _lifecycle_lock 后委托给
        `_apply_hotkey_locked`（唯一 listener replace/start transition owner）。

        - 非阻塞获取锁：并发触发（另一 lifecycle transition 进行中）被合并，
          不创建重复 listener；锁释放后的下一次触发正常执行。
        - 持锁状态（lifecycle transition 内）不得调用本方法——非重入锁下
          非阻塞获取失败即 coalesce（不会死锁）；锁内路径一律用
          `_apply_hotkey_locked`。
        """
        if not self._lifecycle_lock.acquire(blocking=False):
            _log("AAF Bridge: 热键生命周期转换已在进行，本次触发被合并（不创建重复 listener）。")
            return
        try:
            self._apply_hotkey_locked(show_error)
        finally:
            self._lifecycle_lock.release()

    def _apply_hotkey_locked(self, show_error: bool = True) -> None:
        """RW-012 FIX-004：唯一的 listener replace/start transition owner。

        调用方必须已持有 _lifecycle_lock（本方法自身不获取锁）——所有
        lifecycle trigger（启动 / config reload / health recovery / delayed
        cleanup / restart-failure / 外部恢复入口）最终都汇入本方法创建
        listener，不存在第二套 listener creation 逻辑（Requirement 2/3/6）。

        RW-012 FIX-005（Requirement 3/10/12）：锁内首先重新验证 shutdown——
        shutdown intent 已发布（_shutting_down=True）时任何 trigger 一律
        不创建 / 不重启 / 不替换 listener（config reload during shutdown
        不 restart、不复活；shutdown 接管后不存在第二套创建路径）。

        stop-before-replace（Requirement 12）：
        - 先通过 listener-owned stop 契约停掉旧 listener（线程内注销 + 有界
          join），确认旧线程退出后才创建新 listener；主线程绝不直接
          UnregisterHotKey（registration 归 listener 线程所有）。
        - 旧 listener 未能在限时内退出 → fail safe：不创建 replacement、
          写入 warning、保留 ownership reference（_pending_stop）、状态保持
          DEGRADED（可恢复性保留给有界重试；跨 recovery cycle 不重复）。
        - 新 listener 启动后必须 wait_ready 成功且无 error 才算启动成功：
          wait_ready 超时 / error 均不 reset recovery/backoff、不报告 healthy。
        """
        # RW-012 FIX-005：shutdown 已在 lifecycle authority 下发布 → 唯一
        # creation authority 锁内拒绝任何创建（关闭 check-then-wait 竞态的
        # 另一半：config reload / 外部触发在 shutdown 后不得复活 listener）
        if self._shutting_down:
            _log("AAF Bridge: 正在退出，忽略热键生命周期触发（不创建 listener）。")
            return
        parsed = cfg_mod.parse_hotkey(self.cfg.get("hotkey", "ctrl+alt+a"))
        if parsed is None:
            if show_error:
                ui.show_error("AAF Bridge", f"热键配置无效: {self.cfg.get('hotkey')!r}（示例: ctrl+alt+a）")
            return
        mods, vk = parsed
        # 先停止旧 listener 并确认退出，才允许创建新 listener（stop-before-replace）
        if not self._stop_listener():
            return  # fail safe：旧 listener 未确认退出 → 不启动 replacement
        self.listener = HotkeyListener(mods, vk, self._on_hotkey, self.hotkey_id)
        self.listener.start()
        # RW-012 FIX-002：wait_ready 返回值必须参与 start success 判定——
        # 初始化超时（线程可能仍 alive 但未 ready）不得视为 healthy
        ready = self.listener.wait_ready(LISTENER_READY_TIMEOUT)
        err = self.listener.error()
        if err is not None:
            if show_error:
                ui.show_error(
                    "AAF Bridge — 热键冲突",
                    f"{err}\n请在 ~/.aaf-bridge/config.json 修改 hotkey 后等待配置热加载。",
                )
            return
        if not ready:
            # 初始化未在限时内就绪：不 reset recovery/backoff、不报告 healthy；
            # 尽力停止未就绪的 listener（未确认退出时保留引用 → recovery pending）
            _log(
                "AAF Bridge: 热键监听线程未能在限时内就绪（初始化超时），"
                "视为启动失败，不重置恢复策略，进入 DEGRADED 恢复流程。"
            )
            self._stop_listener()
            return
        # RW-012：成功应用（启动 / 热键变更 / 自动恢复）→ 恢复策略归零（允许重新自恢复）
        self._recovery.reset()

    def _run_lifecycle_transition(self) -> None:
        """RW-012 FIX-004：delayed-exit recovery 的单一 lifecycle transition。

        在同一个 _lifecycle_lock 临界区内完成完整状态转换（Requirement 1/5）：

            old pending 确认退出
            → 锁内 identity 重验证（pending/listener 双身份 + not alive）
            → clear old ownership（listener=None / pending=None）
            → rearm 恰好一次（新的有界 recovery epoch）
            → eligibility 判定（health 分类 + should_attempt）
            → reserve attempt（begin_attempt：后续触发 coalesce）
            → exactly one replacement（_apply_hotkey_locked）

        不再存在「cleanup lock → release → later eligibility → later
        reacquire for create」的多段 ownership transition：cleanup 与
        replacement start 之间不释放锁，`listener=None / pending=None /
        rearmed 但 transition 未 reserved/owned` 的可竞争中间态在锁外不可见，
        任何其他 lifecycle trigger 非阻塞获取锁失败即被合并。

        rearm 只随真实 delayed-exit ownership release 发生（Requirement 7）；
        listener=None / DEGRADED / 每次 poll 都不会自动 rearm（Requirement 8）。
        主动退出（_shutting_down）时整体跳过：不清理、不 rearm、不启动
        replacement（Requirement 13，退出不复活）。

        RW-012 FIX-005（Requirement 3/4）：锁外的 _shutting_down 检查只是
        快速路径；取得 lifecycle authority 后**在锁内重新验证** shutdown——
        等待锁期间 shutdown 可能已发布（pre-lock check False → 等待 → 
        shutdown 发布 True → 取得锁），此时必须观察到 True 并整体返回，
        不 cleanup / 不 rearm / 不 begin_attempt / 不创建 replacement
        （精确 check-then-wait TOCTOU 关闭，Codex FIX-004 blocker）。
        """
        if self._shutting_down:
            return
        with self._lifecycle_lock:
            # FIX-005：锁内重新验证 shutdown（权威判定；等待锁期间的
            # shutdown 发布必须被观察到，关闭 resurrection 竞态）
            if self._shutting_down:
                return
            # 1) delayed-exit ownership release（锁内 identity 重验证 + 恰好一次 rearm）
            self._delayed_exit_cleanup_locked()
            # 2) eligibility + reserve + replacement（同一锁作用域，单一 creation authority）
            status, _ = classify_bridge_health(
                self.listener, self._pending_stop is not None
            )
            if status != HEALTH_DEGRADED:
                return
            if not self._recovery.should_attempt(time.monotonic()):
                return
            self._recovery.begin_attempt()  # reserve：后续触发 coalesce
            try:
                self._apply_hotkey_locked(show_error=False)
                recovered = (
                    classify_bridge_health(
                        self.listener, self._pending_stop is not None
                    )[0]
                    == HEALTH_OK
                )
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

    def _current_health(self) -> tuple[str, str]:
        """健康判定 + 恢复状态说明（供 Tray / 状态窗口观察；失败必须可见）。"""
        status, detail = classify_bridge_health(self.listener, self._pending_stop is not None)
        note = self._recovery.note()
        if note and status == HEALTH_DEGRADED:
            detail = f"{detail}；{note}" if detail else note
        return status, detail

    def _try_recover_hotkey(self) -> bool:
        """RW-012：仅重建 listener（不重启 Bridge）；失败不弹窗（状态可见即可）。

        FIX-004：生产恢复路径已收敛进 `_run_lifecycle_transition`（单一锁内
        authority），本方法保留为外部触发入口（测试 / 其他调用方）——它仍
        经 `_apply_hotkey` → `_apply_hotkey_locked` 汇入同一个 listener
        creation authority，不存在第二套创建逻辑。
        """
        try:
            self._apply_hotkey(show_error=False)
        except Exception:
            # 异常路径不盲目清空引用（orphan prevention）：仅当确认退出
            # （is_alive False ⟹ thread-owned unregister 已完成）才允许解绑；
            # 仍存活 → 保留引用，由下一轮 recovery 继续处理。
            # RW-012 FIX-003：引用清理同样必须在 _lifecycle_lock 内做 identity
            # 重验证（lock 外 check → lock 外 clear 的 TOCTOU 路径关闭）——
            # 锁内确认 pending/listener 身份与退出状态后才清，绝不清掉
            # 并发路径已安装的 replacement。
            with self._lifecycle_lock:
                pending = self._pending_stop
                if pending is not None and not pending.is_alive():
                    self._clear_pending_ownership_locked(pending)
                elif self.listener is not None and not self.listener.is_alive():
                    # 无 pending 但当前 listener 已退出（异常发生在 stop 后 /
                    # 新 listener 未就绪即死）→ 锁内确认后移除死引用
                    self.listener = None
                    self._pending_stop = None
            return False
        status, _ = classify_bridge_health(self.listener, self._pending_stop is not None)
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
        """每 5s 健康轮询：单一 lifecycle transition → Tray/状态窗口反映结果。

        - 主动退出（shutting_down）期间不触发恢复（退出不复活）
        - RW-012 FIX-004：恢复动作收敛为 `_run_lifecycle_transition()`——在同一
          个 _lifecycle_lock 临界区内完成 delayed-exit cleanup（锁内 identity
          重验证 + 恰好一次 rearm）→ eligibility 判定 → reserve → exactly one
          replacement。不存在「cleanup 释放锁 → 锁外判定 → 再获取锁创建」的
          多段 ownership transition 与可竞争 gap；恢复进行中 / 已停止 /
          backoff 期内重复触发被策略拒绝（无重复 listener / 无 tight loop）
        - 失败保持在 Tray 图标 / Tooltip / 状态窗口可见（note 并入 detail）
        """
        try:
            if not self._shutting_down:
                self._run_lifecycle_transition()
                status, detail = classify_bridge_health(
                    self.listener, self._pending_stop is not None
                )
                note = self._recovery.note()
                if note and status == HEALTH_DEGRADED:
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
        # RW-012 FIX-001：请求 listener stop（thread-owned unregister + 有界 join），
        # 主线程不直接 UnregisterHotKey；进程随后退出，kernel 释放残余 registration
        # RW-012 FIX-003/FIX-005：stop/ownership transition 与其余 lifecycle 路径共用
        # 同一 _lifecycle_lock（单一 transition authority）；shutdown intent 在同一
        # authority 下发布（_shutting_down=True 与 stop 同临界区——发布后任何
        # lifecycle transition 都能可靠观察到，Popen 失败时在同一 authority 下回滚）
        with self._lifecycle_lock:
            self._shutting_down = True
            if self.listener is not None:
                self._stop_listener()
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
            # 重启启动失败：回滚 shutdown intent（同一 authority 下）→ 本实例
            # 继续运行，恢复热键（_apply_hotkey 此时未被 shutdown 守卫抑制）
            with self._lifecycle_lock:
                self._shutting_down = False
            ui.show_error("AAF Bridge — 重启失败", f"无法启动新 Bridge 进程: {e}\n当前实例继续运行。")
            self._apply_hotkey()  # 恢复热键
            return
        # RW-012：重启是主动退出——禁止任何自恢复/复活（新实例由 mutex 交接接管）；
        # shutdown intent 已在 lifecycle authority 下发布（见上）
        os._exit(0)  # 立即退出：kernel 释放 mutex，新实例接管

    def _exit_aaf(self) -> None:
        """退出 AAF：只退出 Bridge / Tray 宿主，与 Stop Current Task 语义分离。

        不写 cancel.request / control.json，不写 task.json / run.json，
        不产生 CANCELLED / FAILED 终态（acceptance 8 / Do Not Do D）。

        RW-012：确认退出期间置 shutting_down——禁止触发 listener 自恢复
        （退出不复活）；用户取消 → 恢复常规运行（自恢复重新允许）。
        RW-012 FIX-005：shutdown intent 在 lifecycle authority 下发布
        （_lifecycle_lock 内写 _shutting_down）——发布/回滚与 lifecycle
        transition 串行化，任何等待锁的 transition 都能可靠观察到。
        """
        with self._lifecycle_lock:
            self._shutting_down = True
        confirm = ui.ask_exit_aaf(self.root)
        if confirm:
            self.root.quit()
        else:
            with self._lifecycle_lock:
                self._shutting_down = False

    def shutdown(self) -> None:
        """Intentional shutdown（Exit 确认 / Ctrl+C）：listener stop 契约收尾。

        - 请求 listener stop → listener-owned unregister → 有界 join
        - 不触发任何恢复（_shutting_down 已置位，恢复被策略拒绝，不复活）
        - 幂等：可安全重复调用
        RW-012 FIX-003：stop/ownership transition 在 _lifecycle_lock 内执行
        （与 _apply_hotkey / delayed-exit cleanup 同一 transition authority）；
        shutdown 不 rearm、不启动 replacement（Requirement 16）。
        RW-012 FIX-005：shutdown intent 在同一 authority 内先于 stop 发布
        （Requirement 2/6：acquire → mark _shutting_down=True → stop →
        prevent any future recovery）——等待锁的 transition 在取得锁后
        必然观察到 shutdown；后续任何 poll / config reload / recovery
        触发都被守卫拒绝（shutdown 接管后不得再有新的 recovery）。
        """
        with self._lifecycle_lock:
            self._shutting_down = True
            self._stop_listener()

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
    bridge.shutdown()  # RW-012 FIX-001：intentional shutdown → listener stop 契约收尾
    guard.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
