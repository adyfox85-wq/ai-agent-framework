"""Phase F（AAF-v0.4-TASK-006）— Workspace 校验 / 分类 / 切换持久化单元测试。

覆盖 TASK req 1–6：
- check_workspace：路径不存在 / 非目录 / 无权限 / malformed / 安全校验 → fail closed（req 5）
- classify_workspace：SAME（req 2）/ KNOWN（req 3）/ UNKNOWN（req 4）/ INVALID
- config.update_project：current_project / current_workspace / recent_projects 持久化（req 6）
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bridge import config as cfg_mod
from bridge import workspace as ws_mod

TASK_WS = "D:\\AdyAI\\ai-agent-framework"


def _ws(tmp_path: Path, name: str = "ws-a") -> Path:
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


# ---------- check_workspace（req 5：fail closed） ----------

def test_check_workspace_empty_fails():
    ok, reason = ws_mod.check_workspace("")
    assert not ok and "空" in reason


def test_check_workspace_whitespace_fails():
    ok, reason = ws_mod.check_workspace("   ")
    assert not ok


def test_check_workspace_control_char_fails():
    ok, reason = ws_mod.check_workspace("D:\\ws\x00bad")
    assert not ok and "NUL" in reason
    ok2, _ = ws_mod.check_workspace("D:\\ws\nbad")
    assert not ok2


def test_check_workspace_relative_fails():
    ok, reason = ws_mod.check_workspace("relative\\path")
    assert not ok and "绝对路径" in reason


def test_check_workspace_missing_path_fails(tmp_path):
    ok, reason = ws_mod.check_workspace(str(tmp_path / "not-exists"))
    assert not ok and "不存在" in reason


def test_check_workspace_file_not_dir_fails(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    ok, reason = ws_mod.check_workspace(str(f))
    assert not ok and "不是目录" in reason


def test_check_workspace_valid_dir_ok(tmp_path):
    ok, reason = ws_mod.check_workspace(str(_ws(tmp_path)))
    assert ok and reason == ""


def test_check_workspace_bridge_private_dir_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("AAF_BRIDGE_DIR", str(tmp_path / "aaf-bridge"))
    private = tmp_path / "aaf-bridge"
    private.mkdir(exist_ok=True)
    ok, reason = ws_mod.check_workspace(str(private))
    assert not ok and "安全校验" in reason
    # 深层包含 .aaf-bridge 段
    deep = tmp_path / "x" / "y" / ".aaf-bridge"
    deep.mkdir(parents=True)
    ok2, reason2 = ws_mod.check_workspace(str(deep))
    assert not ok2 and "安全校验" in reason2


# ---------- classify_workspace（req 2/3/4） ----------

def test_classify_same(tmp_path):
    ws = _ws(tmp_path)
    assert ws_mod.classify_workspace(str(ws), str(ws), []) == ws_mod.SAME


def test_classify_same_case_insensitive(tmp_path):
    ws = _ws(tmp_path)
    # Windows 大小写不敏感
    assert ws_mod.classify_workspace(str(ws).upper(), str(ws), []) == ws_mod.SAME


def test_classify_known(tmp_path):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "other")
    assert ws_mod.classify_workspace(str(other), str(cur), [str(other)]) == ws_mod.KNOWN


def test_classify_unknown(tmp_path):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "other")
    assert ws_mod.classify_workspace(str(other), str(cur), []) == ws_mod.UNKNOWN


def test_classify_invalid_missing(tmp_path):
    cur = _ws(tmp_path, "current")
    missing = tmp_path / "ghost"
    assert ws_mod.classify_workspace(str(missing), str(cur), []) == ws_mod.INVALID


def test_classify_invalid_empty():
    assert ws_mod.classify_workspace("", "D:\\x", []) == ws_mod.INVALID


# ---------- target_project_name ----------

def test_target_project_name_known(tmp_path):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "other")
    known = [{"name": "观微记 H5", "workspace": str(other), "last_used": "2026-08-28T10:00:00"}]
    assert ws_mod.target_project_name(str(other), "Current", str(cur), known) == "观微记 H5"


def test_target_project_name_basename_fallback(tmp_path):
    cur = _ws(tmp_path, "current")
    other = _ws(tmp_path, "guoxue-skills-lab")
    assert ws_mod.target_project_name(str(other), "Current", str(cur), []) == "guoxue-skills-lab"


def test_target_project_name_current(tmp_path):
    cur = _ws(tmp_path, "current")
    assert ws_mod.target_project_name(str(cur), "AI Agent Framework", str(cur), []) == "AI Agent Framework"


# ---------- config.update_project / recent_projects（req 6 持久化） ----------

def test_update_project_sets_current_and_recent(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    ws = _ws(tmp_path, "ws-a")
    cfg = cfg_mod.update_project("Project A", str(ws), cfg_path)
    assert cfg["current_project"] == "Project A"
    assert cfg["current_workspace"] == str(ws)
    recent = cfg["recent_projects"]
    assert len(recent) == 1
    assert recent[0]["name"] == "Project A"
    assert recent[0]["workspace"] == str(ws)
    assert "last_used" in recent[0]
    # 落盘可复读
    on_disk = cfg_mod.load_config(cfg_path)
    assert on_disk["current_project"] == "Project A"
    assert on_disk["current_workspace"] == str(ws)


def test_update_project_recent_dedup_and_order(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    a = _ws(tmp_path, "a")
    b = _ws(tmp_path, "b")
    cfg_mod.update_project("A", str(a), cfg_path)
    cfg_mod.update_project("B", str(b), cfg_path)
    cfg = cfg_mod.update_project("A2", str(a), cfg_path)  # 回到 A → 置顶 + 去重
    recent = cfg["recent_projects"]
    assert len(recent) == 2
    assert recent[0]["workspace"] == str(a)
    assert recent[1]["workspace"] == str(b)


def test_update_project_recent_cap_5(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    for i in range(7):
        ws = _ws(tmp_path, f"ws-{i}")
        cfg_mod.update_project(f"P{i}", str(ws), cfg_path)
    cfg = cfg_mod.load_config(cfg_path)
    assert len(cfg["recent_projects"]) == cfg_mod.RECENT_PROJECTS_LIMIT == 5
    assert cfg["recent_projects"][0]["workspace"].endswith("ws-6")


def test_known_workspaces_from_recent(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    a = _ws(tmp_path, "a")
    b = _ws(tmp_path, "b")
    cfg_mod.update_project("A", str(a), cfg_path)
    cfg_mod.update_project("B", str(b), cfg_path)
    known = cfg_mod.known_workspaces(cfg_path)
    assert str(b) in known
    assert str(a) in known  # 切换过的项目都在 recent_projects（SAME 优先判定，无冲突）
    # 顺序按 last_used 倒序：B 最新
    assert known[0] == str(b)


def test_update_project_preserves_other_config_keys(tmp_path):
    cfg_path = tmp_path / "cfg" / "config.json"
    a = _ws(tmp_path, "a")
    cfg_mod.save_config({"hotkey": "ctrl+alt+x", "current_project": "old", "current_workspace": "", "recent_projects": []}, cfg_path)
    cfg = cfg_mod.update_project("New", str(a), cfg_path)
    assert cfg["hotkey"] == "ctrl+alt+x"


def test_same_workspace_normalization():
    assert cfg_mod.same_workspace("D:\\a\\b\\c", "d:/a/b/c")
    assert not cfg_mod.same_workspace("D:\\a\\b", "D:\\a\\c")
    assert not cfg_mod.same_workspace("", "D:\\x")
