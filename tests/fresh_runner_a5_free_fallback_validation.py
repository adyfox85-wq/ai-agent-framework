"""AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001 fresh-runner validation driver
（Run N+1；TASK Requirement 12：全新进程证明 corrected runtime code 实际加载 +
bounded fallback / fail closed / no chain / no silent paid）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_free_fallback_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat invocation 向
marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖 = actual
invocation model；无覆盖时 = fake config 的 deepseek-v4-flash@deepseek）。

  N1（Risk: LOW + baseline 真实 registry + AAF_COST_AUTH 精确授权）:
       corrected runtime code loaded / no candidate => fail closed（真实事实）：
       deepseek-v4-flash@deepseek 是唯一 main-scope 候选 = original 自身 →
       same-model 排除 → fallback candidates 空 → hermes chat **恰 1 次**、
       audit attempted=false / decision=fallback_not_eligible / run=WAITING。
  N2（Risk: LOW + fb_success）: A3 初始 routing 到 aaa-orig（LOW + LOCAL_FREE
       main-scope 合格）→ aaa-orig invocation 失败 → A5 fallback **恰一次**到
       zzz-fb → 成功 → hermes chat 恰 2 次（marker MODEL 行 = aaa-orig@custom
       然后 zzz-fb@custom）、audit attempted=true used=true final_actual=
       zzz-fb/custom、run=SUCCESS（at most one model-level fallback + used）。
  N3（Risk: LOW + fb_success + 两者都失败）: fallback failure => no chain：
       hermes chat 恰 2 次（无第三模型）、audit attempted=true used=false
       final_actual=zzz-fb、run=WAITING。
  N4（Risk: LOW + fb_single）: no candidate => fail closed（受控）：hermes chat
       恰 1 次、audit attempted=false、run=WAITING、原始 FRAMEWORK_ERROR 保留。
  N5（Risk: LOW + fb_paid_pool）: no silent paid fallback：paid/unknown-cost
       合格候选存在但被 A5 cost gate 排除 → hermes chat 恰 1 次、audit
       attempted=false、evidence 显式 no-silent-paid、run=WAITING。

用法：python tests/fresh_runner_a5_free_fallback_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001/fresh-runner-validation/
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

from ai_agent_framework import fallback_contract as fc  # noqa: E402
from ai_agent_framework import fallback_runtime as fr  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a5_free_fallback_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME fresh-runner N+1 fake Hermes CLI
rem (ASCII only on purpose: cmd.exe parses metacharacters even inside REM lines).
rem - `hermes config get model`    -> deepseek-v4-flash / deepseek（baseline 事实）
rem - `hermes config get auxiliary`-> local Ollama slots (read-only discovery shape)
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
  if "%3"=="auxiliary" (
    echo vision:
    echo   provider: custom
    echo   model: qwen2.5vl:3b
    echo   base_url: http://127.0.0.1:11434/v1
    echo compression:
    echo   provider: custom
    echo   model: qwen3:4b
    echo   base_url: http://127.0.0.1:11434/v1
  )
)
exit /b 0

:version
echo Hermes Agent v0.20.5 fake A5-FREE-FALLBACK-RUNTIME
exit /b 0

:help
echo Usage: hermes chat --in DIR -q PROMPT -Q --ignore-rules --source tool
echo Options:
echo   -m MODEL              Set the model
echo   --provider PROVIDER   Set the provider
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
echo FAKE HERMES EXECUTOR: fresh-runner N+1 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME fresh-runner N+1 fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner N+1 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME fresh-runner N+1 fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner N+1 stub (no real inference)
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
                "AAF_TEST_FAKE_BIN", "AAF_TEST_REGISTRY_MODE", "AAF_TEST_FAIL_MODELS",
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


def _audit(out: Path) -> dict:
    path = out / fr.ARTIFACT_FILENAME
    assert path.exists(), f"missing {fr.ARTIFACT_FILENAME} in {out}"
    data = json.loads(path.read_text(encoding="utf-8"))
    fr.validate_fallback_runtime_record(data)
    return data


def _check(
    failures: list[str],
    name: str,
    cond: bool,
    detail: str = "",
) -> None:
    if not cond:
        failures.append(f"{name}: {detail}")


def main() -> int:
    failures: list[str] = []
    summary: list[str] = []

    # ---- N1：baseline 真实 registry → no candidate => fail closed ----
    n1_dir = EVIDENCE_ROOT / "N1-baseline-failclosed"
    n1_task_id = BASE_TASK_ID + "-N1"
    auth = f"{n1_task_id}|hermes|deepseek-v4-flash|deepseek"
    r1 = _run_scenario(
        n1_dir,
        _task(n1_task_id, "LOW", "N1: baseline real facts fail-closed."),
        "baseline",
        {
            "AAF_TEST_FAIL_MODELS": "deepseek-v4-flash@deepseek",
            "AAF_COST_AUTH": auth,
        },
    )
    models1 = _hermes_models(r1["marker_hermes"])
    _check(failures, "N1", r1["proc"].returncode == 0, f"runner exit={r1['proc'].returncode}: {r1['proc'].stderr[-800:]}")
    _check(failures, "N1", len(models1) == 1, f"expected exactly 1 hermes invocation, got {models1}")
    aud1 = _audit(r1["out"])
    _check(failures, "N1", aud1["fallback_attempted"] is False and aud1["fallback_used"] is False,
           f"expected attempted=false used=false, got {aud1['fallback_attempted']}/{aud1['fallback_used']}")
    _check(failures, "N1", aud1["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE,
           f"expected fallback_not_eligible, got {aud1['decision']}")
    _check(failures, "N1", aud1["original_model"] == "deepseek-v4-flash",
           f"original model mismatch: {aud1['original_model']}")
    run1 = json.loads((r1["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N1", run1["status"] == "WAITING", f"run status {run1['status']}")
    summary.append(f"N1 baseline fail-closed: 1 invocation, attempted=false, WAITING")

    # ---- N2：fb_success → exactly one fallback, used=true ----
    n2_dir = EVIDENCE_ROOT / "N2-one-fallback-success"
    r2 = _run_scenario(
        n2_dir,
        _task(BASE_TASK_ID + "-N2", "LOW", "N2: exactly one FREE fallback, success."),
        "fb_success",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models2 = _hermes_models(r2["marker_hermes"])
    _check(failures, "N2", r2["proc"].returncode == 0, f"runner exit={r2['proc'].returncode}: {r2['proc'].stderr[-800:]}")
    _check(failures, "N2", len(models2) == 2, f"expected original+fallback = 2 invocations, got {models2}")
    _check(failures, "N2", models2[0] == "aaa-orig@custom", f"original invocation model {models2}")
    _check(failures, "N2", models2[1] == "zzz-fb@custom", f"fallback invocation model {models2}")
    aud2 = _audit(r2["out"])
    _check(failures, "N2", aud2["fallback_attempted"] is True and aud2["fallback_used"] is True,
           f"expected attempted=true used=true, got {aud2['fallback_attempted']}/{aud2['fallback_used']}")
    _check(failures, "N2", aud2["final_actual_model"] == "zzz-fb"
           and aud2["final_actual_provider"] == "custom",
           f"final actual {aud2['final_actual_model']}/{aud2['final_actual_provider']}")
    _check(failures, "N2", aud2["original_model"] == "aaa-orig", f"original {aud2['original_model']}")
    _check(failures, "N2", aud2["decision"] == fc.DECISION_FALLBACK_ELIGIBLE, f"decision {aud2['decision']}")
    _check(failures, "N2", aud2["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_FREE,
           f"auth {aud2['authorization_outcome']}")
    run2 = json.loads((r2["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N2", run2["status"] == "SUCCESS", f"run status {run2['status']}")
    summary.append(f"N2 one fallback success: 2 invocations (aaa-orig -> zzz-fb), used=true, SUCCESS")

    # ---- N3：fb_success + both fail → no chain / no third model ----
    n3_dir = EVIDENCE_ROOT / "N3-fallback-failure-no-chain"
    r3 = _run_scenario(
        n3_dir,
        _task(BASE_TASK_ID + "-N3", "LOW", "N3: fallback failure => no chain."),
        "fb_success",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom;zzz-fb@custom"},
    )
    models3 = _hermes_models(r3["marker_hermes"])
    _check(failures, "N3", r3["proc"].returncode == 0, f"runner exit={r3['proc'].returncode}: {r3['proc'].stderr[-800:]}")
    _check(failures, "N3", len(models3) == 2, f"expected exactly 2 invocations (no third), got {models3}")
    aud3 = _audit(r3["out"])
    _check(failures, "N3", aud3["fallback_attempted"] is True and aud3["fallback_used"] is False,
           f"expected attempted=true used=false, got {aud3['fallback_attempted']}/{aud3['fallback_used']}")
    _check(failures, "N3", aud3["final_actual_model"] == "zzz-fb", f"final {aud3['final_actual_model']}")
    run3 = json.loads((r3["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N3", run3["status"] == "WAITING", f"run status {run3['status']}")
    _check(failures, "N3", (r3["marker_codebuddy"].exists() is False),
           "chain continued after hermes failure (codebuddy spawned)")
    summary.append(f"N3 fallback failure no chain: 2 invocations, attempted=true used=false, WAITING")

    # ---- N4：fb_single → no candidate => fail closed (controlled) ----
    n4_dir = EVIDENCE_ROOT / "N4-no-candidate-failclosed"
    r4 = _run_scenario(
        n4_dir,
        _task(BASE_TASK_ID + "-N4", "LOW", "N4: no other candidate => fail closed."),
        "fb_single",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models4 = _hermes_models(r4["marker_hermes"])
    _check(failures, "N4", r4["proc"].returncode == 0, f"runner exit={r4['proc'].returncode}: {r4['proc'].stderr[-800:]}")
    _check(failures, "N4", len(models4) == 1, f"expected exactly 1 invocation (same-model excluded), got {models4}")
    aud4 = _audit(r4["out"])
    _check(failures, "N4", aud4["fallback_attempted"] is False and aud4["fallback_used"] is False,
           f"expected attempted=false, got {aud4['fallback_attempted']}")
    _check(failures, "N4", aud4["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE, f"decision {aud4['decision']}")
    _check(failures, "N4", aud4["fallback_candidates"] == [], f"candidates {aud4['fallback_candidates']}")
    result4 = (r4["out"] / "hermes_result.md").read_text(encoding="utf-8")
    _check(failures, "N4", result4.startswith("FRAMEWORK_ERROR"), "original failure not preserved")
    run4 = json.loads((r4["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N4", run4["status"] == "WAITING", f"run status {run4['status']}")
    summary.append(f"N4 no candidate fail closed: 1 invocation, attempted=false, WAITING")

    # ---- N5：fb_paid_pool → no silent paid fallback ----
    n5_dir = EVIDENCE_ROOT / "N5-no-silent-paid"
    r5 = _run_scenario(
        n5_dir,
        _task(BASE_TASK_ID + "-N5", "LOW", "N5: paid/unknown candidates never silently used."),
        "fb_paid_pool",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom"},
    )
    models5 = _hermes_models(r5["marker_hermes"])
    _check(failures, "N5", r5["proc"].returncode == 0, f"runner exit={r5['proc'].returncode}: {r5['proc'].stderr[-800:]}")
    _check(failures, "N5", len(models5) == 1, f"expected exactly 1 invocation (paid excluded), got {models5}")
    aud5 = _audit(r5["out"])
    _check(failures, "N5", aud5["fallback_attempted"] is False, f"attempted {aud5['fallback_attempted']}")
    _check(failures, "N5", aud5["decision"] == fc.DECISION_FALLBACK_NOT_ELIGIBLE, f"decision {aud5['decision']}")
    _check(failures, "N5", "zzz-paid" not in str(aud5.get("fallback_candidates") or [])
           and "mmm-unk" not in str(aud5.get("fallback_candidates") or []),
           f"paid/unknown leaked into candidates: {aud5['fallback_candidates']}")
    _check(failures, "N5", any("never silently used" in n for n in aud5.get("notes") or []),
           "cost-gate exclusion note missing")
    _check(failures, "N5", aud5["authorization_outcome"] == fr.AUTH_OUTCOME_NONE,
           f"auth {aud5['authorization_outcome']} (no candidate -> no admission flow)")
    run5 = json.loads((r5["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "N5", run5["status"] == "WAITING", f"run status {run5['status']}")
    summary.append(f"N5 no silent paid: 1 invocation, paid/unknown excluded, attempted=false, WAITING")

    print("=== A5 FREE-FALLBACK-RUNTIME fresh-runner validation summary ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
