"""AAF-v0.5-A0-PAID-GUARD-001-FIX-006 fresh-runner 验证驱动（Run N+1）。

FIX-006（Codex FIX-005 review BLOCKING）：paid admission 的持久化 state_dir
必须是**显式提供的、非空的、绝对路径**；空串 / 纯空白 / Path("") CWD fallback /
"." / 相对路径 / 畸形 / 类型非法 / 任何 CWD 派生 persistence authority → fail
closed 且**不创建任何 marker（含 CWD）**。本次变更涉及 AAF 准入权威，同 run
证据不足：本驱动从**全新 python 进程**（post-change 代码）复现并证明：

  S1  独立 fresh 进程 + matched paid auth + state_dir=""（受控 CWD）
      -> BLOCKED_COST_APPROVAL + 该 CWD 内零 marker
  S2  6 个独立 fresh 进程、各自不同 CWD、invalid state_dir
      （"" / "./relative-state" / "." 混合）
      -> 零 winner；任何 CWD 均无 marker / 相对目录（旧实现各自可 winner）
  S3  6 个独立 fresh 进程 + 同一有效绝对共享 state_dir + matched auth
      -> 恰好 1 个 ALLOWED_AUTHORIZED_PAID；其余 5 个 BLOCKED；
         marker 指纹正确、无授权原文；fresh replay 仍 BLOCKED
  S4  真实 runner + **相对 output_dir**（CWD 派生 authority）+ matched auth
      -> WAITING + BLOCKED_COST_APPROVAL + authorization_consumed=false
         + hermes 未 spawn + 无 consumption marker（仅 guard 记录 artifact）
  S5  verified LOCAL_FREE（本地 ollama）fresh 进程
      -> SUCCESS + ALLOWED_FREE + hermes 到达 invocation 边界
  S6  顺序 replay（driver 进程内 claim 后再次 evaluate 同 auth）-> BLOCKED
  S7  绝对路径是文件 / 路径中间组件是文件（unusable）fresh 进程
      -> BLOCKED_COST_APPROVAL（fail closed，无异常逃逸）

用法：python tests/fresh_runner_cost_guard_fix006_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A0-PAID-GUARD-001-FIX-006/fresh-runner-validation/（不提交）；
可用环境变量 AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import cost_guard as cg  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_wrapper.py"
FAKE_HERMES = ROOT / "tests" / "fake_hermes_cli.bat"
FAKE_CODEBUDDY = ROOT / "tests" / "fake_codebuddy_cli.bat"
WORKER = ROOT / "tests" / "_auth_claim_worker.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A0-PAID-GUARD-001-FIX-006" / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

TASK_ID = "AAF-FRESH-GUARD-006"
SCOPE = f"{TASK_ID}|hermes|deepseek-v4-flash|deepseek"
TASK_TEXT = f"""# Task ID
{TASK_ID}

# Task Name
fresh-runner persistent-state-dir fail-open class closure validation

# Objective
验证 v0.5 A0 Paid Guard FIX-006：非空绝对持久化 state_dir 才可建立 paid 准入权威

