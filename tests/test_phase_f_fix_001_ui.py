"""AAF-v0.4-TASK-006-FIX-001 — 真实 Bridge/UI 交互路径验收（关闭 Codex blocker #2）。

⚠️ GUI E2E（manual/交互式）：本文件故意驱动**真实桌面窗口**（真实 Tk
Toplevel + 真实剪贴板往返 + 真实按钮 invoke），需要交互式桌面，被 pytest 标记为
``gui_e2e`` 并从普通 automated suite 中排除（见 pytest.ini addopts）。
运行方式：``pytest -m gui_e2e tests/test_phase_f_fix_001_ui.py``
（AAF-v0.4-TASK-010-FIX-001：FIX-UI-A-001 真实桌面弹窗事件根因定位后登记；
普通 automated 等价覆盖见 tests/test_bridge_ui_headless.py）。

不是只调用 plan_submission / apply_submission / launcher 的纯函数验证，而是
驱动**真实 Bridge UI 接线**：真实 tk.Tk root + 真实剪贴板往返 + 真实
`Bridge._handle_hotkey → _process_clipboard` + 真实 `ui.show_workspace_switch`
确认窗 / `ui.show_duplicate_card` 状态卡片（真实 Toplevel、真实 Label/Button），
由确定性 harness 检查窗口内容并点击真实按钮。

覆盖（TASK req 5 A–H）：
A. Known workspace switch → 确认窗出现 + 正确显示当前/目标项目/Workspace → 确认后切换并执行
B. User rejects switch → 不切换、不保存目标 config、不执行任务
C. Unknown workspace → 明确确认前不得执行（取消零写入）；确认后才执行
D. Invalid workspace → 明确拒绝（show_error 清晰原因）+ 无确认窗 / 无绕过执行路径
E. Duplicate RUNNING → 状态卡片（执行中）→ 第二 runner 不启动
F. Duplicate terminal → 状态卡片（已完成 + REPORT 路径）→ 历史 artifacts 不被覆盖
G. RUNNING task + cross-workspace submission → 切换拒绝（当前任务正在运行）→ 当前任务不受影响
H. Bridge restart → current project 正确恢复 → duplicate protection 仍有效

仅 patch：messagebox（show_info/show_error，模态阻塞）捕获参数、CONFIG_PATH 隔离
（测试 tmp 目录）、AAF_BRIDGE_DIR（registry 隔离）。确认窗/卡片本身全部真实。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_agent_framework import task_lifecycle

from bridge import config as cfg_mod
from bridge import duplicate as dup_mod
from bridge import main as main_mod
from bridge import task_io
from bridge import ui as ui_mod
from bridge.launcher import FrameworkLauncher

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DRY = REPO_ROOT / "tests" / "fixtures" / "run_dry.py"
DUMMY_RUNNER = REPO_ROOT / "tests" / "fixtures" / "dummy_runner.py"

# FIX-001：真实桌面 GUI E2E —— 从普通 automated suite 排除（pytest.ini addopts）
pytestmark = pytest.mark.gui_e2e

WIN_SWITCH = "切换项目确认 — AAF Bridge"
WIN_DUP = "任务已存在 — AAF Bridge"


def _task_text(ws: str, task_id: str, name: str = "FIX-001 UI 任务") -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: {name}
Workspace: {ws}

Objective:
验证真实 Bridge UI 交互路径

Acceptance:
1. 通过
AAF_TASK_END"""


