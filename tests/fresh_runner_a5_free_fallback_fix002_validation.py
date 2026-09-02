"""AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002 fresh-runner validation driver
（Run N+1；TASK Requirement 11：全新进程证明——fallback 第二模型已实际
invocation 后，audit validation / serialization / persistence 的**未预期
异常**（RuntimeError / UnicodeError——Codex REQUEST_CHANGE 唯一 blocker：
_emit 原只捕获 ValueError/TypeError/OSError）被统一收口为显式 fail-closed
结果：异常被捕获、attempted=true / used=false 保持可观察、fallback 输出被
拒绝、无第三 invocation、env 还原、无 silent paid fallback）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a5_free_fallback_fix002_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；每次 hermes chat invocation 向
marker 文件 append 一行 ``MODEL=<model>@<provider>``（env 覆盖 = actual
invocation model）。wrapper 在 runner 进程结束前打印 ``AAF_ENV_PROBE|...``
三行（same-process env 还原证明）。

  G1（Risk: LOW + fb_success + AAF_TEST_AUDIT_VALIDATE_FAULT=runtime_error）:
       audit validator 抛未预期 RuntimeError（fallback 已成功 invocation）：
       aaa-orig 失败 → fallback zzz-fb **恰一次**调用（marker 2 行 = attempt
       真实发生）且成功输出 → 权威 audit 校验抛 RuntimeError → 异常被收口
       （不裸逃逸）：hermes_result.md = FRAMEWORK_ERROR +
       `FRAMEWORK_ERROR[a5-fallback audit closure failed]` 显式 append（stderr
       无 "layer error"）、fallback_runtime.json 不存在、run=WAITING、
       codebuddy 未 spawn（无 chain）、env probe 全 -none-（还原）。
  G2（Risk: LOW + fb_success + AAF_TEST_AUDIT_SAVE_FAULT=runtime_error）:
       audit persistence 抛未预期 RuntimeError：同 G1 断言形状。
  G3（Risk: LOW + fb_success + AAF_TEST_AUDIT_SAVE_FAULT=unicode_error）:
       audit serialization/persistence 抛未预期 UnicodeError：同 G1 断言形状。
  G4（Risk: LOW + fb_paid_admission + AAF_COST_AUTH 精确匹配 zzz-free）:
       FIX-001 保护回归（Requirement 8，新进程复证）：authorized-paid **不**
       能作为 FREE fallback 执行——aaa-orig 失败 → A5 候选 zzz-free（registry
       FREE，A0 权威解析 paid + 精确授权 → ALLOWED_AUTHORIZED_PAID）→
       FREE-only 单元拒绝 → hermes chat 恰 1 次（marker 无 zzz-free@remote-api
       行）、audit attempted=false / authorization_outcome=
       ALLOWED_AUTHORIZED_PAID、WAITING、env probe 全 -none-。

用法：python tests/fresh_runner_a5_free_fallback_fix002_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002/fresh-runner-validation/
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

WRAPPER = ROOT / "tests" / "fresh_runner_a5_free_fallback_fix002_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002 fresh-runner fake Hermes CLI
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
echo Hermes Agent v0.20.5 fake A5-FREE-FALLBACK-RUNTIME-FIX-002
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
echo FAKE HERMES EXECUTOR: fresh-runner FIX-002 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002 fresh-runner fake CodeBuddy CLI.
if defined FAKE_CODEBUDDY_MARKER (
  echo SPAWNED > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner FIX-002 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002 fresh-runner fake Codex CLI.
if defined FAKE_CODEX_MARKER (
  echo SPAWNED > "%FAKE_CODEX_MARKER%"
)
echo FAKE CODEX EXECUTOR: fresh-runner FIX-002 stub (no real inference)
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
                "AAF_TEST_AUDIT_SAVE_FAIL", "AAF_TEST_AUDIT_VALIDATE_FAULT",
                "AAF_TEST_AUDIT_SAVE_FAULT",
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


def _assert_audit_closure_fail_closed(failures, scenario, r) -> None:
    """G1–G3 共享断言：未预期 audit-closure 异常被收口为 fail-closed。"""
    tag = scenario
    models = _hermes_models(r["marker_hermes"])
    _check(failures, tag, r["proc"].returncode == 0,
           f"runner exit={r['proc'].returncode}: {r['proc'].stderr[-800:]}")
    # fallback 第二模型**恰一次**真实 invocation（attempt 事实保留，无第三模型）
    _check(failures, tag, len(models) == 2 and models[0] == "aaa-orig@custom"
           and models[1] == "zzz-fb@custom",
           f"fallback attempt must have happened exactly once, got {models}")
    result = (r["out"] / "hermes_result.md").read_text(encoding="utf-8")
    _check(failures, tag, result.startswith("FRAMEWORK_ERROR"),
           "fallback output was accepted as the stage result despite audit failure")
    # runner 消费结构化 fail-closed outcome（显式 append），不是泛化 layer error
    _check(failures, tag, "FRAMEWORK_ERROR[a5-fallback audit closure failed]" in result,
           "structured audit closure failure marker missing from the stage result")
    _check(failures, tag, "audit closure" in result,
           "audit closure failure not surfaced in the stage result")
    _check(failures, tag, "layer error" not in (r["proc"].stderr or ""),
           "audit-closure exception was reduced to a generic layer error")
    _check(failures, tag, not (r["out"] / fr.ARTIFACT_FILENAME).exists(),
           "fallback_runtime.json must not exist (authoritative audit never persisted)")
    run = json.loads((r["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, tag, run["status"] == "WAITING", f"run status {run['status']}")
    _check(failures, tag, not r["marker_codebuddy"].exists(),
           "chain continued after fail-closed hermes failure (codebuddy spawned)")
    probe = _env_probe(r["proc"])
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        _check(failures, tag, probe.get(var) == "-none-",
               f"env not restored at runner exit: {var}={probe.get(var)!r} "
               f"(probe={probe!r})")


def main() -> int:
    failures: list[str] = []
    summary: list[str] = []

    # ---- G1：audit validator 抛未预期 RuntimeError（fallback 已 invocation）----
    g1_dir = EVIDENCE_ROOT / "G1-validator-runtime-error-failclosed"
    r1 = _run_scenario(
        g1_dir,
        _task(BASE_TASK_ID + "-G1", "LOW",
              "G1: audit validator RuntimeError after fallback success => fail closed."),
        "fb_success",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_TEST_AUDIT_VALIDATE_FAULT": "runtime_error",
        },
    )
    _assert_audit_closure_fail_closed(failures, "G1", r1)
    summary.append("G1 validator RuntimeError: 2 invocations (attempt real), output NOT accepted, "
                   "FRAMEWORK_ERROR + audit closure surfaced, no artifact, WAITING, no chain, env restored")

    # ---- G2：audit persistence 抛未预期 RuntimeError ----
    g2_dir = EVIDENCE_ROOT / "G2-save-runtime-error-failclosed"
    r2 = _run_scenario(
        g2_dir,
        _task(BASE_TASK_ID + "-G2", "LOW",
              "G2: audit persistence RuntimeError after fallback success => fail closed."),
        "fb_success",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_TEST_AUDIT_SAVE_FAULT": "runtime_error",
        },
    )
    _assert_audit_closure_fail_closed(failures, "G2", r2)
    summary.append("G2 persistence RuntimeError: 2 invocations, output NOT accepted, "
                   "FRAMEWORK_ERROR + audit closure surfaced, WAITING, no chain, env restored")

    # ---- G3：audit serialization/persistence 抛未预期 UnicodeError ----
    g3_dir = EVIDENCE_ROOT / "G3-save-unicode-error-failclosed"
    r3 = _run_scenario(
        g3_dir,
        _task(BASE_TASK_ID + "-G3", "LOW",
              "G3: audit persistence UnicodeError after fallback success => fail closed."),
        "fb_success",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_TEST_AUDIT_SAVE_FAULT": "unicode_error",
        },
    )
    _assert_audit_closure_fail_closed(failures, "G3", r3)
    summary.append("G3 persistence UnicodeError: 2 invocations, output NOT accepted, "
                   "FRAMEWORK_ERROR + audit closure surfaced, WAITING, no chain, env restored")

    # ---- G4：FIX-001 保护回归——authorized-paid 不能作为 FREE fallback 执行 ----
    g4_dir = EVIDENCE_ROOT / "G4-authorized-paid-refused"
    g4_task_id = BASE_TASK_ID + "-G4"
    r4 = _run_scenario(
        g4_dir,
        _task(g4_task_id, "LOW",
              "G4: authorized-paid cannot execute as FREE fallback (FIX-001 intact)."),
        "fb_paid_admission",
        {
            "AAF_TEST_FAIL_MODELS": "aaa-orig@custom",
            "AAF_COST_AUTH": f"{g4_task_id}|hermes|zzz-free|remote-api",
        },
    )
    models4 = _hermes_models(r4["marker_hermes"])
    _check(failures, "G4", r4["proc"].returncode == 0,
           f"runner exit={r4['proc'].returncode}: {r4['proc'].stderr[-800:]}")
    _check(failures, "G4", len(models4) == 1 and models4[0] == "aaa-orig@custom",
           f"paid fallback must NOT execute: expected only aaa-orig@custom, got {models4}")
    _check(failures, "G4", "zzz-free@remote-api" not in models4,
           f"authorized-paid candidate executed as FREE fallback: {models4}")
    aud4 = _audit(r4["out"])
    _check(failures, "G4", aud4["fallback_attempted"] is False and aud4["fallback_used"] is False,
           f"expected attempted=false used=false, got {aud4['fallback_attempted']}/{aud4['fallback_used']}")
    _check(failures, "G4", aud4["authorization_outcome"] == fr.AUTH_OUTCOME_ALLOWED_AUTHORIZED_PAID,
           f"auth {aud4['authorization_outcome']} (A0 token must be recorded truthfully)")
    _check(failures, "G4", aud4["fallback_eligible"] is True, "eligible flag mismatch")
    _check(failures, "G4", aud4["final_actual_model"] == aud4["original_model"],
           f"final {aud4['final_actual_model']} must equal original (no switch)")
    _check(failures, "G4",
           any("was NOT invoked" in e for e in aud4["no_silent_fallback_evidence"]),
           "no-silent-paid evidence (was NOT invoked) missing")
    _check(failures, "G4", (r4["out"] / cg.CONSUMPTION_FILENAME).exists(),
           "A0 exact-scope authorization was not claimed at the admission boundary")
    run4 = json.loads((r4["out"] / "run.json").read_text(encoding="utf-8"))
    _check(failures, "G4", run4["status"] == "WAITING", f"run status {run4['status']}")
    _check(failures, "G4", not r4["marker_codebuddy"].exists(),
           "chain continued after hermes failure (codebuddy spawned)")
    probe4 = _env_probe(r4["proc"])
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL):
        _check(failures, "G4", probe4.get(var) == "-none-",
               f"env not restored at runner exit: {var}={probe4.get(var)!r}")
    summary.append("G4 authorized-paid refused: 1 invocation (no paid model), attempted=false, "
                   "auth=ALLOWED_AUTHORIZED_PAID, WAITING, env restored")

    print("=== A5 FREE-FALLBACK-RUNTIME-001-FIX-002 fresh-runner validation summary ===")
    for line in summary:
        print(f"- {line}")
    print(f"FAILURES: {len(failures)}")
    for f in failures:
        print(f"- FAIL: {f}")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
