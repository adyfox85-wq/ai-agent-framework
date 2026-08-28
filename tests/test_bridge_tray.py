"""AAF Bridge — Phase B Tray / Background / Restart Lifecycle 测试。

覆盖（Phase B 最小范围，不创建真实 Tray 图标 / 不注册真实热键）：
- Tray 菜单规格（最小三项 + 健康信息行）
- 菜单事件映射
- Bridge health 判定（listener registered + loop alive）
- 重启命令构造（pythonw + scripts/start_bridge.pyw）
- 最小状态窗口内容行
- 单实例 mutex：防双开 / 释放后可再获取 / 旧实例退出后新实例接管（restart 交接）
"""
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from bridge import main as bridge_main
from bridge import tray as tray_mod

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- Tray 菜单规格 ----------


def test_menu_spec_contains_required_three_entries():
    spec = tray_mod.build_tray_menu_spec("正常运行")
    items = [(kind, label) for kind, label, _ in spec if kind == "item"]
    labels = [label for _, label in items]
    assert "打开状态窗口" in labels
    assert "重启 Bridge" in labels
    assert "退出 AAF" in labels
    # 最小三项，不多不少（Phase B 范围控制）
    assert len(items) == 3


def test_menu_spec_order_and_health_line():
    spec = tray_mod.build_tray_menu_spec("正常运行", "热键注册失败")
    assert spec[0][0] == "info"
    assert "状态：正常运行（热键注册失败）" in spec[0][1]
    # 第一项为灰显信息行，其余为分隔线/操作项
    kinds = [k for k, _, _ in spec]
    assert kinds[0] == "info"
    assert "sep" in kinds
    # 健康信息行在操作项之前
    info_idx = kinds.index("info")
    assert all(k != "info" for k in kinds[info_idx + 1 :])


def test_menu_event_mapping():
    assert tray_mod.menu_event_for_id(tray_mod.MENU_ID_OPEN) == tray_mod.EVENT_OPEN_STATUS
    assert tray_mod.menu_event_for_id(tray_mod.MENU_ID_RESTART) == tray_mod.EVENT_RESTART
    assert tray_mod.menu_event_for_id(tray_mod.MENU_ID_EXIT) == tray_mod.EVENT_EXIT
    assert tray_mod.menu_event_for_id(999) == ""


def test_event_namespace_prefixed_for_bridge_dispatch():
    # Bridge 事件循环按 "tray:" 前缀分派
    for ev in (tray_mod.EVENT_OPEN_STATUS, tray_mod.EVENT_RESTART, tray_mod.EVENT_EXIT):
        assert ev.startswith("tray:")


# ---------- Health 判定（§8 最小模型） ----------


class FakeListener:
    def __init__(self, error=None, alive=True, ready=True):
        self._error = error
        self._alive = alive
        self._ready = ready

    def error(self):
        return self._error

    def is_alive(self):
        return self._alive

    def is_ready(self):
        return self._ready


def test_health_ok_when_registered_and_alive():
    status, detail = bridge_main.classify_bridge_health(FakeListener(error=None, alive=True))
    assert status == bridge_main.HEALTH_OK
    assert "正常运行" in detail


def test_health_degraded_when_no_listener():
    status, detail = bridge_main.classify_bridge_health(None)
    assert status == bridge_main.HEALTH_DEGRADED
    assert "未注册" in detail


def test_health_degraded_when_registration_failed():
    status, _ = bridge_main.classify_bridge_health(FakeListener(error=RuntimeError("冲突"), alive=False))
    assert status == bridge_main.HEALTH_DEGRADED


def test_health_degraded_when_listener_thread_dead():
    status, detail = bridge_main.classify_bridge_health(FakeListener(error=None, alive=False))
    assert status == bridge_main.HEALTH_DEGRADED
    assert "已退出" in detail


# ---------- 重启命令构造 ----------


def test_build_restart_argv_uses_pythonw_and_start_script(monkeypatch, tmp_path):
    fake_dir = tmp_path / "venv" / "Scripts"
    fake_dir.mkdir(parents=True)
    fake_python = fake_dir / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    (fake_dir / "pythonw.exe").write_text("", encoding="utf-8")  # pythonw 存在 → 首选
    monkeypatch.setattr(sys, "executable", str(fake_python))
    argv = bridge_main.build_restart_argv()
    assert len(argv) == 2
    assert argv[0] == str(fake_python.with_name("pythonw.exe"))
    assert Path(argv[1]).name == "start_bridge.pyw"
    assert Path(argv[1]).parent.name == "scripts"