def _ws(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _taskkill(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        pass


def _wait_until(fn, timeout: float = 90.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _hash_dir(d: Path) -> dict[str, str]:
    return {str(p.relative_to(d)): p.read_bytes().hex() for p in sorted(d.rglob("*")) if p.is_file()}


# ---------- 真实 UI harness ----------

class _BridgeUIHarness(main_mod.Bridge):
    """真实 Bridge UI 接线 harness：保留真实 _handle_hotkey / _process_clipboard /
    _show_duplicate_card 与真实 ui.show_workspace_switch / show_duplicate_card 弹窗，
    仅把 __init__ 换成最小状态（不注册热键 / Tray / 状态窗口，避免真实全局副作用）。

    状态窗口 / REPORT 打开回调记录调用（_open_status_window / _open_report_path
    与真实 Bridge 同签名，由 duplicate 卡片真实接线调用）。
    """

    def __init__(self, root: tk.Tk, cfg: dict, launcher: FrameworkLauncher):
        self.root = root
        self.cfg = cfg
        self.launcher = launcher
        self.busy = False
        self.status_views = 0
        self.report_opens: list[str] = []

    def _open_status_window(self) -> None:
        self.status_views += 1

    def _open_report_path(self, report_path: str) -> None:
        self.report_opens.append(report_path)


def _all_widgets(w):
    for child in w.winfo_children():
        yield child
        yield from _all_widgets(child)


def _find_window(root: tk.Tk, title: str):
    for w in root.winfo_children():
        try:
            if isinstance(w, tk.Toplevel) and w.winfo_exists() and str(w.title()) == title:
                return w
        except tk.TclError:
            continue
    return None


def _widget_texts(w: tk.Toplevel) -> list[str]:
    out = []
    for c in _all_widgets(w):
        try:
            cls = c.winfo_class()
            if cls == "Label":
                out.append(str(c.cget("text")))
            elif cls == "Button":
                out.append(f"[{c.cget('text')}]")
        except tk.TclError:
            continue
    return out


def _click(w: tk.Toplevel, text: str) -> bool:
    for c in _all_widgets(w):
        try:
            if c.winfo_class() == "Button" and str(c.cget("text")) == text:
                c.invoke()  # 真实按钮 command 回调
                return True
        except tk.TclError:
            continue
    return False


def _dump_evidence(title: str, texts: list[str]) -> None:
    print(f"\n[UI-EVIDENCE] window={title!r}")
    for t in texts:
        print(f"  {t}")


@pytest.fixture()
def ui_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def ui_env(tmp_path, monkeypatch, ui_root):
    """CONFIG_PATH / registry / messagebox 全部隔离；真实窗口与真实剪贴板保留。"""
    bridge_dir = tmp_path / "aaf-bridge"
    bridge_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(bridge_dir))
    cfg_path = tmp_path / "cfg" / "config.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", cfg_path)
    boxes = {"info": [], "error": []}
    monkeypatch.setattr(ui_mod, "show_info", lambda title, msg: boxes["info"].append((title, msg)))
    monkeypatch.setattr(ui_mod, "show_error", lambda title, msg: boxes["error"].append((title, msg)))
    return SimpleNamespace(root=ui_root, bridge_dir=bridge_dir, cfg_path=cfg_path, boxes=boxes)


def _make_launcher(bridge_dir: Path, run_py: Path = RUN_DRY,
                   done: threading.Event | None = None) -> FrameworkLauncher:
    def _on_finished(last, output):
        if done is not None:
            done.set()
    return FrameworkLauncher(run_py=run_py, registry_dir=bridge_dir / "launches", on_finished=_on_finished)


def _seed_known_switch(tmp_path, cfg_path: Path):
    """构造「已知但非当前」：current=cur，known=other。"""
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "known-proj")
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg_mod.update_project("Known Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    return cur, other


def _run_window_scenario(ui_env, bridge, task_text: str, expect_title: str,
                         on_window, click_text: str, deadline: float = 30.0) -> None:
    """剪贴板 → 真实 _handle_hotkey → 真实弹窗；harness 检查内容并点击真实按钮。"""
    root = ui_env.root
    assert ui_mod.clipboard_set_text(root, task_text), "真实剪贴板写入失败"
    done = threading.Event()

    def _poll():
        win = None
        try:
            win = _find_window(root, expect_title)
        except Exception:  # noqa: BLE001
            win = None
        if win is not None:
            try:
                on_window(win)
                assert _click(win, click_text), f"按钮 {click_text!r} 未找到"
            finally:
                done.set()
        else:
            root.after(25, _poll)

    root.after(10, bridge._handle_hotkey)
    root.after(60, _poll)
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline and not done.is_set():
        root.update()
        time.sleep(0.01)
    assert done.is_set(), f"真实窗口 {expect_title!r} 未被驱动（未出现或断言失败）"
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline and bridge.busy:
        root.update()
        time.sleep(0.01)
    assert not bridge.busy, "Bridge busy 未清除（处理链路卡住）"
    for _ in range(30):
        root.update()


def _run_no_window_scenario(ui_env, bridge, task_text: str, deadline: float = 30.0) -> None:
    """reject 路径：无弹窗；等待真实 _handle_hotkey 处理完成。

    busy 置位与清除可能发生在同一次 root.update() 内（外部循环看不到中间态），
    因此用 after 时序哨兵：probe 排在 handler 之后，handler 完成才会触发。
    """
    root = ui_env.root
    assert ui_mod.clipboard_set_text(root, task_text), "真实剪贴板写入失败"
    probe = threading.Event()
    root.after(10, bridge._handle_hotkey)
    root.after(50, probe.set)  # 仅在 handler 完整返回后触发
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline and not probe.is_set():
        root.update()
        time.sleep(0.01)
    assert probe.is_set(), "真实热键处理链从未完成"
    for _ in range(30):
        root.update()
    assert not bridge.busy


# ========== A. Known workspace switch：确认窗出现 + 内容正确 + 确认后切换并执行 ==========

def test_ui_a_known_switch_confirm_then_execute(tmp_path, ui_env, monkeypatch):
    cur, other = _seed_known_switch(tmp_path, ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    done = threading.Event()
    launcher = _make_launcher(ui_env.bridge_dir, done=done)
    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)

    seen = {}

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_SWITCH, texts)
        seen["texts"] = texts
        # 确认窗必须正确显示当前项目 / 目标项目 / Workspace（req A）
        joined = "\n".join(texts)
        assert "当前项目" in joined and "Current Project" in joined
        assert "目标项目" in joined and "Known Project" in joined
        assert "目标 Workspace" in joined and str(other) in joined
        assert "切换将修改 AAF Bridge 的项目设置" in joined  # §9.2.7 防漂移文案
        assert "Task ID" in joined and "FIX-UI-A-001" in joined

    _run_window_scenario(ui_env, bridge, _task_text(str(other), "FIX-UI-A-001"), WIN_SWITCH, on_window, "切换并执行")

    # 确认后才切换并执行（req A）
    on_disk = cfg_mod.load_config(ui_env.cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(other))
    assert on_disk["current_project"] == "Known Project"
    assert on_disk["recent_projects"][0]["workspace"] == str(other)
    # TASK.md 落在目标 workspace（不改写 Workspace）
    target = task_io.task_target_path(str(other), "FIX-UI-A-001")
    assert target.exists()
    # 真实执行（run_dry 子进程）完成
    assert _wait_until(lambda: launcher.state == "FINISHED")
    assert launcher.last.task_id == "FIX-UI-A-001"
    assert (other / ".aaf" / "FIX-UI-A-001" / "REPORT.md").exists()
    # 用户得到「任务已启动」提示
    assert any(t == "任务已启动" for t, _ in ui_env.boxes["info"])
    # 原子保存无 tmp 残留
    assert [p for p in ui_env.cfg_path.parent.iterdir() if ".tmp-" in p.name] == []
    assert seen["texts"], "确认窗内容未被检查"


