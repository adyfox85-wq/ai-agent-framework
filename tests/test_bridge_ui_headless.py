"""AAF-v0.4-TASK-010-FIX-001 — Bridge UI headless controller 回归测试。

背景（FIX-UI-A-001）：TASK-010 全量 pytest 运行期间，真实桌面弹出
「任务已存在 — AAF Bridge」modal（Task ID: FIX-UI-A-001，pytest temp workspace），
等待人工关闭。根因：tests/test_phase_f_fix_001_ui.py 故意驱动**真实桌面窗口**
（真实 Tk Toplevel + grab_set + wait_window + 真实剪贴板），且普通 automated
suite 无结构性排除机制；harness 只处理预期窗口标题，状态偏差（如 duplicate 卡片
代替切换确认窗）导致窗口滞留桌面。

本文件 = 普通 automated suite 中替代 gui_e2e 文件的 headless 等价覆盖
（Requirements 9–14 / 21 G/H/I/J）：

- 驱动真实 `Bridge._handle_hotkey → _process_clipboard → intake → apply →
  launcher` 主链路（产品逻辑零改动）。
- UI 对话框全部 headless stub：show_workspace_switch / show_duplicate_card /
  show_info / show_error 记录调用并返回配置决策 —— 无 Toplevel、无 grab_set、
  无 wait_window、无 messagebox。
- 剪贴板为进程内缓冲 —— 不触碰真实用户剪贴板。
- 状态全部隔离：CONFIG_PATH / AAF_BRIDGE_DIR / launch registry 全在 tmp；
  绝不切换真实 Bridge current project / 绝不写真实 .aaf-bridge state。
- 无人值守：全部同步完成，不需要任何人工点击（关闭/取消/确定/切换并执行/
  查看状态/打开 REPORT）。
"""
from __future__ import annotations

import json
import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_agent_framework import task_lifecycle

from bridge import config as cfg_mod
from bridge import duplicate as dup_mod
from bridge import launch_registry as reg_mod
from bridge import main as main_mod
from bridge import task_io
from bridge import ui as ui_mod
from bridge.launcher import FrameworkLauncher

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DRY = REPO_ROOT / "tests" / "fixtures" / "run_dry.py"


# ---------------------------------------------------------------------------
# Headless stubs（零真实桌面交互）
# ---------------------------------------------------------------------------


class _DialogRecorder:
    """UI 对话框 stub：记录调用并返回配置决策；绝不创建真实窗口。"""

    def __init__(self):
        self.default_switch = True
        self.switch_calls = 0
        self.switch_plans = []
        self.dup_cards = []
        self.infos = []
        self.errors = []

    def show_workspace_switch(self, root, plan):
        self.switch_calls += 1
        self.switch_plans.append(plan)
        return self.default_switch

    def show_duplicate_card(self, root, info, on_view_status=None, on_open_report=None):
        self.dup_cards.append(info)
        self._last_callbacks = (on_view_status, on_open_report)

    def show_info(self, title, message):
        self.infos.append((title, message))

    def show_error(self, title, message):
        self.errors.append((title, message))


class _ClipboardBuffer:
    """进程内剪贴板：不触碰真实用户剪贴板。"""

    def __init__(self):
        self.buf = ""

    def set_text(self, root, text):
        self.buf = text
        return True

    def get_text(self, root):
        return self.buf


class _HeadlessBridge(main_mod.Bridge):
    """真实 Bridge 接线（_handle_hotkey / _process_clipboard），UI 全部 stub。
    与 gui_e2e harness 同构，但不创建/驱动任何真实 Tk 窗口。"""

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


def _task_text(ws: str, task_id: str, name: str = "FIX-001 headless 任务") -> str:
    return f"""AAF_TASK_BEGIN
Task ID: {task_id}
Task Name: {name}
Workspace: {ws}

Objective:
验证 Bridge UI 主链路 headless 无人值守执行

Acceptance:
1. 通过
AAF_TASK_END"""


def _make_launcher(bridge_dir: Path, done: threading.Event | None = None) -> FrameworkLauncher:
    def _on_finished(last, output):
        if done is not None:
            done.set()
    return FrameworkLauncher(
        run_py=RUN_DRY, registry_dir=bridge_dir / "launches", on_finished=_on_finished
    )


