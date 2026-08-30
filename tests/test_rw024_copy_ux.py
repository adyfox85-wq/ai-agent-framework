"""AAF-v0.4-TASK-008 — RW-024 Completion Dialog Copy UX（复制后无第二窗口 + 就地反馈）。

覆盖（TASK req 8 A–F）：
A. copy success → 复制回调（clipboard 函数）被调用 → 无第二 modal / 无新 Toplevel
B. copy success → 原完成窗口保持打开（Task ID / REPORT 仍可见）
C. copy success → 按钮/窗内反馈变为「已复制 ✓」
D. 第二次复制 → 再次成功 → 仍无第二窗口
E. [关闭] 按钮 → 关闭主窗口
F. copy failure → 窗内「复制失败」反馈 → 无 false success（按钮不回退为已复制）
   + 失败后重试成功 → 反馈转为「已复制 ✓」

FIX-001 追加覆盖（TASK req 3/4/9 A–H）：
G. 反馈计时器到期 → 按钮/反馈恢复「复制报告」（临时反馈，不永久停留）
H. 反馈期内重复复制 → 复制再次执行 + 计时器刷新（不提前恢复）
I. 窗口在 timer 到期前关闭 → after 回调无异常、不重建窗口、无残留
J. backlog RW-024 状态与当前实现一致（SOLVED + 完成态字段 + 无「只登记不实现」）

策略：mocked/unit-level Tk 行为——真实（withdrawn）tk.Tk root 上调用
`ui.show_finished`，复制回调（on_copy）全部 mock：不触真实剪贴板、不触
ToDesk-sensitive clipboard E2E；用 monkeypatch 的 show_info/show_error
记录器证明成功路径零 modal 调用。计时器通过 monkeypatch
`ui_mod.COPY_FEEDBACK_MS` 缩短后以真实 Tk after 事件循环驱动。

AAF-RUNTIME-UX-GUI-TEST-LEAK-001：测试侧隔离——ui_root fixture 把
`tk.Toplevel` 替换为「构造后立即 withdraw」的子类，使本文件所有 Tk 测试
（含 show_finished 的完成窗）在普通 pytest 回归中不映射到真实桌面，
杜绝「任务已完成」窗口闪现；生产 `bridge/ui.show_finished` 未改动，
正式 AAF 完成窗口行为不变。

另含 Bridge 层测试：`Bridge._copy_last_report` 保留 handoff 构建 +
`ui.clipboard_set_text` 写剪贴板逻辑，返回 bool，且不再调用任何提示弹窗。
"""
from __future__ import annotations

import re
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from bridge import main as main_mod
from bridge import ui as ui_mod

WIN_TITLE = "任务已完成 — AAF Bridge"


def _all_widgets(w):
    for child in w.winfo_children():
        yield child
        yield from _all_widgets(child)


def _find_toplevels(root: tk.Tk) -> list[tk.Toplevel]:
    out = []
    for w in root.winfo_children():
        try:
            if isinstance(w, tk.Toplevel) and w.winfo_exists():
                out.append(w)
        except tk.TclError:
            continue
    return out


def _find_finished_window(root: tk.Tk):
    for w in _find_toplevels(root):
        try:
            if str(w.title()) == WIN_TITLE:
                return w
        except tk.TclError:
            continue
    return None


def _button(win, text: str):
    for c in _all_widgets(win):
        try:
            if c.winfo_class() == "Button" and str(c.cget("text")) == text:
                return c
        except tk.TclError:
            continue
    return None


def _label_texts(win) -> list[str]:
    out = []
    for c in _all_widgets(win):
        try:
            if c.winfo_class() == "Label":
                out.append(str(c.cget("text")))
        except tk.TclError:
            continue
    return out


def _button_texts(win) -> list[str]:
    out = []
    for c in _all_widgets(win):
        try:
            if c.winfo_class() == "Button":
                out.append(str(c.cget("text")))
        except tk.TclError:
            continue
    return out


def _pump(root: tk.Tk, n: int = 20) -> None:
    for _ in range(n):
        root.update()