# ========== B. 用户拒绝切换：不切换、不保存目标 config、不执行任务 ==========

def test_ui_b_reject_switch_writes_nothing(tmp_path, ui_env):
    cur, other = _seed_known_switch(tmp_path, ui_env.cfg_path)
    before = cfg_mod.load_config(ui_env.cfg_path)
    launcher = _make_launcher(ui_env.bridge_dir)
    bridge = _BridgeUIHarness(ui_env.root, before, launcher)

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_SWITCH, texts)
        joined = "\n".join(texts)
        assert "当前项目" in joined and "Known Project" in joined  # 确认窗先出现

    _run_window_scenario(ui_env, bridge, _task_text(str(other), "FIX-UI-B-001"), WIN_SWITCH, on_window, "取消")

    # 不切换：config 与切换前完全一致（含 recent_projects，未保存目标 config）
    after = cfg_mod.load_config(ui_env.cfg_path)
    assert after == before
    assert cfg_mod.same_workspace(after["current_workspace"], str(cur))
    # 不执行任务：无 TASK.md、无 .aaf 产物、launcher 未启动
    assert not task_io.task_target_path(str(other), "FIX-UI-B-001").exists()
    assert not (other / ".aaf").exists()
    assert launcher.state == "IDLE"
    assert not ui_env.boxes["info"]  # 没有「任务已启动」
    # 无 tmp 残留
    assert [p for p in ui_env.cfg_path.parent.iterdir() if ".tmp-" in p.name] == []


