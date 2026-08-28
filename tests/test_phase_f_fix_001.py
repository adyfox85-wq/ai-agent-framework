"""AAF-v0.4-TASK-006-FIX-001 — 真实原子配置持久化（关闭 Codex blocker #1）。

覆盖（TASK req 1/2/3/8）：
- atomic save success：tmp + flush/fsync + os.replace 统一契约；无 tmp 残留
- temp write failure：抛 ConfigError，正式 config 保持原样，tmp 清理
- replace 前异常（json.dumps 序列化失败 / open 失败）：正式 config 不受影响
  （FIX-002：序列化失败同样抛 ConfigError，统一异常契约）
- replace failure：抛 ConfigError，正式 config 保持原样，tmp 清理
- update_project 复用同一 atomic contract（唯一写入点，无旁路）
- restart after successful switch：fresh load 恢复 current/workspace/recent
- restart after failed switch：旧配置仍可正常加载

不删除/不修改既有 Phase F tests（本文件只新增）。
"""
from __future__ import annotations

import builtins
import json
import os
from pathlib import Path

import pytest

from bridge import config as cfg_mod


def _ws(tmp_path: Path, name: str = "ws-a") -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _tmp_leftovers(d: Path) -> list[Path]:
    return [p for p in d.iterdir() if p.name.startswith(".") and ".tmp-" in p.name]


def _spy_replace(monkeypatch):
    """替换 os.replace 为 spy：记录 (tmp, dst) 后调用真实实现。"""
    real_replace = cfg_mod.os.replace
    calls = []

    def _spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(cfg_mod.os, "replace", _spy)
    return calls


# ---------- 1. atomic save success ----------

