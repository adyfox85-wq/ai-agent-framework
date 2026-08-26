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
from . import task_io
from . import ui
from .win32 import HotkeyConflictError, HotkeyListener, read_clipboard_text, unregister_hotkey

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
                self.events.get_nowait()
                self._handle_hotkey()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

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
        text = read_clipboard_text().strip()
        if not text:
            ui.show_info("AAF Bridge", "剪贴板为空。请先在 Planner 中复制 TASK 文本。")
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
        ui.show_info(
            "AAF TASK CREATED",
            f"Task ID: {task_id}\nTask Name: {task_name}\n\n{target}",
        )


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