# ========== C. Unknown workspace：明确确认前不得执行；确认后才允许 ==========

def test_ui_c_unknown_requires_confirm(tmp_path, ui_env):
    cur = _ws(tmp_path, "cur")
    stranger = _ws(tmp_path, "brand-new")
    cfg_mod.update_project("Current Project", str(cur), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    launcher = _make_launcher(ui_env.bridge_dir)
    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_SWITCH, texts)
        joined = "\n".join(texts)
        # 陌生路径 fail-safe 警示文案（req C / §9.2.7）
        assert "首次出现" in joined and "确认前不会执行任何操作" in joined
        assert str(stranger) in joined

    # 第一轮：取消 → 不得执行
    _run_window_scenario(ui_env, bridge, _task_text(str(stranger), "FIX-UI-C-001"), WIN_SWITCH, on_window, "取消")
    assert not task_io.task_target_path(str(stranger), "FIX-UI-C-001").exists()
    assert not (stranger / ".aaf").exists()
    assert cfg_mod.load_config(ui_env.cfg_path)["current_workspace"] == str(cur)
    assert launcher.state == "IDLE"

    # 第二轮：明确确认（切换并执行）→ 才允许加入 recent + 执行
    done = threading.Event()
    launcher2 = _make_launcher(ui_env.bridge_dir, done=done)
    bridge2 = _BridgeUIHarness(ui_env.root, cfg_mod.load_config(ui_env.cfg_path), launcher2)
    _run_window_scenario(ui_env, bridge2, _task_text(str(stranger), "FIX-UI-C-002"), WIN_SWITCH, on_window, "切换并执行")
    assert _wait_until(lambda: launcher2.state == "FINISHED")
    on_disk = cfg_mod.load_config(ui_env.cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(stranger))
    assert on_disk["recent_projects"][0]["workspace"] == str(stranger)
    assert (stranger / ".aaf" / "FIX-UI-C-002" / "REPORT.md").exists()


# ========== D. Invalid workspace：明确拒绝，无绕过执行路径 ==========

def test_ui_d_invalid_workspace_rejected_no_bypass(tmp_path, ui_env):
    cur = _ws(tmp_path, "cur")
    cfg_mod.update_project("Current Project", str(cur), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    launcher = _make_launcher(ui_env.bridge_dir)
    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)

    missing = tmp_path / "missing-dir"
    _run_no_window_scenario(ui_env, bridge, _task_text(str(missing), "FIX-UI-D-001"))

    # 明确拒绝原因（fail closed，req D）
    assert ui_env.boxes["error"], "必须弹出拒绝提示"
    title, msg = ui_env.boxes["error"][0]
    assert "不存在" in msg
    # 无确认窗出现（无绕过执行路径）
    assert _find_window(ui_env.root, WIN_SWITCH) is None
    assert _find_window(ui_env.root, WIN_DUP) is None
    # 未执行、未写入
    assert not (missing).exists()
    assert not task_io.task_target_path(str(missing), "FIX-UI-D-001").exists()
    assert launcher.state == "IDLE"
    assert cfg_mod.load_config(ui_env.cfg_path)["current_workspace"] == str(cur)
    assert not ui_env.boxes["info"]


# ========== E. Duplicate RUNNING：清晰状态提示 + 第二 runner 不启动 ==========