def _wait_until(fn, timeout: float = 60.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def _find_toplevels(root: tk.Tk) -> list:
    out = []
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.winfo_exists():
            out.append(w)
    return out


def _assert_no_real_windows(root: tk.Tk) -> None:
    """回归 21G/H：headless 全程不得创建任何真实 Toplevel / modal。"""
    assert _find_toplevels(root) == [], "headless 测试不得创建真实 Toplevel 窗口"


@pytest.fixture()
def headless_env(tmp_path, monkeypatch):
    """全部隔离：headless 对话框 + 进程内剪贴板 + tmp config/registry。"""
    root = tk.Tk()
    root.withdraw()
    bridge_dir = tmp_path / "aaf-bridge"
    bridge_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(bridge_dir))
    cfg_path = tmp_path / "cfg" / "config.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", cfg_path)
    dialogs = _DialogRecorder()
    clip = _ClipboardBuffer()
    monkeypatch.setattr(ui_mod, "show_workspace_switch", dialogs.show_workspace_switch)
    monkeypatch.setattr(ui_mod, "show_duplicate_card", dialogs.show_duplicate_card)
    monkeypatch.setattr(ui_mod, "show_info", dialogs.show_info)
    monkeypatch.setattr(ui_mod, "show_error", dialogs.show_error)
    monkeypatch.setattr(ui_mod, "clipboard_set_text", clip.set_text)
    monkeypatch.setattr(ui_mod, "clipboard_get_text", clip.get_text)
    env = SimpleNamespace(root=root, bridge_dir=bridge_dir, cfg_path=cfg_path,
                          dialogs=dialogs, clip=clip)
    yield env
    try:
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


def _ws(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _seed_known_switch(tmp_path, cfg_path: Path):
    cur = _ws(tmp_path, "cur")
    other = _ws(tmp_path, "known-proj")
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    cfg_mod.update_project("Known Project", str(other), cfg_path)
    cfg_mod.update_project("Current Project", str(cur), cfg_path)
    return cur, other


# ---------------------------------------------------------------------------
# G/H. 已知 workspace 切换（确认接受）→ 无人值守完成，零真实窗口
# ---------------------------------------------------------------------------


def test_headless_known_switch_accept_unattended_no_modal(tmp_path, headless_env):
    """G/H：确认切换 → 配置切换 + 任务落盘 + 执行完成；无真实窗口/无人工点击。"""
    cur, other = _seed_known_switch(tmp_path, headless_env.cfg_path)
    cfg = cfg_mod.load_config(headless_env.cfg_path)
    done = threading.Event()
    launcher = _make_launcher(headless_env.bridge_dir, done=done)
    bridge = _HeadlessBridge(headless_env.root, cfg, launcher)

    headless_env.clip.buf = _task_text(str(other), "FIX-UI-A-001")
    bridge._handle_hotkey()  # 同步完成（对话框为 stub）

    assert headless_env.dialogs.switch_calls == 1
    assert not bridge.busy
    on_disk = cfg_mod.load_config(headless_env.cfg_path)
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(other))
    assert on_disk["current_project"] == "Known Project"
    target = task_io.task_target_path(str(other), "FIX-UI-A-001")
    assert target.exists()
    assert _wait_until(lambda: launcher.state == "FINISHED")
    assert launcher.last.task_id == "FIX-UI-A-001"
    assert any(t == "任务已启动" for t, _ in headless_env.dialogs.infos)
    assert headless_env.dialogs.errors == []
    assert headless_env.dialogs.dup_cards == []
    _assert_no_real_windows(headless_env.root)
    assert headless_env.clip.buf  # 只通过进程内缓冲，真实剪贴板未触碰


def test_headless_known_switch_decline_zero_writes(tmp_path, headless_env):
    """H：拒绝切换 → 不切换、不落盘、不启动、无任何弹窗。"""
    cur, other = _seed_known_switch(tmp_path, headless_env.cfg_path)
    before = cfg_mod.load_config(headless_env.cfg_path)
    launcher = _make_launcher(headless_env.bridge_dir)
    bridge = _HeadlessBridge(headless_env.root, before, launcher)
    headless_env.dialogs.default_switch = False

    headless_env.clip.buf = _task_text(str(other), "FIX-UI-B-001")
    bridge._handle_hotkey()

    assert headless_env.dialogs.switch_calls == 1
    assert cfg_mod.load_config(headless_env.cfg_path) == before
    assert not task_io.task_target_path(str(other), "FIX-UI-B-001").exists()
    assert launcher.state == "IDLE"
    assert headless_env.dialogs.infos == []
    assert headless_env.dialogs.errors == []
    assert headless_env.dialogs.dup_cards == []
    _assert_no_real_windows(headless_env.root)


