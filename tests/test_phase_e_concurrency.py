"""Phase E（TASK-005-A）真实并发测试（req 29 / 设计 §6B.18）。

要求：normal finalizer vs cancel finalizer 的同一 task terminal winner，
由谁先在同一把 state.lock 下 commit 决定；不得仅 mock 掉整个 lock 后宣称 race 已测试。

本文件使用**真实子进程 + 真实 OS 文件锁 + 真实 filesystem**：
- SUCCESS worker：finalize_terminal（SUCCESS，锁内提交）
- CANCEL worker：finalize_cancelled_task（CANCELLED，锁内提交 + reconciliation）
- 确定性用例（谁先 commit 谁赢）固定 winner；
- 真正并发用例断言不变量（恰一个终态 + generation 1 + 派生产物跟随 canonical），
  任意 winner 均通过——对 CI/local 确定性成立。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ai_agent_framework import reconcile as rec_mod
from ai_agent_framework import task_lifecycle
from ai_agent_framework.task_lifecycle import (
    finalize_terminal,
    read_canonical_terminal,
    read_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

CONCURRENCY_WORKER = """\
import sys
from pathlib import Path

from ai_agent_framework import cancel as cancel_mod
from ai_agent_framework import finalize_cancelled
from ai_agent_framework.task_lifecycle import finalize_terminal

mode, out, task_id, ws = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
out = Path(out)
if mode == "success":
    c = finalize_terminal(
        out, task_id=task_id, status="SUCCESS", task_path=out / "TASK.md",
        workspace=ws, report_path=str(out / "REPORT.md"),
    )
    print("OK success", c.status, c.terminal_generation, c.preserved)
elif mode == "cancel":
    # FIX-001：soft recovery 需要合法 cancel.request 作为 authority evidence
    cancel_mod.write_cancel_request(out, task_id)
    c = finalize_cancelled.finalize_cancelled_task(task_id, ws, out)
    print("OK cancel", c.status, c.terminal_generation, c.preserved)
else:
    raise SystemExit(f"unknown mode: {mode}")
"""


def _spawn(worker: str, *args: str) -> subprocess.Popen:
    import tempfile

    script = Path(tempfile.gettempdir()) / f"aaf_phase_e_worker_{abs(hash(worker))}.py"
    script.write_text(worker, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.Popen(
        [sys.executable, str(script), *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def _run_worker(proc: subprocess.Popen) -> str:
    out_text = proc.communicate(timeout=60)[0] or ""
    assert proc.returncode == 0, f"worker 异常退出: {out_text}"
    return out_text


@pytest.fixture
def race_dir(tmp_path):
    """预置 RUNNING task.json（两个 worker 都读同一 RUNNING 状态，winner 由锁内 commit 决定）。"""
    out = tmp_path / "out"
    task_lifecycle.update_status(
        out, task_id="RACE", status="RUNNING", task_path=str(out / "TASK.md"), workspace=str(tmp_path)
    )
    (out / "TASK.md").write_text("# Task\nRACE", encoding="utf-8")
    return out


def _assert_consistent(out: Path, task_id: str, tmp_path: Path) -> None:
    """派生产物（run.json / REPORT）必须跟随 canonical；canonical 未被 reconciliation 改写。"""
    canonical = read_canonical_terminal(out)
    assert canonical is not None
    rec_mod.reconcile_terminal_artifacts(task_id, str(tmp_path), out)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == canonical.status
    assert run["terminal_generation"] == canonical.terminal_generation
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert f"## Current Status\n{canonical.status}" in report
    # canonical 不可变：reconcile 后 generation 不变
    assert read_status(out)["terminal_generation"] == canonical.terminal_generation


def test_concurrent_success_first_wins(race_dir, tmp_path):
    """Case A（§6B.18）：SUCCESS 先 commit → 后续 cancel 被拒绝，SUCCESS wins。"""
    p1 = _spawn(CONCURRENCY_WORKER, "success", str(race_dir), "RACE", str(tmp_path))
    _run_worker(p1)
    p2 = _spawn(CONCURRENCY_WORKER, "cancel", str(race_dir), "RACE", str(tmp_path))
    out2 = _run_worker(p2)
    assert "OK cancel SUCCESS 1 True" in out2  # preserved=True，generation 未 bump
    assert read_status(race_dir)["status"] == "SUCCESS"
    assert read_status(race_dir)["terminal_generation"] == 1
    _assert_consistent(race_dir, "RACE", tmp_path)


def test_concurrent_cancel_first_wins(race_dir, tmp_path):
    """Case B（§6B.18）：CANCELLED 先 commit → 后续 SUCCESS 被拒绝，CANCELLED wins。"""
    p1 = _spawn(CONCURRENCY_WORKER, "cancel", str(race_dir), "RACE", str(tmp_path))
    _run_worker(p1)
    p2 = _spawn(CONCURRENCY_WORKER, "success", str(race_dir), "RACE", str(tmp_path))
    out2 = _run_worker(p2)
    assert "OK success CANCELLED 1 True" in out2  # preserved=True，generation 未 bump
    assert read_status(race_dir)["status"] == "CANCELLED"
    assert read_status(race_dir)["terminal_generation"] == 1
    _assert_consistent(race_dir, "RACE", tmp_path)


@pytest.mark.parametrize("iteration", range(3))
def test_concurrent_real_race_invariant(race_dir, tmp_path, iteration):
    """真正同时启动 SUCCESS vs CANCEL：恰好一个终态 commit 成功（generation 1），
    另一个 preserved；派生产物与 canonical 一致。winner 任意（由锁顺序决定），
    不变量确定性成立（§6B.18 / §6B.2 锁内 re-read 闭合）。"""
    p1 = _spawn(CONCURRENCY_WORKER, "success", str(race_dir), "RACE", str(tmp_path))
    p2 = _spawn(CONCURRENCY_WORKER, "cancel", str(race_dir), "RACE", str(tmp_path))
    o1 = _run_worker(p1)
    o2 = _run_worker(p2)
    status = read_status(race_dir)["status"]
    assert status in ("SUCCESS", "CANCELLED"), f"必须恰有一个终态（iteration={iteration}）: {o1} / {o2}"
    assert read_status(race_dir)["terminal_generation"] == 1, f"generation 必须为 1（只有一次 commit 胜出）"
    # 双方输出的状态必须一致 = canonical（输家锁内 re-read 到已提交的 terminal truth）；
    # 恰一个 preserved=True（输家）+ 恰一个 preserved=False（赢家）
    statuses = set()
    preserved_flags = []
    for out_text in (o1, o2):
        parts = out_text.strip().split()
        assert len(parts) == 5, f"worker 输出格式异常: {out_text!r}"
        statuses.add(parts[2])
        preserved_flags.append(parts[4])
    assert statuses == {status}, f"双方必须读到同一 canonical 终态: {o1!r} / {o2!r}"
    assert sorted(preserved_flags) == ["False", "True"], f"必须恰一个 winner + 一个 preserved 输家: {o1!r} / {o2!r}"
    _assert_consistent(race_dir, "RACE", tmp_path)