def test_ui_e_duplicate_running_card_no_second_runner(tmp_path, ui_env, monkeypatch):
    ws = _ws(tmp_path, "ws-e")
    cfg_mod.update_project("Project E", str(ws), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "30")

    # 真实 RUNNING 任务（dummy runner sleep）
    task_file = task_io.save_task(_task_text(str(ws), "FIX-UI-E-001"), str(ws), "FIX-UI-E-001")
    launcher = _make_launcher(ui_env.bridge_dir, run_py=DUMMY_RUNNER)
    out_e = launcher.default_output_dir(str(ws), "FIX-UI-E-001")
    assert launcher.launch(task_file, str(ws), out_e, "FIX-UI-E-001")
    assert launcher.state == "RUNNING"
    lid = launcher._active_launch["FIX-UI-E-001"]

    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)
    try:
        def on_window(win):
            texts = _widget_texts(win)
            _dump_evidence(WIN_DUP, texts)
            joined = "\n".join(texts)
            assert "任务已存在" in joined
            assert "执行中（RUNNING）" in joined          # 清晰状态提示（req E）
            assert "不启动第二份 runner" in joined        # 卡片 reason
            assert "打开 REPORT" not in joined            # RUNNING 无 REPORT（§10.3）

        _run_window_scenario(ui_env, bridge, _task_text(str(ws), "FIX-UI-E-001"), WIN_DUP, on_window, "关闭")
        assert bridge.status_views == 0  # 未点[查看状态]（卡片关闭路径）
        # 第二 runner 不启动：registry 仍只有第一个活跃 launch
        from bridge import launch_registry as reg_mod
        regs = reg_mod.list_launches(root=ui_env.bridge_dir / "launches")
        assert len(regs) == 1 and regs[0]["launch_id"] == lid and regs[0]["state"] == "RUNNING"
        assert launcher.state == "RUNNING"  # 原任务不受影响
        assert not ui_env.boxes["info"]
    finally:
        from bridge import launch_registry as reg_mod
        reg = reg_mod.read_registry(lid, root=ui_env.bridge_dir / "launches")[0]
        _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
        assert _wait_until(lambda: launcher.state != "RUNNING", timeout=30)


# ========== F. Duplicate terminal：状态卡片 + REPORT 入口 + 历史 artifacts 不被覆盖 ==========

def test_ui_f_duplicate_terminal_card_no_overwrite(tmp_path, ui_env):
    ws = _ws(tmp_path, "ws-f")
    cfg_mod.update_project("Project F", str(ws), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    launcher = _make_launcher(ui_env.bridge_dir)
    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)

    # 构造真实已完成任务（canonical SUCCESS + REPORT + run.json 完整产物）
    task_dir = ws / ".aaf" / "FIX-UI-F-001"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    (task_dir / "run.json").write_text(json.dumps({"status": "SUCCESS", "task_id": "FIX-UI-F-001"}), encoding="utf-8")
    task_lifecycle.finalize_terminal(
        task_dir, task_id="FIX-UI-F-001", status="SUCCESS",
        task_path=str(ws / ".aaf" / "tasks" / "active" / "FIX-UI-F-001.md"),
        workspace=str(ws), report_path=str(task_dir / "REPORT.md"),
        stage="COMPLETED", phase_state="SUCCESS",
    )
    active = task_io.task_target_path(str(ws), "FIX-UI-F-001")
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(_task_text(str(ws), "FIX-UI-F-001"), encoding="utf-8")
    before = _hash_dir(task_dir)
    before_active = active.read_bytes()

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_DUP, texts)
        joined = "\n".join(texts)
        assert "任务已存在" in joined
        assert "已完成（SUCCESS）" in joined               # 清晰状态（req F）
        assert "需新 Task ID" in joined
        assert "REPORT 路径" in joined and str(task_dir / "REPORT.md") in joined

    # 点 [打开 REPORT] 验证卡片真实接线（harness 记录回调，不真开编辑器）
    _run_window_scenario(ui_env, bridge, _task_text(str(ws), "FIX-UI-F-001"), WIN_DUP, on_window, "打开 REPORT")
    assert bridge.report_opens == [str(task_dir / "REPORT.md")]

    # 历史 artifacts 未被覆盖（req F）；无新执行
    assert _hash_dir(task_dir) == before
    assert active.read_bytes() == before_active
    assert launcher.state == "IDLE"
    from bridge import launch_registry as reg_mod
    assert reg_mod.list_launches(root=ui_env.bridge_dir / "launches") == []
    assert not ui_env.boxes["info"]


