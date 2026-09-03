"""AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001 fresh-runner validation driver
（Run N+1；TASK Requirement 13：全新进程证明 corrected runtime 实际加载）。

每个 stage 在**全新 python 进程**（tests/fresh_runner_state_recovery_wrapper.py）
内扮演一个 Bridge 实例，驱动真实 bounded 测试任务（dummy_recover_runner：
handshake → canonical RUNNING → sleep(AAF_RECOVER_SLEEP) → SUCCESS 全套产物）：

  N1 launch   实例 1 真实 launch bounded 任务（live 窗口 ~6s），实例退出
              模拟「Bridge 崩溃/重启前实例消失」（wait thread 随进程消失，
              runner 子进程继续存活——Windows 子进程不随父退出）
  N2 restart  实例 2（零内存）：recover_launches → 同一正式任务恢复 RUNNING
              （task_id / launch_id / runner_pid 与 registry/control 一致）→
              duplicate hotkey 尝试 → running reject、registry 无第二活跃
              launch、view 未被覆盖 → 任务自然完成 → recovered watcher 收尾
              （state FINISHED / last_run FINISHED / registry EXITED /
              canonical SUCCESS / REPORT 存在）
  N3 reopen   实例 3（零内存）：terminal 视图经 last_run 恢复（SUCCESS/已完成 +
              REPORT 路径）；再真实启动第二个 bounded 任务 → 正常完成 +
              REPORT/run.json 生成（执行/报告生成无回归）

FIX-001（EXITED→last_run crash-window closure；N4/N5 独立隔离根 cw-bridge）：
  N4 crashwin    真实 bounded 任务（SRV-FRESH-001）自然完成 → registry EXITED
              + canonical SUCCESS → 模拟「mark_exited 后、_persist_last 前
              Bridge 崩溃」：last_run 回退为更早 SRV-FRESH-OLD 的旧呈现
  N5 crashreopen 新进程 recover_launches → 从权威 artifacts 重建 victim
              terminal（同 task_id/launch_id、FINISHED、REPORT）；无 rerun
              （canonical generation 不变 / 无 ACTIVE / launch 数不变）；旧
              last_run 不覆盖恢复结果；再真实启动新任务（执行无回归）

验证要点（对应 TASK requirement 13 清单）：
- launch a real bounded test task                          N1
- while task is live, restart/reopen Bridge                N1→N2（真实新进程）
- same formal task identity/status is recovered            N2
- duplicate launch attempt does not create another runner  N2
- task can continue to terminal state                      N2
- reopening after terminal state shows correct terminal
  task/result                                              N3
- EXITED crash-window（registry EXITED + last_run 丢失）→
  restart 从既有任务 artifacts 恢复同一 terminal identity   N4→N5（真实新进程）
- crash-window 恢复无 rerun / 无重复 runner                 N5
- older last_run 不能覆盖恢复的 terminal task              N5
- no F-I-RUN/test-state leakage：全部 stage 在隔离
  AAF_BRIDGE_DIR 根运行；driver 前后对比真实 ~/.aaf-bridge
  （last_run.json 内容 + launches/ 文件数）零变化          driver
- no regression to task execution/report generation        N3/N5

用法：python tests/fresh_runner_state_recovery_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001/fresh-runner-validation/
（不提交）；可用环境变量 AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WRAPPER = ROOT / "tests" / "fresh_runner_state_recovery_wrapper.py"
TASK_DIR = ROOT / ".aaf" / "AAF-RUNTIME-UX-BRIDGE-STATE-RECOVERY-001"
DEFAULT_EVIDENCE_ROOT = TASK_DIR / "fresh-runner-validation"
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

REAL_STATE_DIR = Path.home() / ".aaf-bridge"
REAL_LAST_RUN = REAL_STATE_DIR / "last_run.json"
REAL_LAUNCHES_DIR = REAL_STATE_DIR / "launches"

STAGES = ("launch", "restart", "reopen", "crashwin", "crashreopen")

TEST_IDS = ("SRV-FRESH-001", "SRV-FRESH-002", "SRV-FRESH-003", "SRV-FRESH-OLD", "F-I-RUN")


def _real_snapshot() -> tuple[bytes | None, int]:
    last = REAL_LAST_RUN.read_bytes() if REAL_LAST_RUN.exists() else None
    count = 0
    if REAL_LAUNCHES_DIR.is_dir():
        count = len(list(REAL_LAUNCHES_DIR.glob("*.json")))
    return last, count


def _run_stage(stage: str, ev: Path) -> tuple[int, str]:
    env = dict(os.environ)
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), stage, str(ev)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main() -> int:
    failures = 0
    # 每次运行从干净证据根开始（旧证据绝不参与判定）
    shutil.rmtree(EVIDENCE_ROOT, ignore_errors=True)
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    before = _real_snapshot()
    print(f"== AAF state-recovery fresh-runner validation (evidence: {EVIDENCE_ROOT}) ==")
    for stage in STAGES:
        print(f"-- stage {stage} (new process) ...", flush=True)
        code, out = _run_stage(stage, EVIDENCE_ROOT)
        print(out[-4000:] if code != 0 else out[-2000:])
        ev_path = EVIDENCE_ROOT / f"stage-{stage}.json"
        if code != 0:
            failures += 1
            print(f"[FAIL] stage {stage} exit={code}")
            continue
        if not ev_path.exists():
            failures += 1
            print(f"[FAIL] stage {stage}: 证据文件缺失 {ev_path}")
            continue
        data = json.loads(ev_path.read_text(encoding="utf-8"))
        print(f"[PASS] stage {stage}: {json.dumps(data, ensure_ascii=False)[:600]}")
    # 泄漏检查：真实用户 Bridge state 零变化、零测试身份
    last_now, count_now = _real_snapshot()
    if last_now != before[0]:
        failures += 1
        print("[FAIL] 真实 ~/.aaf-bridge/last_run.json 内容被 fresh-runner 改写（泄漏）")
    if count_now != before[1]:
        failures += 1
        print("[FAIL] 真实 ~/.aaf-bridge/launches/ 文件数变化（泄漏）")
    if last_now:
        text = last_now.decode("utf-8", errors="replace")
        leaked = [t for t in TEST_IDS if t in text]
        if leaked:
            failures += 1
            print(f"[FAIL] 测试身份泄漏进真实 last_run.json: {leaked}")
    registry_leak = False
    if REAL_LAUNCHES_DIR.is_dir():
        for p in REAL_LAUNCHES_DIR.glob("*.json"):
            try:
                raw = p.read_text(encoding="utf-8")
                if any(t in raw for t in TEST_IDS):
                    registry_leak = True
                    break
            except OSError:
                continue
        if registry_leak:
            failures += 1
            print("[FAIL] 测试身份出现在真实 launches registry 文件（泄漏）")
    print(f"== fresh-runner validation {'PASS' if failures == 0 else f'FAIL ({failures})'} ==")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
