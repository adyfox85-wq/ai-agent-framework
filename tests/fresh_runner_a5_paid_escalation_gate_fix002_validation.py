"""AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner validation driver
（Requirement 12：fresh-runner closure——本任务改变 self-hosting paid
authorization **exact scope** 语义，必须在新进程证明）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_paid_escalation_gate_fix002_wrapper.py），fake
hermes.bat / codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat
invocation 向 marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖
= actual invocation model）。wrapper 在 runner 进程结束前打印
``AAF_ENV_PROBE|...`` 三行（same-process env 还原证明）。

  P1（pg_paid_only + guard_mode=guard_wrong_task_scope）:
       A0 record 的 required_scope 编码**别的 task**（model/provider/stage
       维度全对）→ gate FAIL_CLOSED「scope mismatch」；权威
       paid_escalation_gate.json **存在且 validator 通过**；normalized
       authorization_matched=False（raw 矛盾不进 normalized 字段）而
       source_guard_record 保留 raw decision/matched=True + wrong scope
       （可观察）；零 paid invocation（marker 恰 1 行 aaa-orig@custom）；无
       A0 消费 marker；WAITING、env probe 全 -none-。
  P2（guard_mode=guard_wrong_stage_scope）:
       required_scope 编码错误 stage → FAIL_CLOSED「scope mismatch」、
       artifact 存在 + validator 通过、normalized matched=False、source
       wrong scope 可观察、零 paid invocation、env 还原。
  P3（real A0 + exact AAF_COST_AUTH）:
       exact-valid authorization 行为保持：gate AUTHORIZED（matched/consumed
       true、A0 一次性消费 marker 存在）但**仍零 paid invocation**（marker 恰
       1 行）、WAITING、env 还原。
  P4（pg_free_intact + real A0）:
       FREE fallback 行为保持：original 失败 → 恰一次 zzz-fb free fallback
       （marker 2 行）→ used=true / final=zzz-fb、无 gate artifact、SUCCESS。
  P5（guard_mode=guard_exact_scope）:
       脚本化 **canonical exact scope** record（task/stage/model/provider 全
       对）→ gate AUTHORIZED（exact canonical scope 仍被授权）但零 paid
       invocation + 无消费 marker（脚本化 guard 不 claim——interpret 层只
       转述）+ WAITING + env 还原。

用法：python tests/fresh_runner_a5_paid_escalation_gate_fix002_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002/fresh-runner-validation/
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
from ai_agent_framework import fallback_paid_gate as fpg  # noqa: E402
from ai_agent_framework import fallback_runtime as fr  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a5_paid_escalation_gate_fix002_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002"
_WRONG_TASK_ID = BASE_TASK_ID + "-WRONG-TASK"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner fake Hermes CLI
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
echo Hermes Agent v0.20.5 fake A5-PAID-ESCALATION-GATE-001-FIX-002
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
echo FAKE HERMES EXECUTOR: fresh-runner PAID-ESCALATION-GATE-FIX002 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner PAID-ESCALATION-GATE-FIX002 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 fresh-runner fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner PAID-ESCALATION-GATE-FIX002 stub (no real inference)
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
    guard_mode: str,
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
                "AAF_TEST_FAIL_MODELS", "AAF_TEST_GUARD_MODE",
            )
        },
        "PYTHONPATH": str(ROOT),
        "AAF_TEST_FAKE_BIN": str(fakebin),
        "AAF_TEST_REGISTRY_MODE": registry_mode,
        "AAF_TEST_GUARD_MODE": guard_mode,
        "FAKE_HERMES_MARKER": str(marker_hermes),
        "FAKE_CODEBUDDY_MARKER": str(marker_codebuddy),
        "FAKE_CODEX_MARKER": str(marker_codex),
        **extra_env,
    }
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), str(task_file),
         "--workspace", str(ws), "--output", str(out)],
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


def _check(failures, name, cond, detail="") -> None:
    if not cond:
        failures.append(f"{name}: {detail}")


def _assert_no_paid_execution(failures, tag, r, gate, models) -> None:
    """共享断言：no silent paid execution + env 还原。"""
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


def _assert_scope_mismatch_fail_closed(failures, tag, r, wrong_scope) -> dict:
    """FIX-002 共享断言：scope mismatch → FAIL_CLOSED authoritative audit 存在
    + validator 通过 + normalized flags 恒 False/guard_decision None +
    required_scope type-safe echo + artifact 落盘 + raw wrong scope 证据可观察。"""
    gate = _gate_record(r["out"])
    _check(failures, tag, gate is not None,
           "missing paid_escalation_gate.json (blocker: artifact not persisted)")
    if gate is None:
        return {}
    _check(failures, tag, gate["gate_decision"] == fpg.GATE_DECISION_FAIL_CLOSED,
           f"expected FAIL_CLOSED, got {gate['gate_decision']}")
    _check(failures, tag, "scope mismatch" in gate["gate_reason"],
           f"expected scope-mismatch reason, got {gate['gate_reason']!r}")
    _check(failures, tag,
           gate["authorization_present"] is False
           and gate["authorization_matched"] is False
           and gate["authorization_consumed"] is False,
           "normalized authorization flags must all be false under FAIL_CLOSED: "
           f"{gate['authorization_present']}/"
           f"{gate['authorization_matched']}/{gate['authorization_consumed']}")
    _check(failures, tag, gate["guard_decision"] is None,
           "in-scope ALLOWED_AUTHORIZED_PAID must not appear in normalized "
           f"guard_decision under FAIL_CLOSED, got {gate['guard_decision']!r}")
    _check(failures, tag, gate["required_scope"] == wrong_scope,
           f"required_scope type-safe echo must expose the wrong scope for "
           f"audit, got {gate['required_scope']!r}")
    src = gate["source_guard_record"]
    _check(failures, tag, src is not None
           and src["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
           and src["authorization_matched"] is True
           and src["required_scope"] == wrong_scope,
           f"raw wrong-scope source evidence must stay observable: {src!r}")
    _assert_no_paid_execution(failures, tag, r, gate,
                              _hermes_models(r["marker_hermes"]))
    return gate


def main() -> int:
    failures: list[str] = []
    summary: list[str] = []

    # ---- P1：required_scope 编码别的 task（wrong task scope）→ FAIL_CLOSED
    #      + artifact 存在/valid + raw 证据可观察 ----
    p1_dir = EVIDENCE_ROOT / "P1-wrong-task-scope"
    p1_task_id = BASE_TASK_ID + "-P1"
    wrong1 = cg.scope_string(_WRONG_TASK_ID, "hermes", "zzz-paid", "remote-api")
    r1 = _run_scenario(
        p1_dir,
        _task(p1_task_id, "LOW",
              "P1: A0 record claims exact authorization for a DIFFERENT task "
              "(wrong task scope) => gate FAIL_CLOSED, authoritative audit "
              "persisted and valid, raw wrong-scope evidence observable."),
        "pg_paid_only",
        "guard_wrong_task_scope",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    _check(failures, "P1", r1["proc"].returncode == 0,
           f"runner exit={r1['proc'].returncode}: {r1['proc'].stderr[-800:]}")
    models1 = _hermes_models(r1["marker_hermes"])
    _check(failures, "P1",
           len(models1) == 1 and models1[0] == "aaa-orig@custom",
           f"expected exactly one original invocation (no paid), got {models1}")
    _assert_scope_mismatch_fail_closed(failures, "P1", r1, wrong1)
    _check(failures, "P1", not (r1["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "scripted wrong-scope guard must not claim/consume authorization")
    _runtime_audit(r1["out"])
    _assert_waiting_no_chain(failures, "P1", r1)
    summary.append("P1 wrong task scope: FAIL_CLOSED scope-mismatch, artifact "
                   "persisted+valid, raw wrong-scope source observable, "
                   "1 original invocation only, no claim, WAITING, env restored")

    # ---- P2：required_scope 编码错误 stage（wrong stage scope）----
    p2_dir = EVIDENCE_ROOT / "P2-wrong-stage-scope"
    p2_task_id = BASE_TASK_ID + "-P2"
    wrong2 = cg.scope_string(p2_task_id, "validator", "zzz-paid", "remote-api")
    r2 = _run_scenario(
        p2_dir,
        _task(p2_task_id, "LOW",
              "P2: A0 record claims exact authorization for a DIFFERENT stage "
              "(wrong stage scope) => gate FAIL_CLOSED, authoritative audit "
              "persisted and valid."),
        "pg_paid_only",
        "guard_wrong_stage_scope",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    _check(failures, "P2", r2["proc"].returncode == 0,
           f"runner exit={r2['proc'].returncode}: {r2['proc'].stderr[-800:]}")
    models2 = _hermes_models(r2["marker_hermes"])
    _check(failures, "P2",
           len(models2) == 1 and models2[0] == "aaa-orig@custom",
           f"expected exactly one original invocation (no paid), got {models2}")
    _assert_scope_mismatch_fail_closed(failures, "P2", r2, wrong2)
    _runtime_audit(r2["out"])
    _assert_waiting_no_chain(failures, "P2", r2)
    summary.append("P2 wrong stage scope: FAIL_CLOSED scope-mismatch, artifact "
                   "persisted+valid, raw wrong-scope source observable, no "
                   "paid, WAITING, env restored")

    # ---- P3：exact-valid authorization 行为保持（real A0）----
    p3_dir = EVIDENCE_ROOT / "P3-exact-auth-unchanged"
    p3_task_id = BASE_TASK_ID + "-P3"
    auth3 = cg.scope_string(p3_task_id, "hermes", "zzz-paid", "remote-api")
    r3 = _run_scenario(
        p3_dir,
        _task(p3_task_id, "LOW",
              "P3: exact-valid authorization behavior unchanged => gate "
              "AUTHORIZED but still no paid invocation."),
        "pg_paid_only",
        "real",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": auth3,
        },
    )
    _check(failures, "P3", r3["proc"].returncode == 0,
           f"runner exit={r3['proc'].returncode}: {r3['proc'].stderr[-800:]}")
    models3 = _hermes_models(r3["marker_hermes"])
    _check(failures, "P3",
           len(models3) == 1 and models3[0] == "aaa-orig@custom",
           f"exact auth must NOT cause a paid invocation, got {models3}")
    gate3 = _gate_record(r3["out"])
    _check(failures, "P3", gate3 is not None, "missing paid_escalation_gate.json")
    if gate3 is not None:
        _check(failures, "P3",
               gate3["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
               and gate3["authorization_present"] is True
               and gate3["authorization_matched"] is True
               and gate3["authorization_consumed"] is True
               and gate3["required_scope"] == auth3,
               f"expected AUTHORIZED/exact canonical scope unchanged, got "
               f"{gate3['gate_decision']} scope={gate3['required_scope']!r}")
        _check(failures, "P3",
               isinstance(gate3["source_guard_record"], dict)
               and gate3["source_guard_record"]["decision"]
               == cg.DECISION_ALLOWED_AUTHORIZED_PAID,
               "AUTHORIZED record must still carry the raw A0 source snapshot")
        _assert_no_paid_execution(failures, "P3", r3, gate3, models3)
    _check(failures, "P3", (r3["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "A0 exact-scope one-time authorization was not claimed at the "
           "admission boundary (A0 semantics must be intact)")
    _runtime_audit(r3["out"])
    _assert_waiting_no_chain(failures, "P3", r3)
    summary.append("P3 exact auth unchanged: gate AUTHORIZED/matched/consumed "
                   "with real A0 + canonical exact scope, still zero paid "
                   "invocation, WAITING, env restored")

    # ---- P4：FREE fallback 行为保持（real A0 + pg_free_intact）----
    p4_dir = EVIDENCE_ROOT / "P4-free-fallback-unchanged"
    r4 = _run_scenario(
        p4_dir,
        _task(BASE_TASK_ID + "-P4", "LOW",
              "P4: FREE fallback behavior unchanged (free precedes paid "
              "escalation)."),
        "pg_free_intact",
        "real",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    _check(failures, "P4", r4["proc"].returncode == 0,
           f"runner exit={r4['proc'].returncode}: {r4['proc'].stderr[-800:]}")
    models4 = _hermes_models(r4["marker_hermes"])
    _check(failures, "P4",
           len(models4) == 2 and models4[0] == "aaa-orig@custom"
           and models4[1] == "zzz-fb@custom",
           f"FREE fallback must execute exactly once, got {models4}")
    rt4 = _runtime_audit(r4["out"])
    _check(failures, "P4",
           rt4["fallback_attempted"] is True and rt4["fallback_used"] is True
           and rt4["fallback_candidate"] == "zzz-fb@custom"
           and rt4["final_actual_model"] == "zzz-fb"
           and rt4["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE,
           f"FREE fallback audit shape mismatch: {rt4['decision']}")
    _check(failures, "P4", _gate_record(r4["out"]) is None,
           "paid escalation gate must not run when a FREE candidate exists")
    run4 = json.loads((r4["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "P4", run4["status"] == "SUCCESS",
           f"FREE fallback chain must succeed, got {run4['status']}")
    probe4 = _env_probe(r4["proc"])
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        _check(failures, "P4", probe4.get(var) == "-none-",
               f"env not restored at runner exit: {var}={probe4.get(var)!r}")
    summary.append("P4 FREE fallback unchanged: original fails -> exactly one "
                   "zzz-fb free fallback, used=true, no gate artifact, "
                   "SUCCESS, env restored")

    # ---- P5：脚本化 canonical exact scope → AUTHORIZED（仍零 paid）----
    p5_dir = EVIDENCE_ROOT / "P5-exact-canonical-scope-authorized"
    p5_task_id = BASE_TASK_ID + "-P5"
    exact5 = cg.scope_string(p5_task_id, "hermes", "zzz-paid", "remote-api")
    r5 = _run_scenario(
        p5_dir,
        _task(p5_task_id, "LOW",
              "P5: scripted A0 record with the exact canonical task/stage/"
              "model/provider scope => gate AUTHORIZED but still zero paid "
              "invocation (authorization is eligibility only)."),
        "pg_paid_only",
        "guard_exact_scope",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    _check(failures, "P5", r5["proc"].returncode == 0,
           f"runner exit={r5['proc'].returncode}: {r5['proc'].stderr[-800:]}")
    models5 = _hermes_models(r5["marker_hermes"])
    _check(failures, "P5",
           len(models5) == 1 and models5[0] == "aaa-orig@custom",
           f"exact canonical scope must NOT cause a paid invocation, got "
           f"{models5}")
    gate5 = _gate_record(r5["out"])
    _check(failures, "P5", gate5 is not None, "missing paid_escalation_gate.json")
    if gate5 is not None:
        _check(failures, "P5",
               gate5["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
               and gate5["authorization_present"] is True
               and gate5["authorization_matched"] is True
               and gate5["required_scope"] == exact5,
               f"expected AUTHORIZED for the exact canonical scope, got "
               f"{gate5['gate_decision']} scope={gate5['required_scope']!r}")
        _assert_no_paid_execution(failures, "P5", r5, gate5, models5)
    _check(failures, "P5", not (r5["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "scripted exact-scope guard does not itself claim (interpret only "
           "transcribes A0 flags; no consumption marker expected)")
    _runtime_audit(r5["out"])
    _assert_waiting_no_chain(failures, "P5", r5)
    summary.append("P5 exact canonical scope: gate AUTHORIZED with canonical "
                   "task/stage/model/provider required_scope, zero paid "
                   "invocation, WAITING, env restored")

    print("=== A5 PAID-ESCALATION-GATE-001-FIX-002 fresh-runner closure ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
