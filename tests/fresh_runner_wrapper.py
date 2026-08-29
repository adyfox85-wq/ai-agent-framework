"""AAF-v0.5-A0 fresh-runner validation wrapper（TASK: AAF-v0.5-A0-PAID-GUARD-001）。

仅用于 fresh-process 验证（Run N+1）：在导入 runner 之前把 fake bin 目录前置到
adapters / cost_guard 的 CLI discovery PATH（``AAF_TEST_FAKE_BIN``）。这样：
- 真实进程创建边界保留：``subprocess.run`` 会真实拉起 fake ``hermes.bat`` /
  ``codebuddy.bat``（真实 child process；blocked 场景则一个 child 都不会出现）；
- guard 的解析/分类/授权逻辑零修改（本 wrapper 只影响可执行文件 discovery 路径）。

用法：
    python tests/fresh_runner_wrapper.py <TASK.md> --workspace <ws> --output <out> [--launch-id X]

env:
    AAF_TEST_FAKE_BIN   fake bin 目录（含 hermes.bat / codebuddy.bat），前置到 discovery PATH
    FAKE_HERMES_MARKER  每次 hermes chat invocation 写入的 marker 文件路径（argv 证据）
"""
import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod

_real_adapters_path = adapters_mod._windows_path
_real_guard_path = cost_guard_mod._windows_path


def _prepend_fake_bin(original):
    extra = os.environ.get("AAF_TEST_FAKE_BIN", "").strip()
    if not extra:
        return original
    return extra + ";" + original


adapters_mod._windows_path = lambda: _prepend_fake_bin(_real_adapters_path())
cost_guard_mod._windows_path = lambda: _prepend_fake_bin(_real_guard_path())

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
