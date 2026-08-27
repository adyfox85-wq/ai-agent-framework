"""AAF Bridge — tkinter 确认窗口与提示（薄 UI，全部在主线程使用）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox


def show_confirm(
    root: tk.Tk,
    task_id: str,
    task_name: str,
    current_project: str,
    workspace: str,
) -> bool:
    """确认窗口（Phase C 中文优先）：显示 Task ID / Task Name / 当前项目 / Workspace，返回 执行/取消。"""
    win = tk.Toplevel(root)
    win.title("确认任务 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    rows = [
        ("Task ID", task_id or "(empty)"),
        ("Task Name", task_name or "(empty)"),
        ("当前项目", current_project or "(empty)"),
        ("Workspace", workspace or "(empty)"),
    ]
    for i, (label, value) in enumerate(rows):
        tk.Label(win, text=f"{label}：", font=("Segoe UI", 9, "bold")).grid(
            row=i, column=0, sticky="ne", padx=10, pady=4
        )
        tk.Label(win, text=value, font=("Segoe UI", 9), wraplength=420, justify="left").grid(
            row=i, column=1, sticky="w", padx=10, pady=4
        )

    result = {"value": False}

    def on_execute():
        result["value"] = True
        win.destroy()

    def on_cancel():
        result["value"] = False
        win.destroy()

    btns = tk.Frame(win)
    btns.grid(row=len(rows), column=0, columnspan=2, pady=12)
    tk.Button(btns, text="执行", width=12, command=on_execute).pack(side="left", padx=8)
    tk.Button(btns, text="取消", width=12, command=on_cancel).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    # 居中
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
    root.wait_window(win)
    return result["value"]


def show_info(title: str, message: str) -> None:
    messagebox.showinfo(title, message)


def show_error(title: str, message: str) -> None:
    messagebox.showerror(title, message)


def ask_exit_aaf(root: tk.Tk) -> bool:
    """退出 AAF 确认（Phase C 中文按钮）。与 Stop Current Task 语义分离：只退出宿主。"""
    win = tk.Toplevel(root)
    win.title("退出 AAF")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(
        win, text="确定退出 AAF Bridge / Tray？", font=("Segoe UI", 10, "bold")
    ).pack(padx=16, pady=(14, 6), anchor="w")
    tk.Label(
        win,
        text="退出不会取消正在执行的任务（Framework 将继续在后台运行）。\n"
        "重新使用请运行 scripts/start_bridge.pyw。",
        font=("Segoe UI", 9),
        justify="left",
    ).pack(padx=16, anchor="w")

    result = {"value": False}

    def on_yes():
        result["value"] = True
        win.destroy()

    def on_no():
        result["value"] = False
        win.destroy()

    btns = tk.Frame(win)
    btns.pack(pady=12)
    tk.Button(btns, text="确认退出", width=12, command=on_yes).pack(side="left", padx=8)
    tk.Button(btns, text="取消", width=12, command=on_no).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
    root.wait_window(win)
    return result["value"]


def show_bridge_status(root: tk.Tk, rows: list[tuple[str, str]]) -> tk.Toplevel:
    """最小 Bridge 信息窗口（Phase B 占位；Phase C 预留接入点）。

    - 关闭窗口（X / Close 按钮）只销毁本窗口，不退出 Bridge
    - 返回窗口对象，调用方用于去重/聚焦
    """
    win = tk.Toplevel(root)
    win.title("AAF Bridge — 状态")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    for i, (label, value) in enumerate(rows):
        tk.Label(win, text=f"{label}:", font=("Segoe UI", 9, "bold")).grid(
            row=i, column=0, sticky="ne", padx=10, pady=3
        )
        tk.Label(win, text=value, font=("Segoe UI", 9), wraplength=420, justify="left").grid(
            row=i, column=1, sticky="w", padx=10, pady=3
        )

    note = tk.Label(
        win,
        text="关闭本窗口不会退出 Bridge。",
        font=("Segoe UI", 8),
        fg="#666666",
    )
    note.grid(row=len(rows), column=0, columnspan=2, padx=10, pady=(6, 0))

    btns = tk.Frame(win)
    btns.grid(row=len(rows) + 1, column=0, columnspan=2, pady=10)
    tk.Button(btns, text="关闭", width=12, command=win.destroy).pack()

    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    return win


def clipboard_set_text(root: tk.Tk, text: str) -> bool:
    """写入系统剪贴板（tkinter 路径，需在主线程）。成功返回 True。"""
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # 让剪贴板内容生效
        return True
    except tk.TclError:
        return False


def clipboard_get_text(root: tk.Tk) -> str:
    """读取系统剪贴板（tkinter 路径，需在主线程）。被占用时返回 ''。"""
    try:
        return root.clipboard_get()
    except tk.TclError:
        return ""


def show_finished(root: tk.Tk, task_id: str, report_path: str, on_copy) -> None:
    """任务完成窗口（Phase C 中文优先）：显示结果 + [复制报告] / [关闭]。

    on_copy 由调用方提供（执行 handoff 构建 + 写剪贴板 + 提示）。
    """
    win = tk.Toplevel(root)
    win.title("任务已完成 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(win, text="任务已完成", font=("Segoe UI", 12, "bold"), fg="#1a7f37").pack(
        padx=12, pady=(12, 4), anchor="w"
    )
    tk.Label(win, text=f"Task ID: {task_id}", font=("Segoe UI", 10)).pack(padx=12, anchor="w")
    tk.Label(
        win,
        text=f"REPORT: {report_path}",
        font=("Segoe UI", 9),
        wraplength=460,
        justify="left",
    ).pack(padx=12, pady=(2, 6), anchor="w")

    btns = tk.Frame(win)
    btns.pack(pady=8)

    def do_copy():
        try:
            on_copy()
        finally:
            win.destroy()

    tk.Button(btns, text="复制报告", width=12, command=do_copy).pack(side="left", padx=8)
    tk.Button(btns, text="关闭", width=12, command=win.destroy).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