def test_headless_invalid_workspace_rejected_no_bypass(tmp_path, headless_env):
    """H：无效 workspace → 明确拒绝（error 捕获），无确认窗/无执行/无写入。"""
    cur = _ws(tmp_path, "cur")
    cfg_mod.update_project("Current Project", str(cur), headless_env.cfg_path)
    cfg = cfg_mod.load_config(headless_env.cfg_path)
    launcher = _make_launcher(headless_env.bridge_dir)
    bridge = _HeadlessBridge(headless_env.root, cfg, launcher)

    missing = tmp_path / "missing-dir"
    headless_env.clip.buf = _task_text(str(missing), "FIX-UI-D-001")
    bridge._handle_hotkey()

    assert headless_env.dialogs.errors, "必须明确拒绝（fail closed）"
    assert "不存在" in headless_env.dialogs.errors[0][1]
    assert headless_env.dialogs.switch_calls == 0
    assert headless_env.dialogs.dup_cards == []
    assert launcher.state == "IDLE"
    assert not task_io.task_target_path(str(missing), "FIX-UI-D-001").exists()
    _assert_no_real_windows(headless_env.root)


# ---------------------------------------------------------------------------
# G/I. Duplicate：状态卡片由 stub 捕获（无真实窗口）；第二 runner 不启动
# ---------------------------------------------------------------------------


def test_headless_duplicate_running_card_no_second_runner(tmp_path, headless_env):
    """G/I：RUNNING duplicate → 卡片内容正确捕获；registry 仍唯一；无弹窗。"""
    ws = _ws(tmp_path, "ws-e")
    cfg_mod.update_project("Project E", str(ws), headless_env.cfg_path)
    cfg = cfg_mod.load_config(headless_env.cfg_path)
    launcher = _make_launcher(headless_env.bridge_dir)

    # 真实 RUNNING 状态（registry PREPARED 条目 = ACTIVE_STATES 成员；不启真实进程）
    task_file = task_io.save_task(_task_text(str(ws), "FIX-UI-E-001"), str(ws), "FIX-UI-E-001")
    reg_mod.create_prepared(
        launch_id="LID-E-001", task_id="FIX-UI-E-001", workspace=str(ws),
        output_dir=str(ws / ".aaf" / "FIX-UI-E-001"),
        expected_runner_entry=str(task_file),
        expected_command_line=[str(task_file)],
        launcher_instance_id="headless-test",
        root=headless_env.bridge_dir / "launches",
    )
    bridge = _HeadlessBridge(headless_env.root, cfg, launcher)

    headless_env.clip.buf = _task_text(str(ws), "FIX-UI-E-001")
    bridge._handle_hotkey()

    assert len(headless_env.dialogs.dup_cards) == 1
    card = headless_env.dialogs.dup_cards[0]
    assert card.task_id == "FIX-UI-E-001"
    assert card.kind == dup_mod.KIND_RUNNING
    assert "不启动第二份 runner" in card.reason
    # 无第二 launch：registry 仍唯一活跃
    regs = reg_mod.list_launches(root=headless_env.bridge_dir / "launches")
    assert len(regs) == 1 and regs[0]["launch_id"] == "LID-E-001"
    assert launcher.state == "IDLE"
    assert headless_env.dialogs.infos == []
    assert headless_env.dialogs.errors == []
    _assert_no_real_windows(headless_env.root)


def test_headless_duplicate_terminal_card_artifacts_untouched(tmp_path, headless_env):
    """G/I：已完成 duplicate → 卡片含 REPORT 路径；历史 artifacts 不被覆盖。"""
    ws = _ws(tmp_path, "ws-f")
    cfg_mod.update_project("Project F", str(ws), headless_env.cfg_path)
    cfg = cfg_mod.load_config(headless_env.cfg_path)
    launcher = _make_launcher(headless_env.bridge_dir)

    task_dir = ws / ".aaf" / "FIX-UI-F-001"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "REPORT.md").write_text("# REPORT\n\n## Current Status\nSUCCESS\n", encoding="utf-8")
    (task_dir / "run.json").write_text(
        json.dumps({"status": "SUCCESS", "task_id": "FIX-UI-F-001"}), encoding="utf-8"
    )
    task_lifecycle.finalize_terminal(
        task_dir, task_id="FIX-UI-F-001", status="SUCCESS",
        task_path=str(ws / ".aaf" / "tasks" / "active" / "FIX-UI-F-001.md"),
        workspace=str(ws), report_path=str(task_dir / "REPORT.md"),
        stage="COMPLETED", phase_state="SUCCESS",
    )
    active = task_io.task_target_path(str(ws), "FIX-UI-F-001")
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(_task_text(str(ws), "FIX-UI-F-001"), encoding="utf-8")
    before = {str(p.relative_to(task_dir)): p.read_bytes() for p in task_dir.rglob("*") if p.is_file()}
    before_active = active.read_bytes()

    bridge = _HeadlessBridge(headless_env.root, cfg, launcher)
    headless_env.clip.buf = _task_text(str(ws), "FIX-UI-F-001")
    bridge._handle_hotkey()

    assert len(headless_env.dialogs.dup_cards) == 1
    card = headless_env.dialogs.dup_cards[0]
    assert card.kind == dup_mod.KIND_COMPLETED
    assert card.report_path and str(card.report_path).endswith("REPORT.md")
    after = {str(p.relative_to(task_dir)): p.read_bytes() for p in task_dir.rglob("*") if p.is_file()}
    assert after == before
    assert active.read_bytes() == before_active
    assert launcher.state == "IDLE"
    assert headless_env.dialogs.infos == []
    _assert_no_real_windows(headless_env.root)


