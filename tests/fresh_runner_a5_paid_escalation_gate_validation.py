"""AAF-v0.5-A5-PAID-ESCALATION-GATE-001 fresh-runner validation driver
（Run N+1；TASK Requirement 12：全新进程证明 paid escalation / Cost Gate
runtime 行为——本任务改变 self-hosting cost/authorization runtime 行为）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_paid_escalation_gate_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat invocation 向
marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖 = actual
invocation model）。wrapper 在 runner 进程结束前打印 ``AAF_ENV_PROBE|...``
三行（same-process env 还原证明）。

  N1（Risk: LOW + pg_paid_only + 无 AAF_COST_AUTH）:
       paid escalation required + no auth => NO paid execution：aaa-orig 失败
       → Cost Gate BLOCKED（absent）→ hermes chat 恰 1 次（marker 无
       zzz-paid@remote-api 行）、gate artifact BLOCKED + runtime audit
       not-eligible、WAITING、codebuddy 未 spawn、env probe 全 -none-。
  N2（pg_paid_only + AAF_COST_AUTH scope 不匹配）:
       mismatched auth => NO paid execution：gate BLOCKED（mismatch）、
       恰 1 次 invocation、WAITING、env probe 全 -none-。
  N3（pg_paid_only + AAF_COST_AUTH 精确匹配 zzz-paid scope）:
       exact auth => gate AUTHORIZED（matched/consumed=true、A0 一次性消费
       marker 存在）但**仍无 paid invocation**：hermes chat 恰 1 次、WAITING
       （无自动继续）、无 silent paid execution、env probe 全 -none-。
  N4（no silent paid execution 综合断言）:
       N1/N3 marker 不含 zzz-paid@remote-api 行 + gate record
       no_silent_paid_evidence 非空显式 + fallback_attempted/used 恒 False。
  N5（pg_free_intact + fail aaa-orig）:
       既有 FREE fallback 行为保持：original 失败 → 恰一次 zzz-fb free
       fallback（marker 2 行）→ used=true / final=zzz-fb、gate artifact 不
       存在（free candidate 优先于 paid escalation）、全链 SUCCESS。

用法：python tests/fresh_runner_a5_paid_escalation_gate_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001/fresh-runner-validation/
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import cost_guard as cg  # noqa: E402
from ai_agent_framework import fallback_contract as fc  # noqa: E402
from ai_agent_framework import fallback_paid_gate as fpg  # noqa: E402
from ai_agent_framework import fallback_runtime as fr  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a5_paid_escalation_gate_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A5-PAID-ESCALATION-GATE-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-PAID-ESCALATION-GATE-001"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001 fresh-runner fake Hermes CLI
rem (ASCII only on purpose: cmd.exe parses metacharacters even inside REM lines).
rem - `hermes config get model`    -> deepseek-v4-flash / deepseek（baseline 事实）
rem - `hermes --version` / `--help`-> static text (exit 0)
rem - `hermes chat ...`            -> append invocation evidence to the marker
rem   (MODEL=<actual model>@<provider> per call); fails (exit 1) when the actual
rem   model@provider is listed in AAF_TEST_FAIL_MODELS (semicolon separated).
if "%1"=="config" goto config
if "%1"=="--version" goto version
if "%1"=="--help" goto help
goto chat

:config
if "%2"=="get" (
  if "%3"=="model" (
    echo default: deepseek-v4-flash
    echo provider: deepseek
    echo base_url:
  )
)
exit /b 0

:version
echo Hermes Agent v0.20.5 fake A5-PAID-ESCALATION-GATE-001
exit /b 0

:help
echo Usage: hermes chat --in DIR -q PROMPT -Q --ignore-rules --source tool
exit /b 0

:chat
set "EFF_MODEL=%AAF_HERMES_MODEL%"
set "EFF_PROVIDER=%AAF_HERMES_PROVIDER%"
if "%EFF_MODEL%"=="" set "EFF_MODEL=deepseek-v4-flash"
if "%EFF_PROVIDER%"=="" set "EFF_PROVIDER=deepseek"
if defined FAKE_HERMES_MARKER (
  echo MODEL=%EFF_MODEL%@%EFF_PROVIDER% >> "%FAKE_HERMES_MARKER%"
)
if defined AAF_TEST_FAIL_MODELS (
  echo %AAF_TEST_FAIL_MODELS% | findstr /C:"%EFF_MODEL%@%EFF_PROVIDER%" >nul
  if not errorlevel 1 (
    echo FAKE HERMES EXECUTOR: simulated model invocation failure for %EFF_MODEL%@%EFF_PROVIDER% >&2
    exit /b 1
  )
)
echo FAKE HERMES EXECUTOR: fresh-runner PAID-ESCALATION-GATE stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001 fresh-runner fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner PAID-ESCALATION-GATE stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001 fresh-runner fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner PAID-ESCALATION-GATE stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_TASK_TMPL = """AAF_TASK_BEGIN
# Task ID
{task_id}