def test_atomic_save_uses_tmp_then_replace(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"
    p = cfg_dir / "config.json"
    calls = _spy_replace(monkeypatch)

    cfg_mod.save_config({"hotkey": "ctrl+alt+a", "current_project": "P", "current_workspace": "W"}, p)

    assert len(calls) == 1
    tmp_path_arg, dst = calls[0]
    # 临时文件与正式文件同目录（同卷 → 原子替换成立），且不是正式文件本身
    assert Path(tmp_path_arg).parent == cfg_dir
    assert Path(tmp_path_arg).name != "config.json"
    assert Path(tmp_path_arg).name.startswith(".config.json.tmp-")
    assert dst == str(p)
    # 落盘内容正确可复读
    on_disk = cfg_mod.load_config(p)
    assert on_disk["current_project"] == "P"
    assert on_disk["current_workspace"] == "W"
    # 无 tmp 残留
    assert _tmp_leftovers(cfg_dir) == []


def test_atomic_save_roundtrip_no_leftovers(tmp_path):
    cfg_dir = tmp_path / "cfg"
    p = cfg_dir / "config.json"
    cfg_mod.save_config({"hotkey": "ctrl+shift+b", "recent_projects": []}, p)
    assert cfg_mod.load_config(p)["hotkey"] == "ctrl+shift+b"
    # 目录中只有正式 config.json，无临时文件
    assert sorted(x.name for x in cfg_dir.iterdir()) == ["config.json"]


# ---------- 2. temp write failure ----------

def test_atomic_save_temp_write_failure_preserves_old(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    cfg_mod.save_config({"hotkey": "ctrl+alt+a", "current_project": "OLD", "current_workspace": "W0"}, p)
    old_bytes = p.read_bytes()

    real_open = builtins.open

    def _fail_tmp(file, *args, **kwargs):
        name = Path(file).name
        if name.startswith(".config.json.tmp-"):
            raise OSError("simulated temp write failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _fail_tmp)
    with pytest.raises(cfg_mod.ConfigError) as ei:
        cfg_mod.save_config({"hotkey": "ctrl+alt+a", "current_project": "NEW", "current_workspace": "W1"}, p)
    assert "保存失败" in str(ei.value)
    # 正式 config 未被破坏（原字节不变）
    assert p.read_bytes() == old_bytes
    assert cfg_mod.load_config(p)["current_project"] == "OLD"
    assert _tmp_leftovers(p.parent) == []


# ---------- 3. replace 前异常（json.dumps 序列化失败） ----------

def test_atomic_save_json_dump_error_touches_nothing(tmp_path):
    """序列化失败 → ConfigError（统一契约，FIX-002）：旧 config 字节级保留、零 tmp。

    覆盖两类 json.dumps 异常：不可序列化对象（TypeError）与循环引用（ValueError）。
    """
    p = tmp_path / "config.json"
    cfg_mod.save_config({"hotkey": "ctrl+alt+a"}, p)
    old_bytes = p.read_bytes()
    circular = []
    circular.append(circular)
    for bad in ({"unserializable": object()}, circular):
        with pytest.raises(cfg_mod.ConfigError) as ei:
            cfg_mod.save_config(bad, p)
        assert "序列化" in str(ei.value)
        # 旧 config 未被破坏（原字节不变）；无 tmp 残留（未触碰文件系统）
        assert p.read_bytes() == old_bytes
        assert _tmp_leftovers(p.parent) == []


# ---------- 4. replace failure ----------

def test_atomic_save_replace_failure_preserves_old(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    cfg_mod.save_config({"hotkey": "ctrl+alt+a", "current_project": "OLD", "current_workspace": "W0"}, p)
    old_bytes = p.read_bytes()

    def _fail_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(cfg_mod.os, "replace", _fail_replace)
    with pytest.raises(cfg_mod.ConfigError):
        cfg_mod.save_config({"hotkey": "ctrl+alt+a", "current_project": "NEW", "current_workspace": "W1"}, p)
    # 正式 config 保持原样；tmp 已清理（不留半截文件）
    assert p.read_bytes() == old_bytes
    assert cfg_mod.load_config(p)["current_project"] == "OLD"
    assert _tmp_leftovers(p.parent) == []


def test_atomic_save_replace_failure_when_no_old_config(tmp_path, monkeypatch):
    """首次保存时 replace 失败 → 不留下任何正式 config / tmp 残留。"""
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfg_mod.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(cfg_mod.ConfigError):
        cfg_mod.save_config({"hotkey": "ctrl+alt+a"}, p)
    assert not p.exists()
    assert _tmp_leftovers(p.parent) == []


# ---------- 5. update_project 复用统一 atomic contract（无旁路） ----------

def test_update_project_uses_atomic_contract(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg" / "config.json"
    ws = _ws(tmp_path)
    calls = _spy_replace(monkeypatch)

    cfg_mod.update_project("Project A", str(ws), cfg_path)

    assert len(calls) == 1  # 与 save_config 同一 os.replace 路径
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_project"] == "Project A"
    assert on_disk["current_workspace"] == str(ws)
    assert _tmp_leftovers(cfg_path.parent) == []


def test_update_project_failure_preserves_old_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg" / "config.json"
    old_ws = _ws(tmp_path, "old-ws")
    new_ws = _ws(tmp_path, "new-ws")
    cfg_mod.update_project("Old Project", str(old_ws), cfg_path)

    monkeypatch.setattr(cfg_mod.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(cfg_mod.ConfigError):
        cfg_mod.update_project("New Project", str(new_ws), cfg_path)

    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_project"] == "Old Project"
    assert cfg_mod.same_workspace(on_disk["current_workspace"], str(old_ws))
    assert _tmp_leftovers(cfg_path.parent) == []


# ---------- 6. restart recovery ----------

def test_restart_after_successful_switch(tmp_path):
    """成功切换 → 「重启」后（fresh load）current/workspace/recent 全部恢复一致。"""
    cfg_path = tmp_path / "cfg" / "config.json"
    a = _ws(tmp_path, "proj-a")
    b = _ws(tmp_path, "proj-b")
    cfg_mod.update_project("Project A", str(a), cfg_path)
    cfg_mod.update_project("Project B", str(b), cfg_path)  # 切换
    cfg_mod.update_project("Project A2", str(a), cfg_path)  # 再切回（recent 置顶去重）

    # Bridge restart = 零内存 fresh load（唯一持久化通道 = config.json）
    restored = cfg_mod.load_config(cfg_path)
    assert restored["current_project"] == "Project A2"
    assert cfg_mod.same_workspace(restored["current_workspace"], str(a))
    recent = restored["recent_projects"]
    assert len(recent) == 2
    assert recent[0]["name"] == "Project A2" and cfg_mod.same_workspace(recent[0]["workspace"], str(a))
    assert recent[1]["name"] == "Project B" and cfg_mod.same_workspace(recent[1]["workspace"], str(b))
    # known_workspaces 也从持久化恢复
    assert cfg_mod.known_workspaces(cfg_path)[0] == str(a)


def test_restart_after_failed_switch(tmp_path, monkeypatch):
    """失败写入 → 「重启」后旧配置仍可正常加载（Requirements #6/#13 保证）。"""
    cfg_path = tmp_path / "cfg" / "config.json"
    a = _ws(tmp_path, "proj-a")
    b = _ws(tmp_path, "proj-b")
    cfg_mod.update_project("Project A", str(a), cfg_path)
    before = cfg_mod.load_config(cfg_path)

    monkeypatch.setattr(cfg_mod.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(cfg_mod.ConfigError):
        cfg_mod.update_project("Project B", str(b), cfg_path)

    # 重启后（fresh load）：旧配置完整可读，recent_projects 与切换前一致
    restored = cfg_mod.load_config(cfg_path)
    assert restored == before
    assert restored["current_project"] == "Project A"
    assert cfg_mod.same_workspace(restored["current_workspace"], str(a))
    assert len(restored["recent_projects"]) == 1
    assert _tmp_leftovers(cfg_path.parent) == []


# ---------- 7. 完整性：持久化 JSON 可解析且字段齐全 ----------

def test_atomic_written_config_is_complete_json(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    ws = _ws(tmp_path)
    cfg_mod.update_project("Complete", str(ws), cfg_path)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    for key in ("hotkey", "current_project", "current_workspace", "force_cancel_soft_timeout", "recent_projects"):
        assert key in raw
