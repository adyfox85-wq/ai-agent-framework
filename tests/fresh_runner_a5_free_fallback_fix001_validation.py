"""AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner validation driver
（Run N+1；TASK Requirement 10：全新进程证明 corrected runtime code 实际加载 +
authorized-paid 不能作为 FREE fallback 执行 / audit persistence failure 阻止
fallback 结果接受 / 至多一次 fallback / 无 fallback chain / 无 silent paid）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_free_fallback_fix001_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat invocation 向
marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖 = actual
invocation model）。

  F1（Risk: LOW + fb_paid_admission + AAF_COST_AUTH 精确匹配 zzz-free）:
       FIX-001 收口 #1 —— authorized-paid **不能**作为 FREE fallback 执行：
       aaa-orig（LOCAL_FREE）失败 → A5 候选 zzz-free（registry FREE，A0 权威
       解析 paid + 精确授权 → ALLOWED_AUTHORIZED_PAID）→ 本 FREE-only 单元
       拒绝 → hermes chat 恰 1 次（marker 无 zzz-free@remote-api 行）、audit
       attempted=false / authorization_outcome=ALLOWED_AUTHORIZED_PAID /
       evidence 显式 was-NOT-invoked、run=WAITING（no silent paid execution）。
  F2（Risk: LOW + fb_success + AAF_TEST_AUDIT_SAVE_FAIL=1）:
       FIX-001 收口 #2 —— audit persistence failure 阻止 fallback 结果接受：
       aaa-orig 失败 → fallback zzz-fb **恰一次**调用（marker 2 行 = attempt
       真实发生）且成功输出，但权威 audit 写盘失败 → hermes_result.md =
       FRAMEWORK_ERROR + 显式 audit closure failure、fallback_runtime.json
       不存在、run=WAITING、codebuddy 未 spawn（无 chain）。
  F3（Risk: LOW + fb_success + aaa-orig 与 zzz-fb 都失败）:
       至多一次 model-level fallback / 无第三模型 / 无 chain：hermes chat 恰
       2 次、audit attempted=true used=false final=zzz-fb、WAITING、
       codebuddy 未 spawn。
  F4（Risk: LOW + fb_paid_admission + AAF_COST_AUTH 错误 scope）:
       blocked / unknown-paid 语义 → 无 fallback invocation：hermes chat 恰
       1 次、audit attempted=false / authorization_outcome=BLOCKED、WAITING。

用法：python tests/fresh_runner_a5_free_fallback_fix001_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001/fresh-runner-validation/
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
from ai_agent_framework import fallback_runtime as fr  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a5_free_fallback_fix001_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner fake Hermes CLI
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
echo Hermes Agent v0.20.5 fake A5-FREE-FALLBACK-RUNTIME-FIX-001
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
echo FAKE HERMES EXECUTOR: fresh-runner FIX-001 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner FIX-001 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner FIX-001 stub (no real inference)
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
                "AAF_TEST_AUDIT_SAVE_FAIL",
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

    # ---- F1：authorized-paid 不能作为 FREE fallback 执行（FIX-001 #1）----
    f1_dir = EVIDENCE_ROOT / "F1-authorized-paid-refused"
    f1_task_id = BASE_TASK_ID + "-F1"
    r1 = _run_scenario(
        f1_dir,
        _task(f1_task_id, "LOW", "F1: authorized-paid cannot execute as FREE fallback."),
        "fb_paid_admission",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": f"{f1_task_id}|hermes|zzz-free|remote-api",
        },
    )
    models1 = _hermes_models(r1["marker_hermes"])
    _check(failures, "F1", r1["proc"].returncode == 0,
           f"runner exit={r1['proc'].returncode}: {r1['proc'].stderr[-800:]}")
    _check(failures, "F1", len(models1) == 1 and models1[0] == "aaa-orig@custom",
           f"paid fallback must NOT execute: expected only aaa-orig@custom, got {models1}")
    _check(failures, "F1", "zzz-free@remote-api" not in models1,
           f"authorized-paid candidate executed as FREE fallback: {models1}")
    aud1 = _audit(r1["out"])
    _check(failures, "F1", aud1["fallback_attempted"] is False and aud1["fallback_used"] is False,
           f"expected attempted=false used=false, got {aud1['fallback_attempted']}/{aud1['fallback_used']}")
    _check(failures, "F1", aud1["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID,
           f"auth {aud1['authorization_outcome']} (A0 token must be recorded truthfully)")
    _check(failures, "F1", aud1["fallback_eligible"] is True, "eligible flag mismatch")
    _check(failures, "F1", aud1["final_actual_model"] == aud1["original_model"],
           f"final {aud1['final_actual_model']} must equal original (no switch)")
    _check(failures, "F1",
           any("was NOT invoked" in e for e in aud1["no_silent_fallback_evidence"]),
           "no-silent-paid evidence (was NOT invoked) missing")
    _check(failures, "F1", (r1["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "A0 exact-scope authorization was not claimed at the admission boundary")
    run1 = json.loads((r1["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "F1", run1["status"] == "WAITING", f"run status {run1['status']}")
    summary.append("F1 authorized-paid refused: 1 invocation (no paid model), attempted=false, "
                   "auth=ALLOWED_AUTHORIZED_PAID, WAITING")

    # ---- F2：audit persistence failure 阻止 fallback 结果接受（FIX-001 #2）----
    f2_dir = EVIDENCE_ROOT / "F2-audit-save-fail-failclosed"
    r2 = _run_scenario(
        f2_dir,
        _task(BASE_TASK_ID + "-F2", "LOW", "F2: audit persistence failure => result not accepted."),
        "fb_success",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_TEST_AUDIT_SAVE_FAIL": "1",
        },
    )
    models2 = _hermes_models(r2["marker_hermes"])
    _check(failures, "F2", r2["proc"].returncode == 0,
           f"runner exit={r2['proc'].returncode}: {r2['proc'].stderr[-800:]}")
    _check(failures, "F2", len(models2) == 2 and models2[0] == "aaa-orig@custom"
           and models2[1] == "zzz-fb@custom",
           f"fallback attempt must have happened exactly once, got {models2}")
    result2 = (r2["out"] / "hermes_result.md").read_text(encoding="utf-8")
    _check(failures, "F2", result2.startswith("FRAMEWORK_ERROR"),
           "fallback output was accepted as the stage result despite audit failure")
    _check(failures, "F2", "audit closure" in result2,
           "audit closure failure not surfaced in the stage result")
    _check(failures, "F2", not (r2["out"] / fr.ARTIFACT_FILENAME).exists(),
           "fallback_runtime.json must not exist (authoritative audit never persisted)")
    run2 = json.loads((r2["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "F2", run2["status"] == "WAITING", f"run status {run2['status']}")
    _check(failures, "F2", not r2["marker_codebuddy"].exists(),
           "chain continued after fail-closed hermes failure (codebuddy spawned)")
    summary.append("F2 audit persistence failure: 2 invocations (attempt real), output NOT accepted, "
                   "FRAMEWORK_ERROR + audit closure surfaced, no artifact, WAITING, no chain")

    # ---- F3：至多一次 fallback / 无第三模型 / 无 chain ---- 
    f3_dir = EVIDENCE_ROOT / "F3-one-fallback-no-chain"
    r3 = _run_scenario(
        f3_dir,
        _task(BASE_TASK_ID + "-F3", "LOW", "F3: at most one fallback; no chain; no third model."),
        "fb_success",
        {"AAF_TEST_FAIL_MODELS": "aaa-orig@custom;zzz-fb@custom"},
    )
    models3 = _hermes_models(r3["marker_hermes"])
    _check(failures, "F3", r3["proc"].returncode == 0,
           f"runner exit={r3['proc'].returncode}: {r3['proc'].stderr[-800:]}")
    _check(failures, "F3", len(models3) == 2,
           f"expected exactly 2 invocations (original + 1 fallback, no third), got {models3}")
    aud3 = _audit(r3["out"])
    _check(failures, "F3", aud3["fallback_attempted"] is True and aud3["fallback_used"] is False,
           f"expected attempted=true used=false, got {aud3['fallback_attempted']}/{aud3['fallback_used']}")
    _check(failures, "F3", aud3["final_actual_model"] == "zzz-fb", f"final {aud3['final_actual_model']}")
    run3 = json.loads((r3["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "F3", run3["status"] == "WAITING", f"run status {run3['status']}")
    _check(failures, "F3", not r3["marker_codebuddy"].exists(),
           "chain continued after hermes failure (codebuddy spawned)")
    summary.append("F3 one-fallback no-chain: 2 invocations, attempted=true used=false, WAITING, no third model")

    # ---- F4：blocked / unknown-paid（auth mismatch）→ 无 fallback invocation ----
    f4_dir = EVIDENCE_ROOT / "F4-auth-mismatch-blocked"
    f4_task_id = BASE_TASK_ID + "-F4"
    r4 = _run_scenario(
        f4_dir,
        _task(f4_task_id, "LOW", "F4: blocked/unknown-paid semantics => no fallback invocation."),
        "fb_paid_admission",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": f"{f4_task_id}|hermes|WRONG|scope",  # 存在但不精确匹配
        },
    )
    models4 = _hermes_models(r4["marker_hermes"])
    _check(failures, "F4", r4["proc"].returncode == 0,
           f"runner exit={r4['proc'].returncode}: {r4['proc'].stderr[-800:]}")
    _check(failures, "F4", len(models4) == 1 and models4[0] == "aaa-orig@custom",
           f"blocked admission must not invoke fallback, got {models4}")
    aud4 = _audit(r4["out"])
    _check(failures, "F4", aud4["fallback_attempted"] is False and aud4["fallback_used"] is False,
           f"expected attempted=false, got {aud4['fallback_attempted']}")
    _check(failures, "F4", aud4["authorization_outcome"] == fr.AUTH_OUTCOME_BLOCKED,
           f"auth {aud4['authorization_outcome']} (mismatch => BLOCKED)")
    run4 = json.loads((r4["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "F4", run4["status"] == "WAITING", f"run status {run4['status']}")
    summary.append("F4 auth mismatch blocked: 1 invocation, attempted=false, auth=BLOCKED, WAITING")

    print("=== A5 FREE-FALLBACK-RUNTIME-001-FIX-001 fresh-runner validation summary ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
