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
    """极简确认窗口：显示 Task ID / Task Name / Current Project / Workspace，返回 Execute/Cancel。"""
    win = tk.Toplevel(root)
    win.title("AAF Bridge — Confirm Task")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    rows = [
        ("Task ID", task_id or "(empty)"),
        ("Task Name", task_name or "(empty)"),
        ("Current Project", current_project or "(empty)"),
        ("Workspace", workspace or "(empty)"),
    ]
    for i, (label, value) in enumerate(rows):
        tk.Label(win, text=f"{label}:", font=("Segoe UI", 9, "bold")).grid(
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
    tk.Button(btns, text="Execute", width=12, command=on_execute).pack(side="left", padx=8)
    tk.Button(btns, text="Cancel", width=12, command=on_cancel).pack(side="left", padx=8)

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
