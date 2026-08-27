"""Windows subprocess console suppression — 统一共享 helper（platform-safe）。

用途：
- ai_agent_framework.adapters.run_agent() 启动 Hermes / WorkBuddy / Codex 子进程
- bridge.launcher.FrameworkLauncher.launch() 启动 run.py 子进程

Windows 下 GUI 宿主（pythonw / Tray Bridge）启动 console-subsystem 可执行文件时，
子进程默认会新建可见黑色 console 窗口；传入 CREATE_NO_WINDOW 可抑制。

非 Windows 不返回任何 Windows-only 参数（显式 platform-safe，避免 ValueError）。
"""
from __future__ import annotations

import os
import subprocess

# 平台判定在导入期固化：测试可安全 monkeypatch 本模块常量，不触碰全局 os.name
_IS_WINDOWS = os.name == 'nt'


def no_console_kwargs() -> dict:
    """返回用于抑制子进程新建可见 console 窗口的 subprocess kwargs。

    Windows: {'creationflags': subprocess.CREATE_NO_WINDOW}
    其他平台: {}（不传 Windows-only creation flags）
    """
    if _IS_WINDOWS:
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}
