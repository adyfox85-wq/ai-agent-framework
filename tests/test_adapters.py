import subprocess
from pathlib import Path
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

    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env):
        captured['args'] = args
        captured['input'] = input
        captured['cwd'] = cwd
        captured['env'] = env

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