# ========== G. RUNNING task + cross-workspace submission：切换拒绝 + 当前任务不受影响 ==========

def test_ui_g_running_blocks_cross_workspace(tmp_path, ui_env, monkeypatch):
    cur = _ws(tmp_path, "cur-g")
    other = _ws(tmp_path, "other-g")
    cfg_mod.update_project("Current Project", str(cur), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)
    monkeypatch.setenv("AAF_DUMMY_SLEEP", "30")

    task_file = task_io.save_task(_task_text(str(cur), "FIX-UI-G-RUN"), str(cur), "FIX-UI-G-RUN")
    launcher = _make_launcher(ui_env.bridge_dir, run_py=DUMMY_RUNNER)
    out_g = launcher.default_output_dir(str(cur), "FIX-UI-G-RUN")
    assert launcher.launch(task_file, str(cur), out_g, "FIX-UI-G-RUN")
    assert launcher.state == "RUNNING"
    lid = launcher._active_launch["FIX-UI-G-RUN"]

    bridge = _BridgeUIHarness(ui_env.root, cfg, launcher)
    try:
        # 跨 workspace 提交 → 拒绝切换（无确认窗）
        _run_no_window_scenario(ui_env, bridge, _task_text(str(other), "FIX-UI-G-SW"))
        assert ui_env.boxes["error"], "必须弹出拒绝提示"
        title, msg = ui_env.boxes["error"][0]
        assert title == "当前任务正在运行"                   # 清晰状态提示（req G）
        assert "不能切换项目" in msg
        assert _find_window(ui_env.root, WIN_SWITCH) is None
        # 不写入任何文件
        assert not task_io.task_target_path(str(other), "FIX-UI-G-SW").exists()
        assert cfg_mod.load_config(ui_env.cfg_path)["current_workspace"] == str(cur)
        # 当前任务不受影响：仍 RUNNING，registry 唯一活跃 launch 不变
        from bridge import launch_registry as reg_mod
        regs = [e for e in reg_mod.list_launches(root=ui_env.bridge_dir / "launches") if e.get("state") in reg_mod.ACTIVE_STATES]
        assert [e["launch_id"] for e in regs] == [lid]
        assert launcher.state == "RUNNING"
    finally:
        from bridge import launch_registry as reg_mod
        reg = reg_mod.read_registry(lid, root=ui_env.bridge_dir / "launches")[0]
        _taskkill(reg.get("launch_root_pid") or reg.get("runner_pid"))
        assert _wait_until(lambda: launcher.state != "RUNNING", timeout=30)


# ========== FIX-001 追加：确认切换后原子保存失败 → 显式报错、不静默、零写入 ==========

