import os
import subprocess
from pathlib import Path

import pytest

from ai_agent_framework import subprocess_utils
from ai_agent_framework.adapters import build_prompt, run_agent


def test_validator_prompt_includes_task_and_previous_result(tmp_path: Path):
    task = 'TASK BODY'
    previous = {'hermes': 'HERMES RESULT'}
    p = build_prompt('workbuddy', task, previous)
    assert 'TASK BODY' in p
    assert 'HERMES RESULT' in p
    assert '独立复核' in p


def test_workbuddy_long_prompt_uses_stdin_not_commandline(tmp_path: Path, monkeypatch):
    """长 prompt（>50KB）必须走 stdin，CLI 参数保持短，避免 WinError 206。"""
    captured = {}

    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env, **kwargs):
        captured['args'] = args
        captured['input'] = input
        captured['cwd'] = cwd
        captured['env'] = env
        captured['kwargs'] = kwargs

        class FakeProc:
            returncode = 0
            stdout = 'PASS fake'
            stderr = ''
        return FakeProc()

    monkeypatch.setattr(subprocess, 'run', fake_run)

    # 构造 80KB 的 Hermes result，拼出明显超 Windows 命令行限制的 prompt
    long_result = 'H' * (80 * 1024)
    task = 'TASK long context'
    prompt = build_prompt('workbuddy', task, {'hermes': long_result}, tmp_path)
    assert len(prompt) > 50 * 1024  # 确认确实超长

    out = run_agent('workbuddy', prompt, tmp_path)
    assert out == 'PASS fake'

    # 1) CLI 参数列表保持很短，不含长 prompt 内容
    joined = ' '.join(captured['args'])
    assert 'H' * 100 not in joined
    assert len(joined) < 2048
    # 2) 长内容从 stdin 传输
    assert captured['input'] == prompt
    # 3) 官方 headless 参数保留
    assert '-p' in captured['args']
    assert '--output-format' in captured['args']
    assert 'text' in captured['args']
    assert '-y' in captured['args']
    # 4) 环境变量保留（禁用后台任务）
    assert captured['env'].get('CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS') == '1'


def test_workbuddy_prompt_keeps_validation_context(tmp_path: Path):
    """不截断验证上下文：TASK、Hermes 结果、workspace 路径、独立复核要求全保留。"""
    long_result = 'R' * (70 * 1024)
    task = '验证上下文必须完整'
    ws = Path('C:/fake/workspace')
    p = build_prompt('workbuddy', task, {'hermes': long_result}, ws)
    assert task in p
    assert 'R' * (70 * 1024) in p  # Hermes 结果未截断
    assert str(ws) in p  # workspace 绝对路径
    assert '独立复核' in p  # 独立复核要求
    assert len(p) > 70 * 1024


# --- Windows no-console（AAF-v0.4-TASK-002-FIX-003） ---

def _capture_run(monkeypatch, captured: dict):
    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env, **kwargs):
        captured.update(
            args=args, cwd=cwd, input=input, text=text, encoding=encoding,
            errors=errors, capture_output=capture_output, timeout=timeout,
            env=env, kwargs=kwargs,
        )

        class FakeProc:
            returncode = 0
            stdout = 'PASS fake'
            stderr = ''
        return FakeProc()

    monkeypatch.setattr(subprocess, 'run', fake_run)


@pytest.mark.skipif(os.name != 'nt', reason='CREATE_NO_WINDOW 是 Windows-only flag')
def test_agents_use_create_no_window_on_windows(tmp_path: Path, monkeypatch):
    """Windows：Hermes / WorkBuddy / Codex 三条路径统一经 subprocess.run 传 CREATE_NO_WINDOW。"""
    captured: dict = {}
    _capture_run(monkeypatch, captured)

    for agent in ('hermes', 'workbuddy', 'codex'):
        if agent == 'workbuddy':
            prompt = build_prompt('workbuddy', 'TASK', {'hermes': 'ok'}, tmp_path)
        else:
            prompt = build_prompt(agent, 'TASK', {}, tmp_path)
        run_agent(agent, prompt, tmp_path)
        flags = captured['kwargs'].get('creationflags', 0)
        assert flags & subprocess.CREATE_NO_WINDOW, (
            f'{agent}: 未传 CREATE_NO_WINDOW → 会新建可见 console 窗口 (kwargs={captured["kwargs"]})'
        )


def test_run_agent_non_windows_no_creationflags(tmp_path: Path, monkeypatch):
    """非 Windows：不得传 Windows-only creationflags（platform-safe）。"""
    captured: dict = {}
    _capture_run(monkeypatch, captured)
    monkeypatch.setattr(subprocess_utils, '_IS_WINDOWS', False)

    run_agent('hermes', 'TASK', tmp_path)
    assert 'creationflags' not in captured['kwargs']


def test_subprocess_parameters_preserved(tmp_path: Path, monkeypatch):
    """现有 I/O 语义完整保留：capture_output / text / utf-8 / timeout / input / cwd / env。"""
    captured: dict = {}
    _capture_run(monkeypatch, captured)

    run_agent('hermes', 'PROMPT', tmp_path, timeout=4321)
    assert captured['capture_output'] is True
    assert captured['text'] is True
    assert captured['encoding'] == 'utf-8'
    assert captured['errors'] == 'replace'
    assert captured['timeout'] == 4321
    assert captured['input'] is None  # hermes 走 -q 单查询，无 stdin
    assert os.path.normcase(str(captured['cwd'])) == os.path.normcase(str(tmp_path.resolve()))
    assert captured['env'].get('PATH')  # Windows 新会话 PATH


def test_subprocess_utils_platform_split(monkeypatch):
    """共享 helper 平台边界：Windows → CREATE_NO_WINDOW；非 Windows → 空 dict。"""
    monkeypatch.setattr(subprocess_utils, '_IS_WINDOWS', True)
    assert subprocess_utils.no_console_kwargs() == {'creationflags': subprocess.CREATE_NO_WINDOW}

    monkeypatch.setattr(subprocess_utils, '_IS_WINDOWS', False)
    assert subprocess_utils.no_console_kwargs() == {}
