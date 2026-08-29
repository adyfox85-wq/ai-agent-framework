"""AAF-v0.5-A0-PAID-GUARD-001-FIX-003 fresh-runner 验证驱动（Run N+1）。

本次变更涉及 AAF 准入权威（一次性授权消费 → 原子 claim），同 run 证据不足：
本驱动从**全新 python 进程**复现并发 claim 竞争，并证明：

  S1  进程并发 claim（6 个独立 python 进程，同一 auth + 同一 state_dir）
      -> 恰好 1 个 ALLOWED_AUTHORIZED_PAID（authorization_matched=true）；
         其余 5 个 BLOCKED_COST_APPROVAL（authorization_consumed=true）
         —— 跨进程 authority 是 filesystem exclusive-create，与内存无关
  S2  replay 到达真实 runner 边界（marker 已被 claim，同 auth 重新提交）
      -> WAITING + BLOCKED_COST_APPROVAL + authorization_consumed=true
         + hermes 未 spawn（invocation marker 缺失 —— loser/replay 不越过边界）
  S3  verified LOCAL_FREE（本地 ollama）fresh 进程
      -> SUCCESS + ALLOWED_FREE + hermes 到达 invocation 边界（marker 存在）
  S4  paid/unknown 无授权 fresh 进程
      -> WAITING + BLOCKED_COST_APPROVAL + hermes 未 spawn
  S5  顺序 replay（driver 进程内 claim 后再次 evaluate 同 auth）-> BLOCKED

用法：python tests/fresh_runner_cost_guard_fix003_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A0-PAID-GUARD-001-FIX-003/fresh-runner-validation/（不提交）；
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
    ROOT / ".aaf" / "AAF-v0.5-A0-PAID-GUARD-001-FIX-003" / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

TASK_ID = "AAF-FRESH-GUARD-003"
SCOPE = f"{TASK_ID}|hermes|deepseek-v4-flash|deepseek"
TASK_TEXT = f"""# Task ID
{TASK_ID}

# Task Name
fresh-runner atomic claim validation

# Objective
验证 v0.5 A0 Paid Guard FIX-003 原子消费在 fresh-process 下的行为

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


# ---------------------------------------------------------------------------
# S1：进程并发 claim
# ---------------------------------------------------------------------------


def _run_contention(state_dir: Path, n: int = 6) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            **PAID_ENV,
            "AAF_COST_AUTH": SCOPE,
        }
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-u", str(WORKER), str(state_dir), TASK_ID],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(n)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=180)
        results.append(
            {
                "rc": p.returncode,
                "stdout": out.strip(),
                "stderr": err.strip()[-300:],
            }
        )
    return {"n": n, "results": results}


# ---------------------------------------------------------------------------
# S2/S3/S4：真实 runner（fresh process）+ fake bin
# ---------------------------------------------------------------------------