@pytest.fixture()
def ui_root(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk 不可用（无显示环境）: {e}")
    root.withdraw()

    # AAF-RUNTIME-UX-GUI-TEST-LEAK-001：测试侧隔离——普通 pytest 回归中，
    # 本文件内创建的每个 Toplevel（含 show_finished 的完成窗）在构造后立即
    # withdraw，绝不映射到真实桌面，杜绝「任务已完成 / RW024-* / C:\out\REPORT.md」
    # 窗口闪现。窗口逻辑上仍存在（可查找、可按钮 invoke、after 事件仍调度），
    # 全部断言语义不变；生产 bridge/ui.show_finished 未做任何修改。
    class _WithdrawnToplevel(tk.Toplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()

    monkeypatch.setattr(tk, "Toplevel", _WithdrawnToplevel)
    yield root
    try:
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def modal_spy(monkeypatch):
    """记录 show_info / show_error 调用——成功路径必须零调用（req 1/6）。"""
    calls = {"info": [], "error": []}
    monkeypatch.setattr(ui_mod, "show_info", lambda title, msg: calls["info"].append((title, msg)))
    monkeypatch.setattr(ui_mod, "show_error", lambda title, msg: calls["error"].append((title, msg)))
    return calls


# ========== A. copy success → 复制回调被调用 → 无第二 modal / 无新 Toplevel ==========

def test_a_copy_success_calls_clipboard_no_secondary_window(ui_root, modal_spy):
    root = ui_root
    calls = []

    def on_copy():
        calls.append(1)
        return True

    ui_mod.show_finished(root, "RW024-A", r"C:\out\REPORT.md", on_copy)
    win = _find_finished_window(root)
    assert win is not None, "主完成窗口必须出现"
    toplevels_before = len(_find_toplevels(root))

    btn = _button(win, "复制报告")
    assert btn is not None
    btn.invoke()  # 真实按钮 command 回调
    _pump(root)

    assert calls == [1], "复制回调（clipboard 函数）必须被调用"
    assert len(_find_toplevels(root)) == toplevels_before, "不得创建第二个 Toplevel/modal"
    assert _find_finished_window(root) is win, "主完成窗口必须保持打开"
    # 成功路径：零 show_info / show_error（第二「报告已复制」modal 已移除）
    assert modal_spy["info"] == []
    assert modal_spy["error"] == []


# ========== B. copy success → 主完成窗口保持打开（Task ID / REPORT 仍可见） ==========

def test_b_primary_window_remains_alive(ui_root):
    root = ui_root
    ui_mod.show_finished(root, "RW024-B", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    assert win is not None
    btn = _button(win, "复制报告")
    btn.invoke()
    _pump(root)

    assert _find_finished_window(root) is win, "复制后主窗口不得关闭"
    texts = "\n".join(_label_texts(win))
    assert "RW024-B" in texts, "Task ID 仍可查看"
    assert "C:\\out\\REPORT.md" in texts, "REPORT path 仍可查看"


# ========== C. copy success → 按钮/窗内反馈变为「已复制 ✓」 ==========

def test_c_inline_feedback_shows_copied(ui_root):
    root = ui_root
    ui_mod.show_finished(root, "RW024-C", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    btn = _button(win, "复制报告")
    btn.invoke()
    _pump(root)

    assert "已复制 ✓" in _button_texts(win), "按钮文案必须变为「已复制 ✓」"
    assert "已复制 ✓" in _label_texts(win), "窗内必须有「已复制 ✓」就地反馈"
    assert _button(win, "复制报告") is None, "复制成功后按钮不再显示原文案"


# ========== D. 第二次复制 → 再次成功 → 仍无第二窗口 ==========

def test_d_second_copy_succeeds_no_secondary_window(ui_root, modal_spy):
    root = ui_root
    calls = []
    ui_mod.show_finished(root, "RW024-D", r"C:\out\REPORT.md", lambda: calls.append(1) or True)
    win = _find_finished_window(root)
    toplevels_before = len(_find_toplevels(root))

    first = _button(win, "复制报告")
    first.invoke()
    _pump(root)
    second = _button(win, "已复制 ✓")
    assert second is not None, "第一次复制后按钮变为「已复制 ✓」"
    second.invoke()  # 重复复制：按钮仍可点击
    _pump(root)

    assert calls == [1, 1], "每次点击都必须再次执行复制"
    assert len(_find_toplevels(root)) == toplevels_before, "重复复制仍不得创建第二窗口"
    assert _find_finished_window(root) is win
    assert "已复制 ✓" in _button_texts(win), "inline feedback 可重复刷新"
    assert modal_spy["info"] == [] and modal_spy["error"] == []


# ========== E. [关闭] 按钮 → 关闭主窗口 ==========

def test_e_close_button_closes_primary_window(ui_root):
    root = ui_root
    ui_mod.show_finished(root, "RW024-E", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    assert win is not None

    close_btn = _button(win, "关闭")
    assert close_btn is not None
    close_btn.invoke()
    _pump(root)

    assert _find_finished_window(root) is None, "只有 [关闭] 才关闭主完成窗口"
    assert _find_toplevels(root) == [], "关闭后无残留窗口"


# ========== F. copy failure → 失败反馈 → 无 false success；重试成功可恢复 ==========

def test_f_copy_failure_no_false_success_then_retry(ui_root, modal_spy):
    root = ui_root
    results = iter([False, True])  # 第一次失败，重试成功

    def on_copy():
        return next(results)

    ui_mod.show_finished(root, "RW024-F", r"C:\out\REPORT.md", on_copy)
    win = _find_finished_window(root)
    btn = _button(win, "复制报告")
    btn.invoke()
    _pump(root)

    # 失败：无 false success，按钮保持原文案，窗内显示「复制失败」
    assert _button(win, "复制报告") is not None, "失败后按钮不得显示「已复制 ✓」"
    assert _button(win, "已复制 ✓") is None, "失败路径不得出现 false success 状态"
    assert "复制失败" in _label_texts(win), "失败必须显示「复制失败」就地反馈"
    assert _find_finished_window(root) is win, "失败后主窗口保持打开"
    assert modal_spy["info"] == [], "失败路径也不得弹「报告已复制」modal"
    assert modal_spy["error"] == [], "失败反馈走窗内就地显示，不弹 error modal"

    # 重试成功 → 反馈转为「已复制 ✓」，窗口仍打开
    retry = _button(win, "复制报告")
    retry.invoke()
    _pump(root)
    assert "已复制 ✓" in _button_texts(win)
    assert _find_finished_window(root) is win


# ========== Bridge 层：_copy_last_report 保留 copy 逻辑 + 返回 bool + 零 modal ==========

def test_bridge_copy_last_report_builds_handoff_and_writes_clipboard(ui_root, monkeypatch, modal_spy):
    """复制动作本身（handoff 构建 + clipboard write）不被破坏；返回 bool 供就地反馈。"""
    root = ui_root
    written: list[str] = []

    def fake_load_last_run():
        return SimpleNamespace(
            task_id="RW024-BRIDGE",
            report_path=r"C:\out\REPORT.md",
            task_path=r"C:\ws\.aaf\tasks\active\RW024-BRIDGE.md",
        )

    monkeypatch.setattr(main_mod.handoff, "load_last_run", fake_load_last_run)
    monkeypatch.setattr(main_mod.handoff, "read_report", lambda path: "# REPORT\n\nSUCCESS\n")
    monkeypatch.setattr(main_mod.handoff, "git_snapshot", lambda cwd: {"commit": "abc123"})
    monkeypatch.setattr(main_mod.handoff, "build_handoff", lambda last, text, closure: f"HANDOFF::{last.task_id}::{text}")

    def fake_clipboard_set_text(tk_root, text):
        assert tk_root is root
        written.append(text)
        return True

    monkeypatch.setattr(ui_mod, "clipboard_set_text", fake_clipboard_set_text)

    bridge = main_mod.Bridge.__new__(main_mod.Bridge)
    bridge.root = root

    assert bridge._copy_last_report() is True, "复制成功必须返回 True"
    assert written == ["HANDOFF::RW024-BRIDGE::# REPORT\n\nSUCCESS\n"], "handoff payload 必须写入剪贴板"
    assert modal_spy["info"] == [] and modal_spy["error"] == [], "Bridge 复制路径零 modal"


def test_bridge_copy_last_report_failure_returns_false_no_modal(ui_root, monkeypatch, modal_spy):
    root = ui_root
    monkeypatch.setattr(main_mod.handoff, "load_last_run", lambda: SimpleNamespace(
        task_id="RW024-BRIDGE-F", report_path=r"C:\out\REPORT.md", task_path=None,
    ))
    monkeypatch.setattr(main_mod.handoff, "read_report", lambda path: "text")
    monkeypatch.setattr(main_mod.handoff, "git_snapshot", lambda cwd: {})
    monkeypatch.setattr(main_mod.handoff, "build_handoff", lambda last, text, closure: "payload")
    monkeypatch.setattr(ui_mod, "clipboard_set_text", lambda tk_root, text: False)  # 真实 clipboard write 失败

    bridge = main_mod.Bridge.__new__(main_mod.Bridge)
    bridge.root = root

    assert bridge._copy_last_report() is False, "clipboard 写失败必须返回 False"
    assert modal_spy["info"] == [] and modal_spy["error"] == [], "失败也只走窗内就地反馈"


def test_bridge_copy_last_report_no_last_run_returns_false(ui_root, monkeypatch, modal_spy):
    root = ui_root
    monkeypatch.setattr(main_mod.handoff, "load_last_run", lambda: None)
    bridge = main_mod.Bridge.__new__(main_mod.Bridge)
    bridge.root = root
    assert bridge._copy_last_report() is False
    assert modal_spy["info"] == [] and modal_spy["error"] == []


# ========== FIX-001 G. 反馈计时器到期 → 恢复「复制报告」（临时反馈） ==========

def test_g_timer_restores_copy_report_label(ui_root, monkeypatch):
    root = ui_root
    monkeypatch.setattr(ui_mod, "COPY_FEEDBACK_MS", 100)
    ui_mod.show_finished(root, "RW024-G", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    _button(win, "复制报告").invoke()
    _pump(root)

    assert "已复制 ✓" in _button_texts(win), "复制成功必须先显示「已复制 ✓」"

    time.sleep(0.25)  # 跨过 100ms 反馈期
    _pump(root)

    assert _button(win, "复制报告") is not None, "timer 到期后按钮必须恢复「复制报告」"
    assert "已复制 ✓" not in _button_texts(win), "「已复制 ✓」不得永久停留"
    assert "已复制 ✓" not in _label_texts(win), "窗内反馈标签一并恢复"
    assert _find_finished_window(root) is win, "恢复后主窗口仍保持打开"


# ========== FIX-001 H. 反馈期内重复复制 → 再次执行 + 计时器刷新 ==========

def test_h_repeat_copy_before_timer_resets_feedback(ui_root, monkeypatch):
    root = ui_root
    monkeypatch.setattr(ui_mod, "COPY_FEEDBACK_MS", 200)
    calls = []
    ui_mod.show_finished(root, "RW024-H", r"C:\out\REPORT.md", lambda: calls.append(1) or True)
    win = _find_finished_window(root)
    toplevels_before = len(_find_toplevels(root))

    _button(win, "复制报告").invoke()
    _pump(root)
    time.sleep(0.12)  # 第一次 timer（200ms）尚未到期
    second = _button(win, "已复制 ✓")
    assert second is not None, "反馈期内按钮仍可点击"
    second.invoke()  # timer 到期前再次复制
    _pump(root)

    assert calls == [1, 1], "每次点击都必须再次执行复制"
    assert len(_find_toplevels(root)) == toplevels_before, "重复复制不得创建第二窗口"

    time.sleep(0.12)  # 已过第一次 deadline（200ms），第二次刷新后（+200ms）尚未到期
    _pump(root)
    assert "已复制 ✓" in _button_texts(win), "timer 被刷新：第一次 deadline 过后反馈仍在显示"

    time.sleep(0.35)  # 跨过第二次 deadline
    _pump(root)
    assert _button(win, "复制报告") is not None, "刷新后的 timer 到期恢复「复制报告」"


# ========== FIX-001 I. 窗口在 timer 到期前关闭 → after 回调无异常、不重建窗口 ==========

def test_i_window_close_before_timer_no_exception(ui_root, monkeypatch):
    root = ui_root
    monkeypatch.setattr(ui_mod, "COPY_FEEDBACK_MS", 100)
    ui_mod.show_finished(root, "RW024-I", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    _button(win, "复制报告").invoke()
    _pump(root)

    close_btn = _button(win, "关闭")
    close_btn.invoke()  # timer 到期前显式关闭窗口
    _pump(root)

    time.sleep(0.25)  # 跨过 timer deadline：after 回调此时触发，不得抛异常
    _pump(root)  # 若回调抛 TclError/重建窗口，此处会失败

    assert _find_finished_window(root) is None, "关闭后不得重建完成窗口"
    assert _find_toplevels(root) == [], "关闭后无残留窗口"


# ========== FIX-001 J. backlog RW-024 状态与当前实现一致 ==========

def test_j_backlog_rw024_matches_implementation():
    """RW-024 单一可信当前状态：SOLVED + 完成态 Current Implementation +
    Remaining Gap=NONE + Decision 不再「只登记，不实现」。"""
    backlog = (
        Path(__file__).resolve().parents[1]
        / "docs" / "internal" / "AAF_MASTER_BACKLOG.md"
    )
    text = backlog.read_text(encoding="utf-8")

    m = re.search(r"## RW-024 — .*?(?=\n## RW-|\Z)", text, re.S)
    assert m, "backlog 必须存在 RW-024 条目"
    section = m.group(0)

    assert "SOLVED" in section, "RW-024 Status 必须为 SOLVED"
    assert "本任务只登记，不实现" not in section, "Decision 不得保留「只登记，不实现」登记态"
    assert re.search(r"Remaining Gap\s*\|\s*\*\*NONE\*\*", section), (
        "Remaining Gap 必须为 NONE（无 blocking gap）"
    )
    # Current Implementation 描述当前完成态：单窗 + 窗内临时反馈 + 恢复动作语义
    assert "临时" in section and "恢复「复制报告」" in section, (
        "Current Implementation 必须描述「已复制 ✓」为临时反馈并恢复「复制报告」"
    )
    assert "不弹第二 modal" in section or "不弹第二个 modal" in section, (
        "Current Implementation 必须保持无第二 modal 约束"
    )


# ========== K. 普通回归隔离：完成窗口不得映射到真实桌面 ==========

def _visible_toplevels(root: tk.Tk) -> list[tk.Toplevel]:
    return [w for w in _find_toplevels(root) if w.winfo_viewable()]


def test_k_normal_run_toplevels_never_visible(ui_root, modal_spy):
    """AAF-RUNTIME-UX-GUI-TEST-LEAK-001：普通 pytest 回归中，show_finished
    创建的完成窗口必须保持 withdrawn——逻辑上存在（可查找、可按钮 invoke），
    但绝不映射到真实桌面，杜绝「任务已完成」窗口闪现。

    该隔离是测试侧行为（ui_root fixture 的 _WithdrawnToplevel），
    生产 bridge/ui.show_finished 的正式可见行为不受影响。
    """
    root = ui_root
    ui_mod.show_finished(root, "RW024-K", r"C:\out\REPORT.md", lambda: True)
    win = _find_finished_window(root)
    assert win is not None, "测试逻辑仍能找到完成窗口（窗口未被删除）"
    _pump(root)

    # 窗口存在且可交互，但处于 withdrawn 状态：不向真实桌面显示
    assert str(win.state()) == "withdrawn", "完成窗口必须处于 withdrawn 状态"
    assert not win.winfo_viewable(), "普通回归中完成窗口不得映射到真实桌面"

    # 复制交互后仍无任何可见 Toplevel；窗口保持打开，成功路径仍零 modal
    _button(win, "复制报告").invoke()
    _pump(root)
    assert _visible_toplevels(root) == [], "普通回归不得产生任何可见 Toplevel"
    assert _find_finished_window(root) is win, "窗口仍保持打开（行为语义不变）"
    assert modal_spy["info"] == [] and modal_spy["error"] == [], "成功路径仍零 modal"

