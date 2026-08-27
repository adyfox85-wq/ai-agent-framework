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
from . import handoff
from . import task_io
from . import tray as tray_mod
from . import ui
from .launcher import (
    AlreadyRunningError,
    FrameworkLauncher,
    RESULT_FAILED,
    RESULT_FAILED_TO_START,
    RESULT_FINISHED,
    RESULT_REPORT_NOT_FOUND,
)
from .status_window import StatusWindowController, collect_status
from .win32 import HotkeyConflictError, HotkeyListener, unregister_hotkey

CONFIG_CHECK_INTERVAL = 2.0  # 秒：热键触发时检查配置变化（无需重启 Bridge）
CONFIG_RELOAD_INTERVAL = 2.0  # 秒：后台轮询配置 mtime
HEALTH_POLL_INTERVAL = 5.0  # 秒：health 轮询 → Tray 图标/Tooltip

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
                self.cfg, classify_bridge_health(self.listener), self.launcher
            ),
            on_restart=self._restart_bridge,
            on_exit=self._exit_aaf,
            on_close=None,
        )
        self._last_health: str | None = None
        self._cfg_mtime = self._config_mtime()
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

    def _apply_hotkey(self) -> None:
        parsed = cfg_mod.parse_hotkey(self.cfg.get("hotkey", "ctrl+alt+a"))
        if parsed is None:
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
            ui.show_error(
                "AAF Bridge — 热键冲突",
                f"{err}\n请在 ~/.aaf-bridge/config.json 修改 hotkey 后等待配置热加载。",
            )

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
        status, detail = classify_bridge_health(self.listener)
        self._last_health = status
        self.tray.set_health(status == HEALTH_OK, _HEALTH_LABELS.get(status, status), detail)

    def _poll_health(self) -> None:
        try:
            status, detail = classify_bridge_health(self.listener)
            if status != self._last_health and self.tray is not None:
                self._last_health = status
                self.tray.set_health(status == HEALTH_OK, _HEALTH_LABELS.get(status, status), detail)
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
        - 不实现 Phase E（无 ownership verification / cancel / taskkill）
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
        os._exit(0)  # 立即退出：kernel 释放 mutex，新实例接管

    def _exit_aaf(self) -> None:
        """退出 AAF：只退出 Bridge / Tray 宿主，与 Stop Current Task 语义分离。

        不写 cancel.request / control.json，不写 task.json / run.json，
        不产生 CANCELLED / FAILED 终态（acceptance 8 / Do Not Do D）。
        """
        confirm = ui.ask_exit_aaf(self.root)
        if confirm:
            self.root.quit()

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

    def _copy_last_report(self) -> None:
        """Copy Last Report → Planner Handoff → 剪贴板（不调用 Agent，不启动 TASK）。"""
        last = handoff.load_last_run()
        if last is None:
            ui.show_error("AAF Bridge", "NO_LAST_RUN：还没有运行过的 Framework TASK。")
            return
        report_text = handoff.read_report(last.report_path)
        if report_text is None:
            ui.show_error("AAF Bridge", "REPORT_NOT_FOUND：last REPORT.md 不存在，无法生成 Handoff。")
            return
        closure = handoff.git_snapshot(Path(last.task_path).parent if last.task_path else ".")
        payload = handoff.build_handoff(last, report_text, closure)
        if ui.clipboard_set_text(self.root, payload):
            ui.show_info("报告已复制", f"Task ID: {last.task_id}\nPlanner Handoff 已复制到剪贴板。")
        else:
            ui.show_error("AAF Bridge", "剪贴板写入失败（可能被其他程序占用）。")

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

        expected_ws = str(self.cfg.get("current_workspace") or "").strip()
        ok, errors = task_io.validate_task_text(text, expected_ws)
        if not ok:
            ui.show_error("AAF Bridge — TASK 校验失败", "\n".join(errors))
            return

        fields = task_io.parse_task(task_io.extract_task_body(text))
        task_id = fields["task_id"]
        task_name = fields["task_name"]
        workspace = fields["workspace"]

        confirmed = ui.show_confirm(
            self.root,
            task_id,
            task_name,
            str(self.cfg.get("current_project") or ""),
            workspace,
        )
        if not confirmed:
            return  # Cancel：不生成文件

        try:
            # 落盘内容 = 提取后的标准 TASK 正文（含 BEGIN/END 标记），
            # 不写入剪贴板中标记外的无关前后文
            task_body = task_io.extract_task_body(text)
            target = task_io.save_task(
                f"{task_io.BEGIN_MARKER}\n{task_body}\n{task_io.END_MARKER}",
                workspace,
                task_id,
            )
        except task_io.TaskParseError as e:
            ui.show_error("AAF Bridge", str(e))
            return

        # 自动启动 Framework 执行链（subprocess 调用 run.py，后台运行）
        output_dir = self.launcher.default_output_dir(workspace, task_id)
        try:
            started = self.launcher.launch(target, workspace, output_dir, task_id)
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
        ui.show_info("任务已启动", f"Task ID: {task_id}\nTASK.md: {target}\nFramework 已在后台执行。")


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
