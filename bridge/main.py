"""AAF Bridge — 最小入口。

流程：热键触发 → 读剪贴板 → 解析/校验 TASK → 确认窗口 → 落盘 .aaf/tasks/active/<Task-ID>.md → 提示。

运行：python -m bridge.main
（Windows；零第三方依赖：ctypes RegisterHotKey + tkinter UI）
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

from . import config as cfg_mod
from . import handoff
from . import task_io
from . import ui
from .launcher import (
    AlreadyRunningError,
    FrameworkLauncher,
    RESULT_FAILED,
    RESULT_FAILED_TO_START,
    RESULT_FINISHED,
    RESULT_REPORT_NOT_FOUND,
)
from .win32 import HotkeyConflictError, HotkeyListener, unregister_hotkey

CONFIG_CHECK_INTERVAL = 2.0  # 秒：热键触发时检查配置变化（无需重启 Bridge）
CONFIG_RELOAD_INTERVAL = 2.0  # 秒：后台轮询配置 mtime


class Bridge:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = cfg_mod.load_config()
        self.hotkey_id = 1
        self.listener: HotkeyListener | None = None
        self.events: queue.Queue = queue.Queue()
        self.busy = False  # 防抖：一次只处理一个热键
        self.launcher = FrameworkLauncher(on_finished=self._on_framework_finished)
        self._cfg_mtime = self._config_mtime()
        self._apply_hotkey()
        self.root.after(100, self._poll_events)
        self.root.after(int(CONFIG_RELOAD_INTERVAL * 1000), self._poll_config)

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
                "AAF Bridge — REPORT_NOT_FOUND",
                f"Task ID: {last.task_id} 执行结束（exit=0）但未找到 REPORT.md。\n"
                f"不得视为任务成功。",
            )
        elif last.result == RESULT_FAILED:
            ui.show_error(
                "AAF TASK FAILED",
                f"Task ID: {last.task_id}\nexit={last.exit_code}\n"
                f"详见输出目录中的 REPORT/日志。",
            )
        elif last.result == RESULT_FAILED_TO_START:
            ui.show_error(
                "AAF Bridge — FAILED_TO_START",
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
            ui.show_info("AAF REPORT COPIED", f"Task ID: {last.task_id}\nPlanner Handoff 已复制到剪贴板。")
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
                "AAF Bridge — AAF_TASK_ALREADY_RUNNING",
                f"已有 Framework TASK 在执行中，不允许并发。\n"
                f"新任务已保留：{target}\n"
                f"请等待当前任务结束后重新提交。",
            )
            return
        if not started:
            ui.show_error(
                "AAF Bridge — FAILED_TO_START",
                f"Framework 启动失败（TASK.md 已保留）:\n{target}\n"
                f"Last result: {self.launcher.last.result if self.launcher.last else 'n/a'}",
            )
            return
        ui.show_info("AAF TASK RUNNING", f"Task ID: {task_id}\nTASK.md: {target}\nFramework 已在后台执行。")


def main() -> int:
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口；Bridge 为后台进程 + 热键触发
    bridge = Bridge(root)
    # 启动时打印状态（便于用户确认热键就绪）
    hotkey_desc = cfg_mod.parse_hotkey(bridge.cfg.get("hotkey", "ctrl+alt+a"))
    desc = (
        cfg_mod.describe_hotkey(*hotkey_desc)
        if hotkey_desc
        else repr(bridge.cfg.get("hotkey"))
    )
    print(f"AAF Bridge 运行中 | 热键: {desc} | 项目: {bridge.cfg.get('current_project')!r}")
    print("按 Ctrl+C 退出。")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