def test_ui_fix_config_save_failure_not_silent(tmp_path, ui_env, monkeypatch):
    """真实 UI：用户确认切换 → os.replace 失败 → 显式「配置保存失败」错误框；
    不静默声称切换成功；旧 config 保留；任务未启动。"""
    cur, other = _seed_known_switch(tmp_path, ui_env.cfg_path)
    before = cfg_mod.load_config(ui_env.cfg_path)
    launcher = _make_launcher(ui_env.bridge_dir)
    bridge = _BridgeUIHarness(ui_env.root, before, launcher)

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_SWITCH, texts)
        assert "Known Project" in "\n".join(texts)

    monkeypatch.setattr(cfg_mod.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("simulated replace failure")))
    _run_window_scenario(ui_env, bridge, _task_text(str(other), "FIX-UI-SAVE-FAIL"), WIN_SWITCH, on_window, "切换并执行")

    # 显式失败提示（不静默声称切换成功）
    assert ui_env.boxes["error"], "必须弹出配置保存失败提示"
    title, msg = ui_env.boxes["error"][0]
    assert title == "AAF Bridge — 配置保存失败"
    assert "未启动" in msg and "原配置保持不变" in msg
    # 旧 config 原样保留；无「任务已启动」提示
    assert cfg_mod.load_config(ui_env.cfg_path) == before
    assert not ui_env.boxes["info"]
    # 任务未启动、未落盘
    assert not task_io.task_target_path(str(other), "FIX-UI-SAVE-FAIL").exists()
    assert launcher.state == "IDLE"
    from bridge import launch_registry as reg_mod
    assert reg_mod.list_launches(root=ui_env.bridge_dir / "launches") == []
    # tmp 已清理
    assert [p for p in ui_env.cfg_path.parent.iterdir() if ".tmp-" in p.name] == []


# ========== H. Bridge restart：current project 恢复 + duplicate protection 仍有效 ==========

def test_ui_h_restart_recovers_project_and_duplicate_protection(tmp_path, ui_env):
    cur = _ws(tmp_path, "cur-h")
    other = _ws(tmp_path, "target-h")
    cfg_mod.update_project("Current Project", str(cur), ui_env.cfg_path)
    cfg = cfg_mod.load_config(ui_env.cfg_path)

    # 实例 A：真实 UI 确认切换 + 执行（目标项目为陌生 → confirm_unknown 确认窗）
    launcher_a = _make_launcher(ui_env.bridge_dir)
    bridge_a = _BridgeUIHarness(ui_env.root, cfg, launcher_a)

    def on_window(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_SWITCH, texts)
        assert "首次出现" in "\n".join(texts)

    _run_window_scenario(ui_env, bridge_a, _task_text(str(other), "FIX-UI-H-001"), WIN_SWITCH, on_window, "切换并执行")
    assert _wait_until(lambda: launcher_a.state == "FINISHED")
    # 收敛为真实 SUCCESS 终态（dry-run 保留 CREATED，这里显式 finalize 以便卡片展示已完成）
    task_dir = other / ".aaf" / "FIX-UI-H-001"
    task_lifecycle.finalize_terminal(
        task_dir, task_id="FIX-UI-H-001", status="SUCCESS",
        task_path=str(other / ".aaf" / "tasks" / "active" / "FIX-UI-H-001.md"),
        workspace=str(other), report_path=str(task_dir / "REPORT.md"),
        stage="COMPLETED", phase_state="SUCCESS",
    )

    # 实例 B = Bridge restart（零内存：cfg 从 config.json fresh load）
    cfg_b = cfg_mod.load_config(ui_env.cfg_path)
    assert cfg_mod.same_workspace(cfg_b["current_workspace"], str(other))
    assert cfg_b["current_project"] == "target-h"  # 陌生路径 → basename 展示名
    assert cfg_b["recent_projects"][0]["workspace"] == str(other)

    launcher_b = _make_launcher(ui_env.bridge_dir)
    bridge_b = _BridgeUIHarness(ui_env.root, cfg_b, launcher_b)
    before = _hash_dir(task_dir)

    def on_dup(win):
        texts = _widget_texts(win)
        _dump_evidence(WIN_DUP, texts)
        joined = "\n".join(texts)
        assert "已完成（SUCCESS）" in joined
        assert "REPORT 路径" in joined

    # restart 后 duplicate protection 仍有效（req H）：同 Task ID 拒绝 + 卡片
    _run_window_scenario(ui_env, bridge_b, _task_text(str(other), "FIX-UI-H-001"), WIN_DUP, on_dup, "关闭")
    assert _hash_dir(task_dir) == before                       # artifacts 未被动过
    from bridge import launch_registry as reg_mod
    regs = reg_mod.list_launches(root=ui_env.bridge_dir / "launches")
    assert len(regs) == 1 and regs[0]["state"] == "EXITED"     # 无第二次执行
    assert launcher_b.state == "IDLE"