def test_build_restart_argv_fallback_when_no_pythonw(monkeypatch, tmp_path):
    # 无 pythonw.exe 时回退 sys.executable（Popen 侧用 CREATE_NO_WINDOW）
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(fake_python))
    argv = bridge_main.build_restart_argv()
    assert argv[0] == str(fake_python)
    assert Path(argv[1]).name == "start_bridge.pyw"


# ---------- 最小状态窗口内容 ----------


def test_build_status_rows_basic():
    cfg = {
        "hotkey": "ctrl+alt+a",
        "current_project": "AI Agent Framework",
        "current_workspace": r"D:\workspaces\proj",
    }
    rows = bridge_main.build_status_rows(cfg, ("OK", "正常运行"), None)
    labels = [label for label, _ in rows]
    assert labels == ["Bridge 状态", "热键", "当前项目", "当前 Workspace", "最近 Task"]
    values = dict(rows)
    assert values["Bridge 状态"] == "正常运行"
    assert values["热键"] == "Ctrl+Alt+A"
    assert values["最近 Task"] == "（无）"


def test_build_status_rows_degraded_shows_detail():
    cfg = {"hotkey": "ctrl+alt+a", "current_project": "", "current_workspace": ""}
    rows = bridge_main.build_status_rows(cfg, ("DEGRADED", "热键监听线程已退出"), None)
    values = dict(rows)
    assert values["Bridge 状态"] == "异常（热键监听线程已退出）"
    assert values["当前项目"] == "（未设置）"


def test_build_status_rows_last_run():
    cfg = {"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"}

    class FakeLast:
        task_id = "AAF-T1"
        result = "FINISHED"

    rows = bridge_main.build_status_rows(cfg, ("OK", "正常运行"), FakeLast())
    assert dict(rows)["最近 Task"] == "AAF-T1 — FINISHED"


# ---------- 单实例（真实进程级） ----------

_MUTEX_PROBE = (
    "import sys\n"
    "sys.path.insert(0, {repo_root!r})\n"
    "from bridge.main import SingleInstance\n"
    "g = SingleInstance(name={name!r}, retries={retries}, delay={delay})\n"
    "print('ACQUIRED' if g.acquire() else 'BUSY')\n"
)


def _run_probe(name: str, retries: int = 1, delay: float = 0.0) -> str:
    code = _MUTEX_PROBE.format(repo_root=str(REPO_ROOT), name=name, retries=retries, delay=delay)
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _unique_mutex() -> str:
    return f"Local\\AAF_Bridge_Test_{uuid.uuid4().hex}"


def test_single_instance_acquire_then_excludes_second_then_release():
    name = _unique_mutex()
    g = bridge_main.SingleInstance(name=name, retries=1, delay=0.0)
    assert g.acquire() is True
    try:
        assert _run_probe(name) == "BUSY"  # 第二实例被拒绝（防双开）
    finally:
        g.release()
    assert _run_probe(name) == "ACQUIRED"  # 释放后可重新获取


def test_single_instance_restart_handoff():
    """模拟 Restart Bridge：旧实例退出（释放 mutex）→ 新实例接管（不双开）。"""
    name = _unique_mutex()
    g = bridge_main.SingleInstance(name=name, retries=1, delay=0.0)
    assert g.acquire() is True
    code = _MUTEX_PROBE.format(repo_root=str(REPO_ROOT), name=name, retries=30, delay=0.3)
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    try:
        time.sleep(1.0)  # 子进程重试期间，父进程仍持有 mutex（子进程应看到 BUSY 状态）
        g.release()  # 模拟旧实例退出
        out, err = p.communicate(timeout=30)
        assert out.strip() == "ACQUIRED", err
    finally:
        if p.poll() is None:
            p.kill()
        g.release()


# ---------- 杂项 ----------


def test_tray_icon_struct_size_sanity():
    # x64 上 NOTIFYICONDATAW.cbSize == 980（Windows 官方值）；避免平台细节写死
    size = tray_mod.ctypes.sizeof(tray_mod.NOTIFYICONDATAW)
    assert 900 <= size <= 1100


def test_tray_icon_constructible_without_starting():
    events = []
    t = tray_mod.TrayIcon(on_event=events.append)
    assert t.is_alive() is False  # 未 start，不创建任何窗口/图标
    assert t.error() is None