def test_headless_running_task_blocks_cross_workspace(tmp_path, headless_env):
    """G：launcher RUNNING + 跨 workspace 提交 → 拒绝；当前任务不受影响。"""
    cur = _ws(tmp_path, "cur-g")
    other = _ws(tmp_path, "other-g")
    cfg_mod.update_project("Current Project", str(cur), headless_env.cfg_path)
    cfg = cfg_mod.load_config(headless_env.cfg_path)
    launcher = _make_launcher(headless_env.bridge_dir)

    class _RunningLauncher:
        state = "RUNNING"
        current = SimpleNamespace(task_id="FIX-UI-G-RUN")

    bridge = _HeadlessBridge(headless_env.root, cfg, _RunningLauncher())
    headless_env.clip.buf = _task_text(str(other), "FIX-UI-G-SW")
    bridge._handle_hotkey()

    assert headless_env.dialogs.errors, "必须明确拒绝"
    assert headless_env.dialogs.errors[0][0] == "当前任务正在运行"
    assert headless_env.dialogs.switch_calls == 0
    assert not task_io.task_target_path(str(other), "FIX-UI-G-SW").exists()
    assert cfg_mod.load_config(headless_env.cfg_path)["current_workspace"] == str(cur)
    assert headless_env.dialogs.infos == []
    _assert_no_real_windows(headless_env.root)


# ---------------------------------------------------------------------------
# J. 热键冲突路径：不注册真实热键、不弹真实桌面 modal
# ---------------------------------------------------------------------------


class _StubRoot:
    """极简 tk root 桩（rw012 同款；不触 tkinter）。"""

    def __init__(self):
        self.afters = []

    def after(self, ms, callback=None):
        self.afters.append((ms, callback))


def test_headless_hotkey_conflict_no_real_modal(monkeypatch):
    """J. RegisterHotKey failure（热键冲突）→ error 被 stub 捕获，零真实 modal。"""
    created = []

    class _FailingListener:
        def __init__(self, mods, vk, on_hotkey, hotkey_id):
            self._err = RuntimeError("热键被占用")
            self._args = (mods, vk, hotkey_id)
            created.append(self)

        def start(self):
            pass

        def wait_ready(self, timeout):
            return True

        def is_ready(self):
            return True

        def error(self):
            return self._err

        def is_alive(self):
            return False

        def request_stop(self):
            pass

        def stop(self, timeout=5.0):
            return True

    monkeypatch.setattr(main_mod, "HotkeyListener", _FailingListener)
    shown = []
    monkeypatch.setattr(main_mod.ui, "show_error", lambda *a, **k: shown.append(a))

    b = object.__new__(main_mod.Bridge)
    b.root = _StubRoot()
    b.cfg = {"hotkey": "ctrl+alt+a"}
    b.hotkey_id = 1
    b._on_hotkey = lambda: None
    b._shutting_down = False
    b._recovery = main_mod.HotkeyRecovery()
    b.listener = None
    b._pending_stop = None
    b._lifecycle_lock = threading.Lock()
    b.tray = None
    b._last_health = None

    b._apply_hotkey()

    assert len(created) == 1  # 每次尝试恰好一个 listener（无真实 RegisterHotKey）
    assert shown, "冲突错误必须可观察（被 stub 捕获，不弹真实 messagebox）"
    assert shown[0][0] == "AAF Bridge — 热键冲突"
