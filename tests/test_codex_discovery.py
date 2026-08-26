"""AI Agent Framework — Codex command discovery fallback 测试（real-world hotfix）。

覆盖：
1. codex 在 PATH → 使用 PATH（fallback 不介入）
2. codex 不在 PATH + 单一 fallback → 找到
3. codex 不在 PATH + 多版本目录 → 确定性选 mtime 最新
4. 无 candidate → MISSING_COMMAND
5. hermes resolution 不变（无 fallback，PATH 优先）
6. workbuddy resolution 不变（codebuddy，无 fallback）
7. 完整回归由全量 tests 覆盖（191 不降）
"""
import os
from pathlib import Path
import pytest

from ai_agent_framework import adapters


@pytest.fixture(autouse=True)
def _isolate_fallback_dir(tmp_path, monkeypatch):
    """把 fallback 目录隔离到临时目录（不读真实机器目录）。"""
    fake_root = tmp_path / "OpenAI" / "Codex" / "bin"
    fake_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(adapters, "CODEX_FALLBACK_DIR", fake_root)
    return fake_root


def _make_candidate(root: Path, name: str, mtime_epoch: float) -> Path:
    d = root / name
    d.mkdir(exist_ok=True)
    exe = d / "codex.exe"
    exe.write_bytes(b"MZ fake")
    os.utime(exe, (mtime_epoch, mtime_epoch))
    return exe


def test_codex_in_path_uses_path(monkeypatch):
    """codex 在 PATH → 直接用 PATH 结果（fallback 不介入）。"""
    fake_exe = Path("C:/fake-bin/codex.exe")
    monkeypatch.setattr(adapters.shutil, "which", lambda cmd, path: str(fake_exe))
    assert adapters._require("codex") == str(fake_exe)


def test_codex_missing_path_single_fallback(_isolate_fallback_dir):
    """codex 不在 PATH + 单一 fallback → 找到 fallback candidate。"""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(adapters.shutil, "which", lambda cmd, path: None)
    exe = _make_candidate(_isolate_fallback_dir, "aaa111", 1000.0)
    try:
        assert adapters._require("codex") == str(exe)
    finally:
        monkeypatch.undo()


def test_codex_missing_path_multi_candidates_newest(monkeypatch, _isolate_fallback_dir):
    """多版本目录 → 确定性选 mtime 最新（当前有效版本）。"""
    monkeypatch.setattr(adapters.shutil, "which", lambda cmd, path: None)
    _make_candidate(_isolate_fallback_dir, "110b3d66a02d864e", 1000.0)  # 旧版本目录
    new = _make_candidate(_isolate_fallback_dir, "8fffe69425752027", 2000.0)  # 当前版本目录
    found = adapters._require("codex")
    assert found == str(new)


def test_codex_missing_path_dir_without_exe_skipped(monkeypatch, _isolate_fallback_dir):
    """含目录但无 codex.exe 的候选被跳过。"""
    monkeypatch.setattr(adapters.shutil, "which", lambda cmd, path: None)
    (_isolate_fallback_dir / "54ee14df1f760d5e").mkdir()  # 只有 rg.exe 的旧目录
    with pytest.raises(RuntimeError, match="MISSING_COMMAND: codex"):
        adapters._require("codex")


def test_codex_no_candidate_missing_command(monkeypatch, _isolate_fallback_dir):
    """无 candidate → MISSING_COMMAND。"""
    monkeypatch.setattr(adapters.shutil, "which", lambda cmd, path: None)
    with pytest.raises(RuntimeError, match="MISSING_COMMAND: codex"):
        adapters._require("codex")


def test_hermes_resolution_unchanged(monkeypatch, _isolate_fallback_dir):
    """hermes 解析不变：PATH 优先，无 fallback（找不到 → MISSING_COMMAND）。"""
    calls = []

    def fake_which(cmd, path):
        calls.append(cmd)
        if cmd == "hermes":
            return "C:/fake-bin/hermes.exe"
        return None

    monkeypatch.setattr(adapters.shutil, "which", fake_which)
    assert adapters._require("hermes") == "C:/fake-bin/hermes.exe"
    assert calls == ["hermes"]  # 不调用 fallback


def test_workbuddy_resolution_unchanged(monkeypatch, _isolate_fallback_dir):
    """workbuddy（codebuddy）解析不变：PATH 优先，无 fallback。"""
    calls = []

    def fake_which(cmd, path):
        calls.append(cmd)
        if cmd == "codebuddy":
            return "C:/fake-bin/codebuddy.exe"
        return None

    monkeypatch.setattr(adapters.shutil, "which", fake_which)
    assert adapters._require("codebuddy") == "C:/fake-bin/codebuddy.exe"
    assert calls == ["codebuddy"]