# Acceptance
1. 通过
"""

GUARD_ENVS = (
    "AAF_HERMES_MODEL",
    "AAF_HERMES_PROVIDER",
    "AAF_COST_AUTH",
    "AAF_COST_FREE_MODELS",
    "FAKE_HERMES_MARKER",
    "AAF_TEST_FAKE_BIN",
)

PAID_ENV = {
    "AAF_HERMES_MODEL": "deepseek-v4-flash",
    "AAF_HERMES_PROVIDER": "deepseek",
}
LOCAL_ENV = {
    "AAF_HERMES_MODEL": "qwen3:4b",
    "AAF_HERMES_PROVIDER": "ollama",
}


def _worker_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    env.update({"PYTHONPATH": str(ROOT), **PAID_ENV, "AAF_COST_AUTH": SCOPE})
    return env


def _run_worker(state_dir_arg: str, cwd: Path, task_id: str = TASK_ID) -> dict:
    """独立 python 进程在指定 CWD 内执行一次准入 claim（真实 resolve + env）。"""
    p = subprocess.run(
        [sys.executable, "-u", str(WORKER), state_dir_arg, task_id],
        cwd=str(cwd),
        env=_worker_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    return {
        "rc": p.returncode,
        "stdout": p.stdout.strip(),
        "stderr": p.stderr.strip()[-300:],
    }


def _spawn_fresh_runner(cwd: Path, env: dict, output_arg: str | Path) -> subprocess.CompletedProcess:
    """真实 runner（fresh process）+ fake bin；``output_arg`` 可传相对路径。"""
    fake_bin = cwd / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy(FAKE_HERMES, fake_bin / "hermes.bat")
    shutil.copy(FAKE_CODEBUDDY, fake_bin / "codebuddy.bat")

    task_file = cwd / "TASK.md"
    task_file.write_text(TASK_TEXT, encoding="utf-8")
    ws = cwd / "ws"
    ws.mkdir(exist_ok=True)

    child_env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    child_env["PYTHONPATH"] = str(ROOT)
    child_env["AAF_TEST_FAKE_BIN"] = str(fake_bin)
    child_env["FAKE_HERMES_MARKER"] = str(cwd / "hermes_invoked.marker")
    for k, v in env.items():
        child_env[k] = v

    return subprocess.run(
        [
            sys.executable,
            "-u",
            str(WRAPPER),
            str(task_file),
            "--workspace",
            str(ws),
            "--output",
            str(output_arg),
        ],
        cwd=str(cwd),
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def _fresh_dir(scenario_dir: Path, name: str) -> Path:
    d = scenario_dir / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _write_record(scenario_dir: Path, name: str, data: dict) -> None:
    (scenario_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# S1：fresh 进程 + state_dir=""（受控 CWD）→ BLOCKED + CWD 零 marker
# ---------------------------------------------------------------------------


def _scenario_s1() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S1-empty-state-dir-blocked")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    r = _run_worker("", scenario_dir)
    _check("blocked_rc", r["rc"] == 3, f"rc={r['rc']} {r['stdout']!r}")
    _check("blocked_decision", '"decision": "BLOCKED_COST_APPROVAL"' in r["stdout"], r["stdout"])
    _check("not_consumed", '"authorization_consumed": false' in r["stdout"], r["stdout"])
    _check("no_allowed", '"ALLOWED_AUTHORIZED_PAID"' not in r["stdout"], r["stdout"])
    _check(
        "no_cwd_marker",
        not (scenario_dir / cg.CONSUMPTION_FILENAME).exists(),
        f"marker created in worker CWD {scenario_dir}",
    )
    _check(
        "cwd_untouched",
        list(scenario_dir.iterdir()) == [],
        f"worker CWD must stay untouched: {list(scenario_dir.iterdir())}",
    )
    _write_record(scenario_dir, "scenario_record.json", {"scenario": "S1", **r})
    return not failures, failures


# ---------------------------------------------------------------------------
# S2：6 fresh 进程 + 不同 CWD + invalid state → 零 winner、零写入
# ---------------------------------------------------------------------------


def _scenario_s2() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S2-invalid-state-different-cwds-zero-winners")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    cwds = [_fresh_dir(scenario_dir, f"cwd{i}") for i in range(6)]
    state_args = ["", "", "./relative-state", "./relative-state", ".", "   "]
    results = [_run_worker(sa, cwd) for sa, cwd in zip(state_args, cwds)]
    winners = [r for r in results if r["rc"] == 0]
    losers = [r for r in results if r["rc"] == 3]
    _check("zero_winners", len(winners) == 0, f"winners={len(winners)} {results}")
    _check("all_blocked", len(losers) == len(results), f"losers={len(losers)}")
    for i, r in enumerate(losers):
        _check(f"loser{i}_blocked", '"decision": "BLOCKED_COST_APPROVAL"' in r["stdout"], r["stdout"])
    for i, d in enumerate(cwds):
        _check(f"cwd{i}_no_marker", not (d / cg.CONSUMPTION_FILENAME).exists(), f"marker in {d}")
        _check(f"cwd{i}_no_relative_dir", not (d / "relative-state").exists(), f"relative dir in {d}")
        _check(f"cwd{i}_untouched", list(d.iterdir()) == [], f"{d}: {list(d.iterdir())}")
    _write_record(
        scenario_dir,
        "scenario_record.json",
        {"scenario": "S2", "state_args": state_args, "results": results},
    )
    return not failures, failures


# ---------------------------------------------------------------------------
# S3：有效绝对共享 state_dir + 6 fresh 进程 → 恰好一个 winner
# ---------------------------------------------------------------------------


def _scenario_s3() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S3-shared-absolute-state-one-winner")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    shared = scenario_dir / "shared"
    shared.mkdir()
    results = [_run_worker(str(shared), scenario_dir) for _ in range(6)]
    winners = [r for r in results if r["rc"] == 0]
    losers = [r for r in results if r["rc"] == 3]
    _check("exactly_one_winner", len(winners) == 1, f"winners={len(winners)} {results}")
    _check("five_blocked", len(losers) == 5, f"losers={len(losers)}")
    marker = shared / cg.CONSUMPTION_FILENAME
    _check("marker_exists", marker.exists(), "consumption marker missing")
    if marker.exists():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        _check(
            "fingerprint",
            payload["consumed_auth_fingerprint"] == cg._auth_fingerprint(SCOPE),
            str(payload),
        )
        _check("no_raw_auth", "consumed_auth" not in payload, str(payload))
    _write_record(
        scenario_dir,
        "scenario_record.json",
        {"scenario": "S3", "winner_count": len(winners), "results": results},
    )
    return not failures, failures


# ---------------------------------------------------------------------------
# S4：真实 runner + 相对 output_dir（CWD 派生 authority）→ BLOCKED + 零 spawn
# ---------------------------------------------------------------------------


def _scenario_s4() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S4-relative-output-runner-blocked")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    proc = _spawn_fresh_runner(
        scenario_dir,
        {**PAID_ENV, "AAF_COST_AUTH": SCOPE},
        output_arg="out-rel",  # 相对路径 → runner CWD 派生 persistence authority
    )
    _check("runner_exit_0", proc.returncode == 0, f"exit={proc.returncode} {proc.stderr[-500:]}")
    out = scenario_dir / "out-rel"
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    _check("run_status_waiting", run_json["status"] == "WAITING", run_json["status"])
    _check("guard_blocked", guard["decision"] == "BLOCKED_COST_APPROVAL", guard["decision"])
    _check("guard_not_consumed", guard["authorization_consumed"] is False, str(guard["authorization_consumed"]))
    _check(
        "hermes_not_spawned",
        not (scenario_dir / "hermes_invoked.marker").exists(),
        "Hermes WAS spawned despite block",
    )
    _check(
        "no_consumption_marker_in_out",
        not (out / cg.CONSUMPTION_FILENAME).exists(),
        "consumption marker created in relative output dir",
    )
    _check(
        "no_consumption_marker_in_cwd",
        not (scenario_dir / cg.CONSUMPTION_FILENAME).exists(),
        "consumption marker created in runner CWD",
    )
    record = {
        "scenario": "S4",
        "runner_exit": proc.returncode,
        "run_status": run_json["status"],
        "guard_decision": guard["decision"],
        "guard_authorization_consumed": guard["authorization_consumed"],
        "guard_notes": guard["notes"],
        "hermes_invoked_marker": (scenario_dir / "hermes_invoked.marker").exists(),
        "consumption_marker_in_out": (out / cg.CONSUMPTION_FILENAME).exists(),
        "runner_stderr_tail": proc.stderr[-300:],
    }
    _write_record(scenario_dir, "scenario_record.json", record)
    return not failures, failures


# ---------------------------------------------------------------------------
# S5：LOCAL_FREE fresh runner → SUCCESS + ALLOWED_FREE + hermes spawn
# ---------------------------------------------------------------------------


def _scenario_s5() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S5-local-free-unaffected")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    proc = _spawn_fresh_runner(scenario_dir, LOCAL_ENV, output_arg="out")
    _check("runner_exit_0", proc.returncode == 0, f"exit={proc.returncode} {proc.stderr[-500:]}")
    run_json = json.loads((scenario_dir / "out" / "run.json").read_text(encoding="utf-8"))
    guard = json.loads((scenario_dir / "out" / "cost_guard.json").read_text(encoding="utf-8"))
    _check("run_status_success", run_json["status"] == "SUCCESS", run_json["status"])
    _check("guard_allowed_free", guard["decision"] == "ALLOWED_FREE", guard["decision"])
    _check("guard_local_free", guard["cost_class"] == "LOCAL_FREE", guard["cost_class"])
    _check(
        "hermes_spawned",
        (scenario_dir / "hermes_invoked.marker").exists(),
        "Hermes did NOT reach invocation boundary",
    )
    record = {
        "scenario": "S5",
        "run_status": run_json["status"],
        "guard_decision": guard["decision"],
        "guard_cost_class": guard["cost_class"],
        "hermes_invoked_marker": (scenario_dir / "hermes_invoked.marker").exists(),
    }
    _write_record(scenario_dir, "scenario_record.json", record)
    return not failures, failures


# ---------------------------------------------------------------------------
# S6：顺序 replay → 首次 allowed、二次 blocked
# ---------------------------------------------------------------------------


def _scenario_s6() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S6-sequential-replay")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    state_dir = scenario_dir / "state"
    state_dir.mkdir()
    ok, err = cg._claim_auth(SCOPE, SCOPE, state_dir)
    _check("first_claim", ok, err)
    saved = {k: os.environ.get(k) for k in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_AUTH)}
    os.environ.update({**PAID_ENV, "AAF_COST_AUTH": SCOPE})
    try:
        rec2 = cg.evaluate(TASK_ID, "hermes", state_dir=state_dir)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    _check("replay_blocked", rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL, rec2["decision"])
    _check("replay_consumed", rec2["authorization_consumed"] is True, str(rec2["authorization_consumed"]))
    _write_record(
        scenario_dir,
        "scenario_record.json",
        {
            "scenario": "S6",
            "first_claim_ok": ok,
            "replay_decision": rec2["decision"],
            "replay_authorization_consumed": rec2["authorization_consumed"],
        },
    )
    return not failures, failures


# ---------------------------------------------------------------------------
# S7：绝对路径是文件 / 中间组件是文件（unusable）→ BLOCKED
# ---------------------------------------------------------------------------


def _scenario_s7() -> tuple[bool, list[str]]:
    scenario_dir = _fresh_dir(EVIDENCE_ROOT, "S7-unusable-absolute-path-blocked")
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    afile = scenario_dir / "afile"
    afile.write_text("x", encoding="utf-8")
    cases = {
        "path_is_file": str(afile),
        "path_under_file": str(afile / "sub"),
    }
    results = {}
    for name, state_arg in cases.items():
        r = _run_worker(state_arg, scenario_dir)
        results[name] = r
        _check(f"{name}_blocked", r["rc"] == 3, f"rc={r['rc']} {r['stdout']!r}")
        _check(f"{name}_decision", '"decision": "BLOCKED_COST_APPROVAL"' in r["stdout"], r["stdout"])
        _check(f"{name}_not_consumed", '"authorization_consumed": false' in r["stdout"], r["stdout"])
    _write_record(scenario_dir, "scenario_record.json", {"scenario": "S7", "results": results})
    return not failures, failures


def main() -> int:
    missing = [f for f in (WRAPPER, FAKE_HERMES, FAKE_CODEBUDDY, WORKER) if not f.exists()]
    if missing:
        print(f"missing validation support files: {missing}", file=sys.stderr)
        return 99
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    failed = 0
    print("=" * 72)
    print("AAF-v0.5-A0 Paid Guard FIX-006 — fresh-runner validation (Run N+1)")
    print(f"fresh python: {sys.executable}")
    print(f"guard code:   {ROOT / 'ai_agent_framework' / 'cost_guard.py'}")
    print(f"evidence:     {EVIDENCE_ROOT}")
    print("=" * 72)

    scenarios = [
        ("S1-empty-state-dir-blocked", _scenario_s1),
        ("S2-invalid-state-different-cwds-zero-winners", _scenario_s2),
        ("S3-shared-absolute-state-one-winner", _scenario_s3),
        ("S4-relative-output-runner-blocked", _scenario_s4),
        ("S5-local-free-unaffected", _scenario_s5),
        ("S6-sequential-replay", _scenario_s6),
        ("S7-unusable-absolute-path-blocked", _scenario_s7),
    ]

    for name, fn in scenarios:
        ok, failures = fn()
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}")
        for f in failures:
            print(f"      - {f}")
        if not ok:
            failed += 1

    print("=" * 72)
    print(f"RESULT: {len(scenarios) - failed}/{len(scenarios)} scenarios passed")
    return failed


if __name__ == "__main__":
    sys.exit(main())
