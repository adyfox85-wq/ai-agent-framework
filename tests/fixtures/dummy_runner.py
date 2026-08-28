"""Deterministic dummy runner — Phase E force E2E（TASK-005-B req 33/34/35）。

用途：真实 Windows 进程树 force-kill 测试的**测试专用** runner（绝不指向真实
Hermes / WorkBuddy / Codex 会话）。

CLI 形状与真实 run.py 一致（[python, <script>, <task>, --workspace, WS, --output,
OUT, --launch-id, LID]），因此 Launcher 的 expected_command_line 记录的就是真实
argv，ownership verification 的命令行比较是真实闭环。

行为：
- runner_handshake（校验 control.json + 回写 runner_pid / runner_creation_time）
- --spawn-child：派生一个子进程（验证 taskkill /T 进程树包含关系）
- --commit-success-no-*：提交 SUCCESS canonical 但故意缺 run.json / REPORT.md
  （验证 wait thread → Core reconciliation 恢复派生产物）
- --cancel-aware（AAF_DUMMY_MODE=cancel-aware）：软取消检查点语义——轮询
  cancel.request，检测到 → Core finalizer 收敛 CANCELLED 全套产物（真实 runner
  检查点行为的确定性替身；TASK-005-C UI E2E 用）
- 默认：DUMMY_READY 后 sleep --sleep 秒（等待 force kill）
"""
import argparse
import json
import os
import subprocess
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
    p.add_argument("--sleep", type=float, default=300.0)
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

    # 与真实 runner 一致：进入 lifecycle 后先写非终态 canonical（recovery finalizer
    # 的 identity 校验要求 canonical task.json 存在且 task_id 匹配——FIX-001）
    update_status(output_dir, task_id=task_id, status="RUNNING",
                  task_path=args.task, workspace=args.workspace)
    print("CANONICAL_RUNNING", flush=True)

    child_pid = None
    if os.environ.get("AAF_DUMMY_SPAWN_CHILD") == "1":
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        child_pid = child.pid
        print(f"CHILD_PID {child.pid}", flush=True)

    # 测试模式经环境变量注入（Launcher argv 固定；env 不影响命令行校验）
    mode = os.environ.get("AAF_DUMMY_MODE", "")
    if mode == "commit-success-no-derived":
        finalize_terminal(output_dir, task_id=task_id, status="SUCCESS",
                          task_path=args.task, workspace=args.workspace,
                          report_path=str(output_dir / "REPORT.md"))
        print("COMMITTED_SUCCESS_NO_DERIVED", flush=True)
        return 0
    if mode == "commit-success-no-runjson":
        finalize_terminal(output_dir, task_id=task_id, status="SUCCESS",
                          task_path=args.task, workspace=args.workspace,
                          report_path=str(output_dir / "REPORT.md"))
        (output_dir / "REPORT.md").write_text(
            "# REPORT\n\n## Current Status\nSUCCESS\n## Terminal Generation\n1\n", encoding="utf-8")
        print("COMMITTED_SUCCESS_NO_RUNJSON", flush=True)
        return 0
    if mode == "commit-success-no-report":
        finalize_terminal(output_dir, task_id=task_id, status="SUCCESS",
                          task_path=args.task, workspace=args.workspace,
                          report_path=str(output_dir / "REPORT.md"))
        (output_dir / "run.json").write_text(
            json.dumps({"status": "SUCCESS", "task_id": task_id}), encoding="utf-8")
        print("COMMITTED_SUCCESS_NO_REPORT", flush=True)
        return 0
    if mode == "cancel-aware":
        # 软取消检查点语义（TASK-005-C UI E2E）：轮询 cancel.request（真实 runner
        # 检查点读取的外部可见等价物），检测到 → **等待 cancel.gate 门闩文件**（测试
        # 用它把「中间 UI 状态观察」与「收敛」解耦，杜绝时序竞态）→ 经 Core
        # finalizer 收敛 CANCELLED 全套产物（task.json / run.json / REPORT.md）。
        poll = float(os.environ.get("AAF_DUMMY_CANCEL_POLL", "0.1"))
        deadline = time.monotonic() + float(os.environ.get("AAF_DUMMY_CANCEL_WAIT", "120"))
        while time.monotonic() < deadline:
            if (output_dir / "cancel.request").exists():
                gate_deadline = time.monotonic() + 30.0
                while time.monotonic() < gate_deadline:
                    if (output_dir / "cancel.gate").exists():
                        break
                    time.sleep(0.05)
                finalize_terminal(output_dir, task_id=task_id, status="CANCELLED",
                                  task_path=args.task, workspace=args.workspace,
                                  report_path=str(output_dir / "REPORT.md"),
                                  cancel_mode="soft", terminal_reason="CANCEL_REQUESTED")
                (output_dir / "run.json").write_text(
                    json.dumps({"status": "CANCELLED", "task_id": task_id,
                                "terminal_generation": 1}), encoding="utf-8")
                (output_dir / "REPORT.md").write_text(
                    "# REPORT\n\n## Current Status\nCANCELLED\n## 任务已取消\n取消请求时间: 软取消收敛\n",
                    encoding="utf-8")
                print("CANCELLED_SOFT", flush=True)
                return 0
            time.sleep(poll)
        print("CANCEL_AWARE_TIMEOUT", flush=True)
        return 1

    sleep = float(os.environ.get("AAF_DUMMY_SLEEP", str(args.sleep)))
    print("DUMMY_READY", flush=True)
    time.sleep(sleep)
    print("DUMMY_EXIT", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
