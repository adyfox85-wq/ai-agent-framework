"""Deterministic recovery-test runner — AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001。

用途：Bridge restart 状态恢复测试的**测试专用** runner（绝不指向真实 Agent 会话）。

CLI 形状与真实 run.py / dummy_runner 一致（[python, <script>, <task>, --workspace,
WS, --output, OUT, --launch-id, LID]），因此 Launcher 的 expected_command_line /
ownership handshake 是真实闭环。

行为：
1. runner_handshake（校验 control.json + 回写 runner_pid / runner_creation_time）
2. update_status RUNNING（canonical 非终态 task.json 存在——与真实 runner 一致）
3. print READY 后 sleep AAF_RECOVER_SLEEP 秒（默认 5.0；测试用短 sleep 制造
   「live 窗口」：launch 后任务仍在运行 → 可在此窗口内重启/恢复）
4. finalize_terminal SUCCESS + run.json + REPORT.md（canonical + 派生产物一致）
5. print DONE；exit 0

sleep 期间被 taskkill → 无 canonical terminal（与 dummy_runner 默认模式一致）；
自然完成 → canonical SUCCESS 全套产物（供 watcher/wait-thread 收尾断言）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task", type=Path)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--launch-id", default=None)
    args = p.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    from ai_agent_framework.runner import runner_handshake  # noqa: PLC0415
    from ai_agent_framework.task_lifecycle import finalize_terminal, update_status  # noqa: PLC0415
    from ai_agent_framework.task_validation import parse_task_fields  # noqa: PLC0415

    task_text = args.task.read_text(encoding="utf-8")
    task_id = parse_task_fields(task_text)["Task ID"]
    output_dir = args.output

    runner_handshake(output_dir, task_id, args.workspace, expected_launch_id=args.launch_id)
    print(f"HANDSHAKE_OK pid={os.getpid()}", flush=True)
    update_status(output_dir, task_id=task_id, status="RUNNING",
                  task_path=args.task, workspace=args.workspace)
    print("CANONICAL_RUNNING", flush=True)

    sleep = float(os.environ.get("AAF_RECOVER_SLEEP", "5.0"))
    print("RECOVERY_RUNNER_READY", flush=True)
    time.sleep(sleep)

    finalize_terminal(output_dir, task_id=task_id, status="SUCCESS",
                      task_path=args.task, workspace=args.workspace,
                      report_path=str(output_dir / "REPORT.md"))
    # 派生产物与 canonical 严格一致（terminal_generation 取自 canonical——finalize
    # 已提交的生成号；避免 watcher/wait-thread 误判 derived-inconsistent 触发 reconcile）
    from ai_agent_framework.task_lifecycle import read_canonical_terminal  # noqa: PLC0415
    canonical = read_canonical_terminal(output_dir)
    generation = getattr(canonical, "terminal_generation", 1) or 1
    (output_dir / "run.json").write_text(
        json.dumps({"status": "SUCCESS", "task_id": task_id,
                    "terminal_generation": generation}), encoding="utf-8")
    (output_dir / "REPORT.md").write_text(
        "# REPORT\n\n## Current Status\nSUCCESS\n## Terminal Generation\n1\n",
        encoding="utf-8")
    print("RECOVERY_RUNNER_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
