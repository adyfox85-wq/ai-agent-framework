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


def ask_stop_task(root: tk.Tk, task_id: str) -> bool:
    """停止确认（设计 §12.3）：[确认停止] [取消]。

    确认后调用方只写 cancel.request（soft cancel，req 3）——不 kill、不写终态。
    """
    win = tk.Toplevel(root)
    win.title("停止确认 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(
        win, text="停止当前任务？", font=("Segoe UI", 10, "bold")
    ).pack(padx=16, pady=(14, 6), anchor="w")
    tk.Label(
        win,
        text=f"Task ID: {task_id}\n"
        "将发送停止请求（soft cancel）。\n"
        "任务会在当前阶段自然结束后停止，已完成的结果会保留。",
        font=("Segoe UI", 9),
        justify="left",
        wraplength=400,
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
    tk.Button(btns, text="确认停止", width=12, command=on_yes).pack(side="left", padx=8)
    tk.Button(btns, text="取消", width=12, command=on_no).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
    root.wait_window(win)
    return result["value"]


def ask_force_stop(root: tk.Tk, task_id: str, detail: str = "") -> bool:
    """强制停止确认（设计 §12.3）：[确认强制停止] [取消] + 红色警示文案。

    只有用户第二次明确确认才返回 True；调用方随后才走 verified force-cancel
    backend（req 4/5：ownership verification + 进程树终止 + evidence + Core finalizer）。
    """
    win = tk.Toplevel(root)
    win.title("强制停止确认 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(
        win, text="强制停止？", font=("Segoe UI", 11, "bold"), fg="#b00020"
    ).pack(padx=16, pady=(14, 6), anchor="w")
    tk.Label(
        win,
        text=f"Task ID: {task_id}\n"
        "强制停止会立即终止任务进程及其子进程树，无法撤销。\n"
        "仅在任务长时间未退出时使用；已完成的结果会保留，\n"
        "任务最终将以「已取消」结束。",
        font=("Segoe UI", 9),
        fg="#b00020",
        justify="left",
        wraplength=420,
    ).pack(padx=16, anchor="w")
    if detail:
        tk.Label(
            win, text=detail, font=("Segoe UI", 8), fg="#666666", justify="left", wraplength=420
        ).pack(padx=16, pady=(2, 0), anchor="w")

    result = {"value": False}

    def on_yes():
        result["value"] = True
        win.destroy()

    def on_no():
        result["value"] = False
        win.destroy()

    btns = tk.Frame(win)
    btns.pack(pady=12)
    tk.Button(btns, text="确认强制停止", width=13, command=on_yes).pack(side="left", padx=8)
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

    RW-024：单窗 UX——点击「复制报告」只执行复制并在窗内就地反馈
    （按钮变「已复制 ✓」/ 窗内「复制失败」），不弹第二个 modal、
    不关闭主窗；仅「关闭」按钮 / 窗口关闭按钮退出。

    on_copy 由调用方提供（执行 handoff 构建 + 写剪贴板），返回 bool：
    True = 复制成功；False = 复制失败。
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
    btns.pack(pady=(4, 0))
    feedback = tk.Label(win, text="", font=("Segoe UI", 9), fg="#1a7f37")
    feedback.pack(pady=(2, 6))

    copy_btn = tk.Button(btns, text="复制报告", width=12)
    copy_btn.pack(side="left", padx=8)

    def do_copy():
        try:
            ok = bool(on_copy())
        except Exception:  # noqa: BLE001 —— 复制回调异常显式显示失败，不弹窗
            ok = False
        if ok:
            copy_btn.config(text="已复制 ✓")
            feedback.config(text="已复制 ✓", fg="#1a7f37")
        else:
            copy_btn.config(text="复制报告")
            feedback.config(text="复制失败", fg="#b00020")

    copy_btn.config(command=do_copy)
    tk.Button(btns, text="关闭", width=12, command=win.destroy).pack(side="left", padx=8)

    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()


# ---------- Phase F / TASK-006：项目切换确认窗 + Duplicate 状态卡片 ----------

def show_workspace_switch(root: tk.Tk, plan) -> bool:
    """项目切换确认窗（设计 §9.1/§9.2.7；中文优先）。

    - 显示当前项目/目标项目/Workspace/Task ID + 「将修改 AAF Bridge 的项目设置」说明
    - 陌生 workspace：额外 fail-safe 警示文案（req 4）
    - [切换并执行] 返回 True；[取消] 返回 False（不切换、不执行、不写任何文件）
    """
    win = tk.Toplevel(root)
    win.title("切换项目确认 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(win, text="检测到新项目，需要切换项目后执行", font=("Segoe UI", 11, "bold")).pack(
        padx=16, pady=(14, 6), anchor="w"
    )
    rows = [
        ("Task ID", plan.task_id or "(empty)"),
        ("当前项目", plan.current_project or "（未设置）"),
        ("当前 Workspace", plan.current_workspace or "（未设置）"),
        ("目标项目", plan.target_project or "(empty)"),
        ("目标 Workspace", plan.workspace or "(empty)"),
    ]
    for label, value in rows:
        frame = tk.Frame(win)
        frame.pack(fill="x", padx=16, pady=2)
        tk.Label(frame, text=f"{label}：", font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(frame, text=value, font=("Segoe UI", 9), wraplength=440, justify="left").pack(
            side="left", padx=(6, 0)
        )

    if getattr(plan, "action", "") == "confirm_unknown":
        tk.Label(
            win,
            text="⚠ 该 Workspace 首次出现（陌生路径）。确认前不会执行任何操作。",
            font=("Segoe UI", 9, "bold"),
            fg="#b00020",
            wraplength=460,
            justify="left",
        ).pack(padx=16, pady=(8, 0), anchor="w")
    tk.Label(
        win,
        text="切换将修改 AAF Bridge 的项目设置（current_project / current_workspace）。",
        font=("Segoe UI", 8),
        fg="#666666",
        wraplength=460,
        justify="left",
    ).pack(padx=16, pady=(4, 0), anchor="w")

    result = {"value": False}

    def on_switch():
        result["value"] = True
        win.destroy()

    def on_cancel():
        result["value"] = False
        win.destroy()

    btns = tk.Frame(win)
    btns.pack(pady=12)
    tk.Button(btns, text="切换并执行", width=12, command=on_switch).pack(side="left", padx=8)
    tk.Button(btns, text="取消", width=12, command=on_cancel).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
    root.wait_window(win)
    return result["value"]


def show_duplicate_card(root: tk.Tk, info, on_view_status=None, on_open_report=None) -> None:
    """Duplicate 状态卡片（设计 §10.1/§10.3；中文优先）。

    - 展示 Task ID / 当前状态（中文映射）/ 当前阶段 / 最近活动 / 结果 / REPORT 路径
    - [查看状态]：运行中与异常状态提供（on_view_status 回调）
    - [打开 REPORT]：仅已完成/有 REPORT 时提供（on_open_report 回调）
    - [关闭]：仅关闭卡片，不做任何操作
    - 本卡片只读：不改写 canonical / 历史 artifacts（req 12）
    """
    win = tk.Toplevel(root)
    win.title("任务已存在 — AAF Bridge")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(win, text="任务已存在", font=("Segoe UI", 12, "bold"), fg="#9a6700").pack(
        padx=16, pady=(14, 4), anchor="w"
    )
    rows = [
        ("Task ID", info.task_id or "(empty)"),
        ("当前状态", f"{info.status_cn}" + (f"（{info.status}）" if info.status else "")),
        ("当前阶段", info.stage_cn or "—"),
        ("最近活动", info.last_activity or "—"),
        ("结果", info.status_cn or "—"),
    ]
    if info.report_path:
        rows.append(("REPORT 路径", info.report_path))
    for label, value in rows:
        frame = tk.Frame(win)
        frame.pack(fill="x", padx=16, pady=2)
        tk.Label(frame, text=f"{label}：", font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(frame, text=value, font=("Segoe UI", 9), wraplength=440, justify="left").pack(
            side="left", padx=(6, 0)
        )
    tk.Label(
        win,
        text=info.reason,
        font=("Segoe UI", 9),
        fg="#b00020",
        wraplength=470,
        justify="left",
    ).pack(padx=16, pady=(8, 0), anchor="w")

    btns = tk.Frame(win)
    btns.pack(pady=12)

    def _safe(cb):
        def wrapper(*args, **kwargs):
            win.destroy()
            try:
                cb(*args, **kwargs)  # 透传参数：on_open_report 需要 report_path（FIX-001）
            except Exception:  # noqa: BLE001 —— 打开失败不得让卡片卡死
                pass
        return wrapper

    if on_view_status is not None:
        tk.Button(btns, text="查看状态", width=12, command=_safe(on_view_status)).pack(side="left", padx=8)
    if on_open_report is not None and info.report_path:
        # FIX-001：按钮命令以闭包捕获 report_path——Tk 按钮 invoke 不带参数，
        # 直接 _safe(on_open_report) 会以零参数调用 → TypeError 被吞 → 死按钮
        tk.Button(
            btns, text="打开 REPORT", width=12,
            command=_safe(lambda: on_open_report(info.report_path)),
        ).pack(side="left", padx=8)
    tk.Button(btns, text="关闭", width=12, command=win.destroy).pack(side="left", padx=8)

    win.grab_set()
    win.update_idletasks()
    x = root.winfo_screenwidth() // 2 - win.winfo_width() // 2
    y = root.winfo_screenheight() // 2 - win.winfo_height() // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.focus_force()
    root.wait_window(win)