def _spawn_fresh_runner(scenario_dir: Path, env: dict) -> subprocess.CompletedProcess:
    fake_bin = scenario_dir / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy(FAKE_HERMES, fake_bin / "hermes.bat")
    shutil.copy(FAKE_CODEBUDDY, fake_bin / "codebuddy.bat")

    task_file = scenario_dir / "TASK.md"
    task_file.write_text(TASK_TEXT, encoding="utf-8")
    ws = scenario_dir / "ws"
    ws.mkdir(exist_ok=True)
    out = scenario_dir / "out"

    child_env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    child_env["PYTHONPATH"] = str(ROOT)
    child_env["AAF_TEST_FAKE_BIN"] = str(fake_bin)
    child_env["FAKE_HERMES_MARKER"] = str(scenario_dir / "hermes_invoked.marker")
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
            str(out),
        ],
        cwd=str(ROOT),
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def _runner_scenario(sid: str, env: dict, expect: dict, pre_claim: bool = False) -> tuple[bool, list[str]]:
    scenario_dir = EVIDENCE_ROOT / sid
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True)
    out = scenario_dir / "out"

    if pre_claim:
        # 模拟并发中已有一个 admission 赢得了 claim（driver 是独立进程）
        ok, err = cg._claim_auth(SCOPE, SCOPE, out)
        if not ok:
            return False, [f"pre_claim failed: {err}"]

    proc = _spawn_fresh_runner(scenario_dir, env)
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    if proc.returncode != 0:
        failures.append(f"runner exit={proc.returncode}: {proc.stderr[-500:]}")
        return not failures, failures

    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    guard = json.loads((out / "cost_guard.json").read_text(encoding="utf-8"))
    marker = scenario_dir / "hermes_invoked.marker"
    hermes_marker = (
        marker.read_text(encoding="utf-8", errors="replace") if marker.exists() else None
    )
    hermes_md = (out / "hermes_result.md").read_text(encoding="utf-8")

    _check("run.status", run_json["status"] == expect["status"], f"{run_json['status']} != {expect['status']}")
    _check("guard.decision", guard["decision"] == expect["decision"], guard["decision"])
    if "cost_class" in expect:
        _check("guard.cost_class", guard["cost_class"] == expect["cost_class"], guard["cost_class"])
    if "authorization_consumed" in expect:
        _check(
            "guard.authorization_consumed",
            guard.get("authorization_consumed") is expect["authorization_consumed"],
            f"authorization_consumed={guard.get('authorization_consumed')}",
        )
    if expect.get("hermes_spawned"):
        _check("hermes.spawned", hermes_marker is not None, "marker missing — Hermes subprocess was not created")
    else:
        _check("hermes.not_spawned", hermes_marker is None, "marker exists — Hermes WAS spawned despite block")

    record = {
        "scenario": sid,
        "env": env,
        "expect": expect,
        "pre_claim": pre_claim,
        "runner_exit": proc.returncode,
        "run_status": run_json["status"],
        "guard_decision": guard["decision"],
        "guard_cost_class": guard["cost_class"],
        "guard_authorization_consumed": guard.get("authorization_consumed"),
        "consumption_marker_exists": (out / cg.CONSUMPTION_FILENAME).exists(),
        "hermes_marker": hermes_marker,
        "hermes_result_head": hermes_md[:300],
        "runner_stderr_tail": proc.stderr[-300:],
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def _scenario_s1() -> tuple[bool, list[str]]:
    scenario_dir = EVIDENCE_ROOT / "S1-process-contention"
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True)
    state_dir = scenario_dir / "shared"
    state_dir.mkdir()

    data = _run_contention(state_dir)
    winners = [r for r in data["results"] if r["rc"] == 0]
    losers = [r for r in data["results"] if r["rc"] == 3]
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    _check("exactly_one_winner", len(winners) == 1, f"winners={len(winners)}")
    _check("all_others_blocked", len(losers) == data["n"] - 1, f"losers={len(losers)}")
    if winners:
        _check("winner_decision", "ALLOWED_AUTHORIZED_PAID" in winners[0]["stdout"], winners[0]["stdout"])
    for i, r in enumerate(losers):
        _check(
            f"loser{i}_consumed",
            f'"decision": "BLOCKED_COST_APPROVAL"' in r["stdout"]
            and '"authorization_consumed": true' in r["stdout"],
            r["stdout"],
        )
    marker = state_dir / cg.CONSUMPTION_FILENAME
    _check("marker_exists", marker.exists(), "consumption marker missing")
    if marker.exists():
        payload = json.loads(marker.read_text(encoding="utf-8"))
        _check(
            "marker_fingerprint",
            payload.get("consumed_auth_fingerprint") == cg._auth_fingerprint(SCOPE),
            payload.get("consumed_auth_fingerprint"),
        )
        _check("marker_no_raw_auth", "consumed_auth" not in payload, "raw auth persisted")

    # 再起一个 fresh 进程（全新内存）→ 跨进程 replay 仍 blocked
    env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    env.update({"PYTHONPATH": str(ROOT), **PAID_ENV, "AAF_COST_AUTH": SCOPE})
    p = subprocess.run(
        [sys.executable, "-u", str(WORKER), str(state_dir), TASK_ID],
        cwd=str(ROOT), env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    _check("fresh_replay_blocked", p.returncode == 3, f"rc={p.returncode} {p.stdout!r}")

    record = {
        "scenario": "S1-process-contention",
        "n": data["n"],
        "winner_count": len(winners),
        "loser_count": len(losers),
        "results": data["results"],
        "fresh_replay_rc": p.returncode,
        "fresh_replay_stdout": p.stdout.strip(),
        "consumption_marker": (
            json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        ),
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def _scenario_s5() -> tuple[bool, list[str]]:
    """S5：顺序 replay（driver 进程 = fresh 进程；claim 后同 auth 再 evaluate → BLOCKED）。

    使用独立 execution 上下文（TASK5/SCOPE5），避免与 S2 的 pre-claim 共享
    driver 进程的 in-process 集合（真实 AAF 中不同 execution = 不同 task id）。
    """
    scenario_dir = EVIDENCE_ROOT / "S5-sequential-replay"
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True)
    state_dir = scenario_dir / "shared"
    state_dir.mkdir()
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    task5 = f"{TASK_ID}-S5"
    scope5 = f"{task5}|hermes|deepseek-v4-flash|deepseek"
    ok, err = cg._claim_auth(scope5, scope5, state_dir)
    _check("first_claim", ok, err)
    saved = {k: os.environ.get(k) for k in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_AUTH)}
    os.environ.update({**PAID_ENV, "AAF_COST_AUTH": scope5})
    try:
        rec2 = cg.evaluate(task5, "hermes", state_dir=state_dir)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    _check(
        "replay_blocked",
        rec2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL,
        rec2["decision"],
    )
    _check("replay_consumed", rec2["authorization_consumed"] is True, str(rec2["authorization_consumed"]))

    record = {
        "scenario": "S5-sequential-replay",
        "task_id": task5,
        "first_claim_ok": ok,
        "replay_decision": rec2["decision"],
        "replay_authorization_consumed": rec2["authorization_consumed"],
        "replay_notes": rec2["notes"],
        "consumption_marker": (
            json.loads((state_dir / cg.CONSUMPTION_FILENAME).read_text(encoding="utf-8"))
            if (state_dir / cg.CONSUMPTION_FILENAME).exists()
            else None
        ),
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def main() -> int:
    missing = [f for f in (WRAPPER, FAKE_HERMES, FAKE_CODEBUDDY, WORKER) if not f.exists()]
    if missing:
        print(f"missing validation support files: {missing}", file=sys.stderr)
        return 99
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    failed = 0
    print("=" * 72)
    print("AAF-v0.5-A0 Paid Guard FIX-003 — fresh-runner validation (Run N+1)")
    print(f"fresh python: {sys.executable}")
    print(f"guard code:   {ROOT / 'ai_agent_framework' / 'cost_guard.py'}")
    print(f"evidence:     {EVIDENCE_ROOT}")
    print("=" * 72)

    scenarios = [
        ("S1-process-contention", _scenario_s1, {}),
        (
            "S2-replay-at-runner-boundary",
            _runner_scenario,
            {
                "sid": "S2-replay-at-runner-boundary",
                "env": {**PAID_ENV, "AAF_COST_AUTH": SCOPE},
                "expect": {
                    "status": "WAITING",
                    "decision": "BLOCKED_COST_APPROVAL",
                    "cost_class": "PAID_OR_UNKNOWN",
                    "authorization_consumed": True,
                    "hermes_spawned": False,
                },
                "pre_claim": True,
            },
        ),
        (
            "S3-local-free-allowed",
            _runner_scenario,
            {
                "sid": "S3-local-free-allowed",
                "env": LOCAL_ENV,
                "expect": {
                    "status": "SUCCESS",
                    "decision": "ALLOWED_FREE",
                    "cost_class": "LOCAL_FREE",
                    "hermes_spawned": True,
                },
            },
        ),
        (
            "S4-paid-no-auth-blocked",
            _runner_scenario,
            {
                "sid": "S4-paid-no-auth-blocked",
                "env": PAID_ENV,
                "expect": {
                    "status": "WAITING",
                    "decision": "BLOCKED_COST_APPROVAL",
                    "cost_class": "PAID_OR_UNKNOWN",
                    "authorization_consumed": False,
                    "hermes_spawned": False,
                },
            },
        ),
        ("S5-sequential-replay", _scenario_s5, {}),
    ]

    for name, fn, kwargs in scenarios:
        ok, failures = fn(**kwargs) if kwargs else fn()
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
