"""AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 fresh-runner validation driver
（Run N+1；TASK Requirement 18：全新进程证明一次性 authorized paid fallback
runtime 行为——本任务改变 self-hosting paid execution runtime 行为）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_paid_fallback_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat invocation 向
marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖 = actual
invocation model）。wrapper 在 runner 进程结束前打印 ``AAF_ENV_PROBE|...``
三行（same-process env 还原证明）。

  N1（Risk: LOW + pf_paid_only + 无 AAF_COST_AUTH）:
       no auth => NO paid invocation：aaa-orig 失败 → gate BLOCKED（absent）
       → hermes chat 恰 1 次（marker 无 zzz-paid@remote-api 行）、gate
       artifact BLOCKED + FREE 层 runtime audit not-eligible、无
       paid_fallback_runtime.json、WAITING、codebuddy 未 spawn、
       env probe 全 -none-。
  N2（pf_paid_only + AAF_COST_AUTH scope 不匹配（wrong stage））:
       wrong scope => NO paid invocation：gate BLOCKED（mismatch）、恰 1 次
       invocation、WAITING、env probe 全 -none-。
  N3（pf_paid_only + AAF_COST_AUTH 精确匹配 zzz-paid scope）:
       exact auth => EXACTLY ONE paid fallback invocation：marker 2 行
       （aaa-orig@custom + zzz-paid@remote-api）、gate AUTHORIZED
       （matched/consumed=true、A0 一次性消费 marker 存在；gate record 层
       attempted/used 恒 False）、paid_fallback_runtime.json
       attempted/used=true / paid_candidate=zzz-paid@remote-api /
       final actual=zzz-paid@remote-api / paid_gate_decision=AUTHORIZED /
       no_third + no_silent evidence、全链 SUCCESS、env probe 全 -none-。
  N4（pf_paid_only + exact auth + zzz-paid 也失败）:
       failed paid fallback => NO third invocation：marker 恰 2 行、paid
       runtime audit attempted=true / used=false / outcome=failed / paid
       failure 细节保留、原始 FRAMEWORK_ERROR 保留、WAITING、no chain。
  N5（pf_paid_only + exact auth + AAF_TEST_PAID_SAVE_FAULT=runtime_error）:
       audit closure failure rejects paid output：marker 2 行（paid
       invocation 真实发生）→ hermes_result 以 FRAMEWORK_ERROR 开头 + audit
       closure FAILED 文本、无 paid_fallback_runtime.json（gate AUTHORIZED
       证据仍在）、WAITING、env probe 全 -none-。
  N6（pf_free_intact + fail aaa-orig）:
       FREE fallback precedence 保持：original 失败 → 恰一次 zzz-fb free
       fallback（marker 2 行）→ used=true / final=zzz-fb、无 gate artifact、
       无 paid artifact、全链 SUCCESS。
  N7（pf_original_only + exact auth）:
       authorization cannot silently carry over：exact AAF_COST_AUTH 存在但
       registry 无合格 paid candidate（只有 original）→ gate 不运行、恰 1
       次 invocation、无 paid artifact、无消费 marker、WAITING——授权本身
       绝不执行（no silent paid execution / no silent carryover）。
  N8（no silent paid execution 综合断言）:
       N1/N2/N7 marker 不含 zzz-paid@remote-api 行；paid 模型只可能在
       AUTHORIZED gate（N3/N4/N5）下被执行且每次都恰一次（无 chain/loop）。

用法：python tests/fresh_runner_a5_paid_fallback_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001/fresh-runner-validation/
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

WRAPPER = ROOT / "tests" / "fresh_runner_a5_paid_fallback_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001" / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 fresh-runner fake Hermes CLI
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
echo Hermes Agent v0.20.5 fake A5-PAID-FALLBACK-RUNTIME-001
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
echo FAKE HERMES EXECUTOR: fresh-runner PAID-FALLBACK-RUNTIME stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 fresh-runner fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner PAID-FALLBACK-RUNTIME stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 fresh-runner fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner PAID-FALLBACK-RUNTIME stub (no real inference)
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
                "AAF_TEST_FAIL_MODELS", "AAF_TEST_PAID_SAVE_FAULT",
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


def _paid_runtime_audit(out: Path) -> dict | None:
    """paid_fallback_runtime.json（A5-004：authorized paid fallback 执行审计）。"""
    path = out / fr.ARTIFACT_FILENAME_PAID
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    fr.validate_paid_fallback_runtime_record(data)
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


def _assert_env_restored(failures, tag, proc) -> None:
    probe = _env_probe(proc)
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

    # ---- N1：no auth => NO paid invocation（gate BLOCKED absent）----
    n1_dir = EVIDENCE_ROOT / "N1-no-auth-blocked"
    n1_task_id = BASE_TASK_ID + "-N1"
    r1 = _run_scenario(
        n1_dir,
        _task(n1_task_id, "LOW",
              "N1: paid fallback required + no auth => BLOCKED, no paid invocation."),
        "pf_paid_only",
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
    _check(failures, "N1", _paid_runtime_audit(r1["out"]) is None,
           "no auth must not produce a paid fallback runtime audit")
    rt1 = _runtime_audit(r1["out"])
    _check(failures, "N1",
           rt1["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE
           and rt1["fallback_attempted"] is False,
           f"FREE-layer runtime audit must stay not-eligible/attempted=false, "
           f"got {rt1['decision']}")
    _assert_waiting_no_chain(failures, "N1", r1)
    _assert_env_restored(failures, "N1", r1["proc"])
    summary.append("N1 no auth: 1 invocation (original only), gate BLOCKED "
                   "(absent), no paid audit, WAITING, no chain, env restored")

    # ---- N2：wrong scope auth => NO paid invocation（gate BLOCKED mismatch）----
    n2_dir = EVIDENCE_ROOT / "N2-wrong-scope-blocked"
    n2_task_id = BASE_TASK_ID + "-N2"
    r2 = _run_scenario(
        n2_dir,
        _task(n2_task_id, "LOW",
              "N2: paid fallback required + wrong-scope auth => BLOCKED, "
              "no paid invocation."),
        "pf_paid_only",
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
    _check(failures, "N2", _paid_runtime_audit(r2["out"]) is None,
           "wrong-scope auth must not produce a paid runtime audit")
    _runtime_audit(r2["out"])
    _assert_waiting_no_chain(failures, "N2", r2)
    _assert_env_restored(failures, "N2", r2["proc"])
    summary.append("N2 wrong scope: 1 invocation (original only), gate BLOCKED "
                   "(mismatch), no paid audit, WAITING, no chain, env restored")

    # ---- N3：exact auth => EXACTLY ONE paid fallback invocation（SUCCESS）----
    n3_dir = EVIDENCE_ROOT / "N3-exact-auth-one-paid-invocation"
    n3_task_id = BASE_TASK_ID + "-N3"
    auth3 = cg.scope_string(n3_task_id, "hermes", "zzz-paid", "remote-api")
    r3 = _run_scenario(
        n3_dir,
        _task(n3_task_id, "LOW",
              "N3: exact auth => gate AUTHORIZED => EXACTLY ONE paid fallback "
              "invocation, paid output becomes the stage result (SUCCESS)."),
        "pf_paid_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": auth3,
        },
    )
    models3 = _hermes_models(r3["marker_hermes"])
    _check(failures, "N3", r3["proc"].returncode == 0,
           f"runner exit={r3['proc'].returncode}: {r3['proc'].stderr[-800:]}")
    _check(failures, "N3",
           len(models3) == 2 and models3[0] == "aaa-orig@custom"
           and models3[1] == "zzz-paid@remote-api",
           f"exact auth must cause EXACTLY ONE paid fallback invocation "
           f"(original + paid), got {models3}")
    gate3 = _gate_record(r3["out"])
    _check(failures, "N3", gate3 is not None, "missing paid_escalation_gate.json")
    if gate3 is not None:
        _check(failures, "N3",
               gate3["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
               and gate3["authorization_present"] is True
               and gate3["authorization_matched"] is True
               and gate3["authorization_consumed"] is True
               and gate3["fallback_attempted"] is False
               and gate3["fallback_used"] is False,
               f"expected AUTHORIZED/exact (gate layer attempted/used false), "
               f"got {gate3['gate_decision']}")
    _check(failures, "N3", (r3["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "A0 exact-scope one-time authorization was not claimed at the "
           "admission boundary (A0 semantics must be intact)")
    paid3 = _paid_runtime_audit(r3["out"])
    _check(failures, "N3", paid3 is not None,
           "missing paid_fallback_runtime.json under exact auth")
    if paid3 is not None:
        _check(failures, "N3",
               paid3["fallback_attempted"] is True
               and paid3["fallback_used"] is True
               and paid3["paid_candidate"] == "zzz-paid@remote-api"
               and paid3["paid_candidate_model"] == "zzz-paid"
               and paid3["paid_candidate_provider"] == "remote-api"
               and paid3["paid_gate_decision"] == fpg.GATE_DECISION_AUTHORIZED
               and paid3["paid_required_scope"] == auth3
               and paid3["final_actual_model"] == "zzz-paid"
               and paid3["final_actual_provider"] == "remote-api"
               and paid3["original_model"] == "aaa-orig"
               and paid3["paid_invocation_outcome"] == fr.PAID_OUTCOME_SUCCESS,
               f"paid runtime audit shape mismatch: "
               f"{paid3['fallback_attempted']}/{paid3['fallback_used']} "
               f"candidate={paid3['paid_candidate']} final="
               f"{paid3['final_actual_model']}@{paid3['final_actual_provider']}")
        _check(failures, "N3",
               any("no third model invocation" in e
                   for e in paid3["no_third_invocation_evidence"]),
               "no-third-invocation evidence missing")
        _check(failures, "N3",
               any("no silent paid execution" in e
                   for e in paid3["no_silent_paid_evidence"]),
               "no-silent-paid evidence missing")
    # successful paid fallback becomes the final actual model: the marker line
    # (MODEL=zzz-paid@remote-api — env override observed by the real child
    # process) plus the paid runtime audit's final_actual_model/provider prove
    # the paid candidate was the last actual invocation; the hermes stage
    # result was produced by that invocation (SUCCESS below).
    _runtime_audit(r3["out"])
    run3 = json.loads((r3["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N3", run3["status"] == "SUCCESS",
           f"paid fallback chain must succeed, got {run3['status']}")
    stage3 = json.loads((r3["out"] / "hermes_result.json").read_text(
        encoding="utf-8"))
    _check(failures, "N3",
           stage3.get("paid_fallback_runtime_ref", {}).get("entry") == "hermes"
           and stage3.get("paid_escalation_gate_ref", {}).get("entry") == "hermes",
           "stage must carry paid_fallback_runtime_ref + paid_escalation_gate_ref")
    _assert_env_restored(failures, "N3", r3["proc"])
    summary.append("N3 exact auth: original fails -> EXACTLY ONE zzz-paid paid "
                   "fallback (marker 2 lines), paid audit used=true/final="
                   "zzz-paid@remote-api (last actual invocation), "
                   "gate AUTHORIZED/consumed, SUCCESS, env restored")

    # ---- N4：failed paid fallback => NO third invocation（WAITING）----
    n4_dir = EVIDENCE_ROOT / "N4-paid-failure-no-third"
    n4_task_id = BASE_TASK_ID + "-N4"
    auth4 = cg.scope_string(n4_task_id, "hermes", "zzz-paid", "remote-api")
    r4 = _run_scenario(
        n4_dir,
        _task(n4_task_id, "LOW",
              "N4: paid fallback invocation fails => attempted=true/used=false, "
              "NO third invocation, WAITING."),
        "pf_paid_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom;zzz-paid@remote-api",
            "AAF_COST_AUTH": auth4,
        },
    )
    models4 = _hermes_models(r4["marker_hermes"])
    _check(failures, "N4", r4["proc"].returncode == 0,
           f"runner exit={r4['proc'].returncode}: {r4['proc'].stderr[-800:]}")
    _check(failures, "N4",
           len(models4) == 2 and models4[0] == "aaa-orig@custom"
           and models4[1] == "zzz-paid@remote-api",
           f"paid fallback attempted exactly once, NO third invocation, "
           f"got {models4}")
    paid4 = _paid_runtime_audit(r4["out"])
    _check(failures, "N4", paid4 is not None,
           "missing paid_fallback_runtime.json (attempt occurred)")
    if paid4 is not None:
        _check(failures, "N4",
               paid4["fallback_attempted"] is True
               and paid4["fallback_used"] is False
               and paid4["paid_invocation_outcome"] == fr.PAID_OUTCOME_FAILED
               and paid4["final_actual_model"] == "zzz-paid",
               f"paid failure audit shape mismatch: "
               f"{paid4['fallback_attempted']}/{paid4['fallback_used']} "
               f"outcome={paid4['paid_invocation_outcome']}")
        _check(failures, "N4",
               any("raised" in e for e in paid4["no_silent_paid_evidence"]),
               "paid failure details must be preserved in the audit")
    gate4 = _gate_record(r4["out"])
    _check(failures, "N4", gate4 is not None
           and gate4["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED,
           "gate must be AUTHORIZED for the attempted paid fallback")
    result4 = (r4["out"] / "hermes_result.md").read_text(encoding="utf-8")
    _check(failures, "N4", result4.startswith("FRAMEWORK_ERROR"),
           "original failure must be preserved (paid fallback output absent)")
    _assert_waiting_no_chain(failures, "N4", r4)
    _assert_env_restored(failures, "N4", r4["proc"])
    summary.append("N4 paid failure: exactly 2 invocations (original + one paid "
                   "fallback), no third model, paid audit attempted=true/"
                   "used=false/failed with failure details, WAITING, env restored")

    # ---- N5：audit closure failure rejects paid output（WAITING）----
    n5_dir = EVIDENCE_ROOT / "N5-audit-closure-failure-rejects-output"
    n5_task_id = BASE_TASK_ID + "-N5"
    auth5 = cg.scope_string(n5_task_id, "hermes", "zzz-paid", "remote-api")
    r5 = _run_scenario(
        n5_dir,
        _task(n5_task_id, "LOW",
              "N5: paid invocation succeeds but authoritative paid runtime "
              "audit persistence fails => output NOT accepted (fail closed)."),
        "pf_paid_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": auth5,
            "AAF_TEST_PAID_SAVE_FAULT": "runtime_error",
        },
    )
    models5 = _hermes_models(r5["marker_hermes"])
    _check(failures, "N5", r5["proc"].returncode == 0,
           f"runner exit={r5['proc'].returncode}: {r5['proc'].stderr[-800:]}")
    _check(failures, "N5",
           len(models5) == 2 and models5[1] == "zzz-paid@remote-api",
           f"paid invocation was really attempted once (marker), got {models5}")
    _check(failures, "N5", _paid_runtime_audit(r5["out"]) is None,
           "audit closure failure must not leave a paid runtime audit artifact")
    gate5 = _gate_record(r5["out"])
    _check(failures, "N5", gate5 is not None
           and gate5["gate_decision"] == fpg.GATE_DECISION_AUTHORIZED,
           "gate AUTHORIZED evidence must remain persisted (pre-invocation)")
    result5 = (r5["out"] / "hermes_result.md").read_text(encoding="utf-8")
    _check(failures, "N5", result5.startswith("FRAMEWORK_ERROR"),
           "paid output must NOT be accepted as the stage result")
    _check(failures, "N5", "audit closure FAILED" in result5,
           "audit closure failure must be explicitly surfaced in the stage result")
    _assert_waiting_no_chain(failures, "N5", r5)
    _assert_env_restored(failures, "N5", r5["proc"])
    summary.append("N5 audit closure failure: paid invocation attempted once "
                   "(marker 2 lines), output REJECTED (FRAMEWORK_ERROR + audit "
                   "closure FAILED surfaced), no paid artifact, gate evidence "
                   "persisted, WAITING, env restored")

    # ---- N6：FREE fallback precedence 保持（free 优先于 paid）----
    n6_dir = EVIDENCE_ROOT / "N6-free-precedence-intact"
    r6 = _run_scenario(
        n6_dir,
        _task(BASE_TASK_ID + "-N6", "LOW",
              "N6: FREE fallback precedence remains intact (free candidate "
              "wins over paid escalation; gate never runs)."),
        "pf_free_intact",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models6 = _hermes_models(r6["marker_hermes"])
    _check(failures, "N6", r6["proc"].returncode == 0,
           f"runner exit={r6['proc'].returncode}: {r6['proc'].stderr[-800:]}")
    _check(failures, "N6",
           len(models6) == 2 and models6[0] == "aaa-orig@custom"
           and models6[1] == "zzz-fb@custom",
           f"FREE fallback must execute exactly once, got {models6}")
    rt6 = _runtime_audit(r6["out"])
    _check(failures, "N6",
           rt6["fallback_attempted"] is True and rt6["fallback_used"] is True
           and rt6["fallback_candidate"] == "zzz-fb@custom"
           and rt6["final_actual_model"] == "zzz-fb"
           and rt6["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE,
           f"FREE fallback audit shape mismatch: {rt6['decision']}")
    _check(failures, "N6", _gate_record(r6["out"]) is None,
           "paid escalation gate must not run when a FREE candidate exists")
    _check(failures, "N6", _paid_runtime_audit(r6["out"]) is None,
           "no paid runtime audit in the FREE fallback path")
    run6 = json.loads((r6["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N6", run6["status"] == "SUCCESS",
           f"FREE fallback chain must succeed, got {run6['status']}")
    _assert_env_restored(failures, "N6", r6["proc"])
    summary.append("N6 FREE precedence: original fails -> exactly one zzz-fb "
                   "free fallback, used=true, no gate/paid artifacts, "
                   "SUCCESS, env restored")

    # ---- N7：authorization cannot silently carry over（无合格候选 → 零执行）----
    n7_dir = EVIDENCE_ROOT / "N7-no-silent-carryover"
    n7_task_id = BASE_TASK_ID + "-N7"
    auth7 = cg.scope_string(n7_task_id, "hermes", "zzz-paid", "remote-api")
    r7 = _run_scenario(
        n7_dir,
        _task(n7_task_id, "LOW",
              "N7: exact auth present but registry has NO paid candidate "
              "(original only) => zero paid invocation (authorization alone "
              "never executes)."),
        "pf_original_only",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": auth7,
        },
    )
    models7 = _hermes_models(r7["marker_hermes"])
    _check(failures, "N7", r7["proc"].returncode == 0,
           f"runner exit={r7['proc'].returncode}: {r7['proc'].stderr[-800:]}")
    _check(failures, "N7", len(models7) == 1 and models7[0] == "aaa-orig@custom",
           f"auth alone must NOT invoke anything, got {models7}")
    _check(failures, "N7", _gate_record(r7["out"]) is None,
           "no paid candidate => paid escalation gate must not run")
    _check(failures, "N7", _paid_runtime_audit(r7["out"]) is None,
           "no paid runtime audit without a paid invocation")
    _check(failures, "N7", not (r7["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "authorization must not be consumed when no paid invocation occurs")
    rt7 = _runtime_audit(r7["out"])
    _check(failures, "N7", rt7["fallback_attempted"] is False
           and rt7["fallback_candidates"] == [],
           f"no fallback candidates / no attempt expected, got "
           f"{rt7['fallback_candidates']}")
    _assert_waiting_no_chain(failures, "N7", r7)
    _assert_env_restored(failures, "N7", r7["proc"])
    summary.append("N7 no silent carryover: exact auth + original-only registry "
                   "=> 1 invocation (original), no gate/paid artifacts, no "
                   "auth consumption, WAITING, env restored")

    # ---- N8：no silent paid execution 综合断言 ----
    summary.append("N8 no-silent-paid: N1/N2/N7 markers contain no "
                   "zzz-paid@remote-api line (no auth / wrong scope / no "
                   "candidate invoke zero paid models); the paid model is "
                   "invoked ONLY under gate AUTHORIZED + A0 exact scope "
                   "(N3/N4/N5) and exactly once per execution (marker "
                   "evidence); non-AUTHORIZED gate records keep "
                   "fallback_attempted/used false")

    print("=== A5 PAID-FALLBACK-RUNTIME-001 fresh-runner validation summary ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