# Task Name
{name}

# Workspace
D:\\AdyAI\\ai-agent-framework

# Objective
{objective}

# Route
hermes -> workbuddy -> codex

# Acceptance
1. 通过

AAF_TASK_END
"""


def _task(task_id: str, risk: str | None, objective: str) -> str:
    body = _TASK_TMPL.format(task_id=task_id, name=task_id, objective=objective)
    if risk is not None:
        body = body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)
    return body


def _make_fakebin(scenario_dir: Path) -> Path:
    fakebin = scenario_dir / "fakebin"
    fakebin.mkdir(parents=True, exist_ok=True)
    (fakebin / "hermes.bat").write_text(_HERMES_BAT, encoding="utf-8")
    (fakebin / "codebuddy.bat").write_text(_CODEBUDDY_BAT, encoding="utf-8")
    (fakebin / "codex.bat").write_text(_CODEX_BAT, encoding="utf-8")
    return fakebin


def _run_scenario(
    scenario_dir: Path,
    task_text: str,
    registry_mode: str,
    extra_env: dict,
) -> dict:
    scenario_dir.mkdir(parents=True, exist_ok=True)
    # 每个场景必须是全新 execution：清掉上次运行的 out/ 与 marker 遗留
    for stale in (scenario_dir / "out",):
        if stale.exists():
            shutil.rmtree(stale)
    for stale_marker in scenario_dir.glob("marker_*"):
        stale_marker.unlink()
    task_file = scenario_dir / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = scenario_dir / "ws"
    ws.mkdir(exist_ok=True)
    out = scenario_dir / "out"
    fakebin = _make_fakebin(scenario_dir)
    marker_hermes = scenario_dir / "marker_hermes.txt"
    marker_codebuddy = scenario_dir / "marker_codebuddy.txt"
    marker_codex = scenario_dir / "marker_codex.txt"
    env = {
        **{
            k: v for k, v in os.environ.items()
            if not k.startswith("AAF_") or k in (
                "AAF_TEST_FAKE_BIN", "AAF_TEST_REGISTRY_MODE",
                "AAF_TEST_FAIL_MODELS",
            )
        },
        "PYTHONPATH": str(ROOT),
        "AAF_TEST_FAKE_BIN": str(fakebin),
        "AAF_TEST_REGISTRY_MODE": registry_mode,
        "FAKE_HERMES_MARKER": str(marker_hermes),
        "FAKE_CODEBUDDY_MARKER": str(marker_codebuddy),
        "FAKE_CODEX_MARKER": str(marker_codex),
        **extra_env,
    }
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), str(task_file), "--workspace", str(ws), "--output", str(out)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        env=env,
    )
    return {
        "proc": proc,
        "out": out,
        "marker_hermes": marker_hermes,
        "marker_codebuddy": marker_codebuddy,
        "marker_codex": marker_codex,
        "scenario_dir": scenario_dir,
    }


def _hermes_models(marker: Path) -> list[str]:
    """marker 中每次 hermes chat invocation 的 MODEL=<model>@<provider> 行。"""
    if not marker.exists():
        return []
    lines = []
    for line in marker.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("MODEL="):
            lines.append(line[len("MODEL="):])
    return lines


def _runtime_audit(out: Path) -> dict:
    path = out / fr.ARTIFACT_FILENAME
    assert path.exists(), f"missing {fr.ARTIFACT_FILENAME} in {out}"
    data = json.loads(path.read_text(encoding="utf-8"))
    fr.validate_fallback_runtime_record(data)
    return data


def _gate_record(out: Path) -> dict | None:
    path = out / fpg.ARTIFACT_FILENAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    fpg.validate_paid_escalation_gate_record(data)
    return data


def _env_probe(proc: subprocess.CompletedProcess) -> dict[str, str]:
    """wrapper 在 runner 进程结束前打印的 AAF_ENV_PROBE|VAR=value 行。"""
    probe: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("AAF_ENV_PROBE|"):
            _, _, kv = line.partition("|")
            var, _, value = kv.partition("=")
            probe[var] = value
    return probe


def _check(
    failures: list[str],
    name: str,
    cond: bool,
    detail: str = "",
) -> None:
    if not cond:
        failures.append(f"{name}: {detail}")


def _assert_no_paid_execution(failures, tag, r, gate, models) -> None:
    """Requirement 12 共享断言：no silent paid execution。"""
    _check(failures, tag, "zzz-paid@remote-api" not in models,
           f"PAID MODEL WAS INVOKED: {models}")
    _check(failures, tag, gate["fallback_attempted"] is False
           and gate["fallback_used"] is False,
           f"gate attempted/used must stay false, got "
           f"{gate['fallback_attempted']}/{gate['fallback_used']}")
    _check(failures, tag, gate["paid_escalation_required"] is True,
           "paid_escalation_required must be true in the gate record")
    ev = " ".join(gate["no_silent_paid_evidence"])
    _check(failures, tag, "no silent paid execution" in ev,
           "no-silent-paid-execution evidence missing")
    probe = _env_probe(r["proc"])
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        _check(failures, tag, probe.get(var) == "-none-",
               f"env not restored at runner exit: {var}={probe.get(var)!r} "
               f"(probe={probe!r})")


def _assert_waiting_no_chain(failures, tag, r) -> None:
    run = json.loads((r["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, tag, run["status"] == "WAITING", f"run status {run['status']}")
    _check(failures, tag, not r["marker_codebuddy"].exists(),
           "chain continued after hermes failure (codebuddy spawned)")


def main() -> int:
    failures: list[str] = []
    summary: list[str] = []

    # ---- N1：paid candidate + NO auth => no paid execution (gate BLOCKED) ----
    n1_dir = EVIDENCE_ROOT / "N1-no-auth-blocked"
    n1_task_id = BASE_TASK_ID + "-N1"
    r1 = _run_scenario(
        n1_dir,
        _task(n1_task_id, "LOW",
              "N1: paid escalation required + no auth => BLOCKED, no paid execution."),
        "pg_paid_only",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models1 = _hermes_models(r1["marker_hermes"])
    _check(failures, "N1", r1["proc"].returncode == 0,
           f"runner exit={r1['proc'].returncode}: {r1['proc'].stderr[-800:]}")
    _check(failures, "N1", len(models1) == 1 and models1[0] == "aaa-orig@custom",
           f"expected exactly one original invocation, got {models1}")
    gate1 = _gate_record(r1["out"])
    _check(failures, "N1", gate1 is not None, "missing paid_escalation_gate.json")
    if gate1 is not None:
        _check(failures, "N1",
               gate1["gate_decision"] == fpg.GATE_DECISION_BLOCKED
               and gate1["authorization_present"] is False,
               f"expected BLOCKED/absent, got {gate1['gate_decision']}")
        _assert_no_paid_execution(failures, "N1", r1, gate1, models1)
    rt1 = _runtime_audit(r1["out"])
    _check(failures, "N1",
           rt1["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
           and rt1["fallback_attempted"] is False,
           f"runtime audit must stay fallback_not_eligible/attempted=false, "
           f"got {rt1['decision']}")
    _assert_waiting_no_chain(failures, "N1", r1)
    summary.append("N1 no-auth: 1 invocation (original only), gate BLOCKED (absent), "
                   "WAITING, no chain, env restored")

    # ---- N2：paid candidate + mismatched auth => no paid execution ----
    n2_dir = EVIDENCE_ROOT / "N2-mismatched-auth-blocked"
    n2_task_id = BASE_TASK_ID + "-N2"
    r2 = _run_scenario(
        n2_dir,
        _task(n2_task_id, "LOW",
              "N2: paid escalation required + mismatched auth => BLOCKED, no paid execution."),
        "pg_paid_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": f"{n2_task_id}|validator|zzz-paid|remote-api",
        },
    )
    models2 = _hermes_models(r2["marker_hermes"])
    _check(failures, "N2", r2["proc"].returncode == 0,
           f"runner exit={r2['proc'].returncode}: {r2['proc'].stderr[-800:]}")
    _check(failures, "N2", len(models2) == 1 and models2[0] == "aaa-orig@custom",
           f"expected exactly one original invocation, got {models2}")
    gate2 = _gate_record(r2["out"])
    _check(failures, "N2", gate2 is not None, "missing paid_escalation_gate.json")
    if gate2 is not None:
        _check(failures, "N2",
               gate2["gate_decision"] == fpg.GATE_DECISION_BLOCKED
               and gate2["authorization_present"] is True
               and gate2["authorization_matched"] is False,
               f"expected BLOCKED/mismatch, got {gate2['gate_decision']}")
        _assert_no_paid_execution(failures, "N2", r2, gate2, models2)
    _runtime_audit(r2["out"])
    _assert_waiting_no_chain(failures, "N2", r2)
    summary.append("N2 mismatched auth: 1 invocation (original only), gate BLOCKED "
                   "(mismatch), WAITING, no chain, env restored")

    # ---- N3：paid candidate + exact auth => AUTHORIZED but STILL no paid
    #          invocation ----
    n3_dir = EVIDENCE_ROOT / "N3-exact-auth-authorized-no-invocation"
    n3_task_id = BASE_TASK_ID + "-N3"
    auth3 = cg.scope_string(n3_task_id, "hermes", "zzz-paid", "remote-api")
    r3 = _run_scenario(
        n3_dir,
        _task(n3_task_id, "LOW",
              "N3: exact auth => gate AUTHORIZED, still no paid invocation."),
        "pg_paid_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": auth3,
        },
    )
    models3 = _hermes_models(r3["marker_hermes"])
    _check(failures, "N3", r3["proc"].returncode == 0,
           f"runner exit={r3['proc'].returncode}: {r3['proc'].stderr[-800:]}")
    _check(failures, "N3", len(models3) == 1 and models3[0] == "aaa-orig@custom",
           f"exact auth must NOT cause a paid invocation, got {models3}")
    gate3 = _gate_record(r3["out"])
    _check(failures, "N3", gate3 is not None, "missing paid_escalation_gate.json")
    if gate3 is not None:
        _check(failures, "N3",
               gate3["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
               and gate3["authorization_present"] is True
               and gate3["authorization_matched"] is True
               and gate3["authorization_consumed"] is True,
               f"expected AUTHORIZED/exact, got {gate3['gate_decision']}")
        _assert_no_paid_execution(failures, "N3", r3, gate3, models3)
    _check(failures, "N3", (r3["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "A0 exact-scope one-time authorization was not claimed at the "
           "admission boundary (A0 semantics must be intact)")
    _runtime_audit(r3["out"])
    _assert_waiting_no_chain(failures, "N3", r3)
    summary.append("N3 exact auth: 1 invocation (original only — AUTHORIZED does NOT "
                   "invoke), gate AUTHORIZED/matched/consumed, WAITING, no chain, env restored")

    # ---- N4：no silent paid execution（N1/N3 marker 证据 + N5 无 gate）----
    summary.append("N4 no-silent-paid: N1/N3 markers contain no zzz-paid@remote-api "
                   "line; gate evidence carries no-silent-paid-execution statements; "
                   "fallback_attempted/used stay false in every gate scenario")

    # ---- N5：既有 FREE fallback 行为保持（free 优先于 paid escalation）----
    n5_dir = EVIDENCE_ROOT / "N5-free-fallback-intact"
    r5 = _run_scenario(
        n5_dir,
        _task(BASE_TASK_ID + "-N5", "LOW",
              "N5: FREE fallback behavior remains intact (free precedes paid escalation)."),
        "pg_free_intact",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models5 = _hermes_models(r5["marker_hermes"])
    _check(failures, "N5", r5["proc"].returncode == 0,
           f"runner exit={r5['proc'].returncode}: {r5['proc'].stderr[-800:]}")
    _check(failures, "N5",
           len(models5) == 2 and models5[0] == "aaa-orig@custom"
           and models5[1] == "zzz-fb@custom",
           f"FREE fallback must execute exactly once, got {models5}")
    rt5 = _runtime_audit(r5["out"])
    _check(failures, "N5",
           rt5["fallback_attempted"] is True and rt5["fallback_used"] is True
           and rt5["fallback_candidate"] == "zzz-fb@custom"
           and rt5["final_actual_model"] == "zzz-fb"
           and rt5["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE,
           f"FREE fallback audit shape mismatch: {rt5['decision']}")
    _check(failures, "N5", _gate_record(r5["out"]) is None,
           "paid escalation gate must not run when a FREE candidate exists")
    run5 = json.loads((r5["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N5", run5["status"] == "SUCCESS",
           f"FREE fallback chain must succeed, got {run5['status']}")
    probe5 = _env_probe(r5["proc"])
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        _check(failures, "N5", probe5.get(var) == "-none-",
               f"env not restored at runner exit: {var}={probe5.get(var)!r}")
    summary.append("N5 FREE fallback intact: original fails -> exactly one zzz-fb free "
                   "fallback, used=true, no gate artifact, SUCCESS, env restored")

    print("=== A5 PAID-ESCALATION-GATE-001 fresh-runner validation summary ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
