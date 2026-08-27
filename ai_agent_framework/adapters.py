from __future__ import annotations

import os
import shutil
import subprocess
import winreg
from pathlib import Path

from .subprocess_utils import no_console_kwargs


ROLE_INSTRUCTIONS = {
    'hermes': '你是 Executor。严格执行 TASK，不扩大范围。完成后报告实际修改、测试、产物、问题和未完成项。',
    'workbuddy': '你是 Validator。对 TASK 和前序结果进行独立复核；必须检查实际项目状态，不默认相信前序 Agent 自述。不要修改文件。给出 PASS / PASS_WITH_WARNING / FAIL、证据和返工项。',
    'codex': '你是 Reviewer。基于 TASK、执行结果和复核结果做独立审查，重点检查代码/架构/逻辑/风险。不要代替 Executor 修改文件。给出 APPROVE / REQUEST_CHANGE 及证据。',
}


def build_prompt(agent: str, task: str, previous_results: dict[str, str], workspace: Path | None = None) -> str:
    prior = '\n\n'.join(f'## {name.upper()} RESULT\n{body}' for name, body in previous_results.items())
    ws = (
        f'\n\n# WORKSPACE\n工作目录（绝对路径）：{workspace}\n'
        '所有文件创建、修改、检查都必须在 WORKSPACE 目录内进行；不要在其他位置创建任务产物。\n'
        if workspace else ''
    )
    return f"{ROLE_INSTRUCTIONS[agent]}\n\n# ORIGINAL TASK\n{task}\n\n# PREVIOUS RESULTS\n{prior or '(none)'}\n{ws}"


def _registry_path(key: int, subkey: str, name: str = 'Path') -> str:
    try:
        with winreg.OpenKey(key, subkey) as k:
            return winreg.QueryValueEx(k, name)[0] or ''
    except OSError:
        return ''


def _windows_path() -> str:
    """Windows 新会话 PATH：用户 PATH + 机器 PATH（不依赖调用方 shell 的 PATH 格式）。"""
    user = _registry_path(winreg.HKEY_CURRENT_USER, 'Environment')
    machine = _registry_path(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')
    return ';'.join(filter(None, [user, machine]))


def _require(cmd: str) -> str:
    found = shutil.which(cmd, path=_windows_path())
    if not found and cmd == 'codex':
        # real-world hotfix：Codex 自动升级会更换 hash 版本目录，
        # registry PATH 可能残留旧目录导致 PATH discovery 失效。
        # 仅对 codex 增加受控 fallback（不改变 hermes / codebuddy 解析）。
        found = _codex_fallback()
    if not found:
        raise RuntimeError(f'MISSING_COMMAND: {cmd}')
    return found


CODEX_FALLBACK_DIR = Path(os.environ.get('LOCALAPPDATA', '')) / 'OpenAI' / 'Codex' / 'bin'


def _codex_fallback() -> str | None:
    """Windows Codex known-install fallback：%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe。

    多版本 hash 目录按 mtime 最新选当前有效版本（新版本目录更新时间更近）；
    0 candidate 或 candidate 不可用 → None（调用方保持 MISSING_COMMAND 语义）。
    """
    try:
        if not CODEX_FALLBACK_DIR.is_dir():
            return None
        candidates = [
            d / 'codex.exe'
            for d in CODEX_FALLBACK_DIR.iterdir()
            if d.is_dir() and (d / 'codex.exe').is_file()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return str(candidates[0])
    except OSError:
        return None


def run_agent(agent: str, prompt: str, workspace: Path, timeout: int = 3600) -> str:
    workspace = workspace.resolve()
    # 子进程统一使用 Windows 新会话 PATH；workbuddy 额外禁用后台任务
    env = {**os.environ, 'PATH': _windows_path()}
    if agent == 'hermes':
        exe = _require('hermes')
        # hermes v0.20.1 无 --query-file；用 -q 单查询 + -Q 静默 + --source tool 隔离
        args = [exe, 'chat', '--in', str(workspace), '-q', prompt, '-Q', '--ignore-rules', '--source', 'tool']
        stdin_data = None
    elif agent == 'workbuddy':
        exe = _require('codebuddy')
        # 官方 headless：-p 为 print 模式；完整 prompt 走 stdin（input=），
        # 避免 50KB+ 长 prompt 超出 Windows 命令行长度限制（WinError 206）。
        args = [exe, '-p', '--output-format', 'text', '-y']
        stdin_data = prompt
        env['CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS'] = '1'
    elif agent == 'codex':
        exe = _require('codex')
        args = [exe, 'exec', '--sandbox', 'read-only', '--cd', str(workspace), '--skip-git-repo-check', '-']
        stdin_data = prompt
    else:
        raise ValueError(f'Unknown agent: {agent}')

    proc = subprocess.run(
        args,
        cwd=workspace,
        input=stdin_data,
        text=True,
        encoding='utf-8',
        errors='replace',
        capture_output=True,
        timeout=timeout,
        env=env,
        **no_console_kwargs(),  # Windows: CREATE_NO_WINDOW，抑制 Agent CLI 新建黑色 console 窗口
    )
    if proc.returncode != 0:
        raise RuntimeError(f'{agent} failed (exit={proc.returncode})\nSTDERR:\n{proc.stderr[-4000:]}')
    out = proc.stdout.strip()
    if not out:
        # exit 0 但无输出（如未认证的 CLI）也必须视为失败，不能静默 PASS
        raise RuntimeError(f'{agent} produced empty output (exit=0)\nSTDERR:\n{proc.stderr[-4000:]}')
    return out
