"""AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001 fresh-runner validation driver
（Run N+1；TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001）。

每个场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_a3_executor_qualification_fix_wrapper.py），fake hermes.bat /
codebuddy.bat / codex.bat 是真实 child process；hermes chat 的 env 覆盖证据由
fake CLI 落盘 marker（MODEL=/PROVIDER=/BASE_URL= 行）。

  N1（Risk: LOW + baseline registry）   -> FIX 核心（真实证据）：active routing
       **不再**路由 qwen3:4b@custom——其 qualification evidence 只覆盖 auxiliary
       槽位（scope=auxiliary）→ excluded=AUXILIARY_ONLY（可审计）；唯一 main-scope
       eligible = deepseek-v4-flash@deepseek 但 cost=UNKNOWN 非 FREE →
       SELECTED_NOT_FREE → routing_applied=false、configured
       deepseek-v4-flash@deepseek 保留（guard ALLOWED_AUTHORIZED_PAID + 精确
       AAF_COST_AUTH）、child 零 env 覆盖、fallback_attempted=false、全链 SUCCESS。
  N1b（Risk: LOW + aux_sole controlled registry） -> aux-only 池（无任何 main-scope
       合格候选）→ NO_ELIGIBLE → routing_applied=false、configured 保留、
       excluded=AUXILIARY_ONLY、fallback_attempted=false、全链 SUCCESS。
  N2（Risk: LOW + main_free controlled registry） -> 「真正主调用合格的 free
       executor」行为保持支持：scope=main + QUALIFIED + LOCAL_FREE → active route
       真实生效（routing_applied=true、guard 以既有 loopback 判定 LOCAL_FREE →
       ALLOWED_FREE 零授权、child 见 main-free/custom/本地端点、shadow
       actual_vs_shadow=SAME、fallback_attempted=false、全链 SUCCESS）。
  N3（Risk: LOW + main_free + invocation failure） -> 无 silent fallback：routing
       applied 后真实 invocation 失败 → FRAMEWORK_ERROR（child 恰一次）、
       fallback_attempted=false、routing_applied=true 证据保留、run=WAITING。

用法：python tests/fresh_runner_a3_executor_qualification_fix_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001/fresh-runner-validation/
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

from ai_agent_framework import active_routing as ar  # noqa: E402
from ai_agent_framework import cost_guard as cg  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a3_executor_qualification_fix_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

BASE_TASK_ID = "AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A3-EXECUTOR-QUALIFICATION-FIX fresh-runner N+1 fake Hermes CLI
rem (ASCII only on purpose: cmd.exe parses metacharacters even inside REM lines).
rem - `hermes config get model`    -> prints the CURRENT established model config
rem   (deepseek-v4-flash / deepseek): N1/N1b prove routing not applied.
rem - `hermes config get auxiliary`-> local Ollama slots (read-only discovery shape).
rem - `hermes --version` / `--help`-> static text (exit 0).
rem - `hermes chat ...`            -> writes env-based invocation evidence to the
rem   marker file (MODEL/PROVIDER/BASE_URL = the AAF_HERMES_* routing overrides
rem   visible INSIDE the real child process); FAKE_HERMES_FAIL=1 simulates a real
rem   invocation failure (exit 1) to prove no silent fallback (N3).
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
echo Hermes Agent v0.20.5 fake A3-EXECUTOR-QUALIFICATION-FIX
exit /b 0

:help
echo Usage: hermes chat --in DIR -q PROMPT -Q --ignore-rules --source tool
echo Options:
echo   -m MODEL              Set the model
echo   --provider PROVIDER   Set the provider
exit /b 0

:chat
if defined FAKE_HERMES_MARKER (
  echo MODEL=%AAF_HERMES_MODEL% > "%FAKE_HERMES_MARKER%"
  echo PROVIDER=%AAF_HERMES_PROVIDER% >> "%FAKE_HERMES_MARKER%"
  echo BASE_URL=%AAF_HERMES_BASE_URL% >> "%FAKE_HERMES_MARKER%"
)
if defined FAKE_HERMES_FAIL (
  echo FAKE HERMES EXECUTOR: simulated invocation failure >&2
  exit /b 1
)
echo FAKE HERMES EXECUTOR: fresh-runner N+1 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A3-EXECUTOR-QUALIFICATION-FIX fresh-runner N+1 fake CodeBuddy CLI
rem (WorkBuddy validator stage). ASCII only on purpose.
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
rem AAF-v0.5-A3-EXECUTOR-QUALIFICATION-FIX fresh-runner N+1 fake Codex CLI
rem (Reviewer stage). ASCII only on purpose.
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


def _run_scenario(scenario_dir: Path, task_text: str, registry_mode: str,
                  extra_env: dict) -> dict:
    scenario_dir.mkdir(parents=True, exist_ok=True)
    # 每个场景必须是全新 execution：清掉上次运行的 out/ 与 marker 遗留
    # （runner 对已有 snapshot 的目录走 resume 语义，会跳过 Agent 执行）。
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
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "AAF_TEST_FAKE_BIN": str(fakebin),
        "AAF_TEST_REGISTRY_MODE": registry_mode,
        "FAKE_HERMES_MARKER": str(marker_hermes),
        "FAKE_CODEBUDDY_MARKER": str(marker_codebuddy),
        "FAKE_CODEX_MARKER": str(marker_codex),
    }
    # A3 路由的 env 必须干净：A3 自己负责设置覆盖或保持 configured。
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL, cg.ENV_AUTH):
        if var in env:
            del env[var]
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(WRAPPER), str(task_file), "--workspace", str(ws),
         "--output", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, env=env,
    )
    return {
        "dir": scenario_dir,
        "out": out,
        "exit_code": result.returncode,
        "stdout_tail": (result.stdout or "")[-1500:],
        "stderr_tail": (result.stderr or "")[-1500:],
        "marker_hermes": marker_hermes,
        "marker_codebuddy": marker_codebuddy,
        "marker_codex": marker_codex,
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_marker(path: Path) -> dict:
    """解析 fake hermes chat 落盘的 env 证据（MODEL=/PROVIDER=/BASE_URL= 行）。

    routing applied（N2/N3）→ 非空值；不路由（N1/N1b）→ 三行均为空。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"model_flag": None, "provider_flag": None, "base_url": None}
    fields: dict = {"model_flag": None, "provider_flag": None, "base_url": None}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        value = value.strip() or None  # echo 会追加尾随空格
        if key == "MODEL":
            fields["model_flag"] = value
        elif key == "PROVIDER":
            fields["provider_flag"] = value
        elif key == "BASE_URL":
            fields["base_url"] = value
    return fields


def _excluded_reason(active: dict, candidate: str) -> str | None:
    for e in active.get("excluded") or []:
        if e.get("candidate") == candidate:
            return e.get("reason")
    return None


def main() -> int:
    failures = 0
    scenario_record: dict = {
        "scenario": "N1-baseline-no-route + N1b-aux-sole + N2-main-free-routed "
                    "+ N3-main-free-failure-no-fallback",
        "task_id": BASE_TASK_ID,
        "purpose": (
            "fresh-runner N+1 for TASK: AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-"
            "FIX-001 (Requirement 9 fresh-process validation of corrected "
            "self-hosting routing authority): (N1) real baseline facts — LOW "
            "Hermes executor NO LONGER routes to qwen3:4b@custom (aux-only "
            "qualification evidence -> excluded AUXILIARY_ONLY; real main-chat "
            "invocation returns HTTP 400), routing_applied=false, configured "
            "deepseek-v4-flash@deepseek preserved; (N1b) controlled aux-only pool "
            "-> NO_ELIGIBLE, configured preserved; (N2) controlled main-scope "
            "LOCAL_FREE executor still really routes (valid qualified Hermes "
            "executor behavior remains supported, guard ALLOWED_FREE zero auth); "
            "(N3) routed invocation failure -> honest FRAMEWORK_ERROR, "
            "fallback_attempted=false, no silent fallback."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: LOW + baseline（真实证据）→ 不路由 ----------
        n1_dir = EVIDENCE_ROOT / "N1-baseline-no-route"
        n1 = _run_scenario(
            n1_dir,
            _task(f"{BASE_TASK_ID}-N1-LOW", "LOW",
                  "验证 FIX：LOW 任务不得再路由 qwen3:4b@custom（aux-only "
                  "evidence）；configured model 保留。"),
            registry_mode="baseline",
            extra_env={
                cg.ENV_AUTH: f"{BASE_TASK_ID}-N1-LOW|hermes|deepseek-v4-flash|deepseek",
            },
        )
        out1 = n1["out"]
        run1 = _read_json(out1 / "run.json") or {}
        active1 = _read_json(out1 / "active_routing.json") or {}
        guard1 = _read_json(out1 / "cost_guard.json") or {}
        shadow1 = _read_json(out1 / "shadow_observation.json") or {}
        marker1 = _parse_marker(n1["marker_hermes"])
        record1 = {
            "exit_code": n1["exit_code"],
            "run_status": run1.get("status"),
            "active_routing": {
                "routing_applied": active1.get("routing_applied"),
                "selected": active1.get("selected"),
                "routed_model": active1.get("routed_model"),
                "fallback_attempted": active1.get("fallback_attempted"),
                "reason": active1.get("reason"),
                "configured_model": active1.get("configured_model"),
                "qwen3_excluded_reason": _excluded_reason(active1, "qwen3:4b@custom"),
            },
            "guard": {
                "decision": guard1.get("decision"),
                "model": guard1.get("model"),
                "provider": guard1.get("provider"),
            },
            "invocation_env_evidence": {
                "model": marker1.get("model_flag"),
                "provider": marker1.get("provider_flag"),
                "base_url": marker1.get("base_url"),
            },
            "shadow": {
                "selected_candidate": shadow1.get("selected_candidate"),
                "actual_vs_shadow": shadow1.get("actual_vs_shadow"),
            },
        }
        scenario_record["scenarios"]["N1-baseline-no-route"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and active1.get("routing_applied") is False
            and active1.get("selected") == "deepseek-v4-flash@deepseek"
            and active1.get("routed_model") is None
            and active1.get("fallback_attempted") is False
            and (active1.get("reason") or "").startswith(ar.REASON_SELECTED_NOT_FREE)
            and _excluded_reason(active1, "qwen3:4b@custom") == "AUXILIARY_ONLY"
            and active1.get("configured_model") == "deepseek-v4-flash"
            and active1.get("configured_provider") == "deepseek"
            and guard1.get("decision") == cg.DECISION_ALLOWED_AUTHORIZED_PAID
            and guard1.get("model") == "deepseek-v4-flash"
            and guard1.get("provider") == "deepseek"
            and marker1.get("model_flag") is None
            and marker1.get("provider_flag") is None
            and marker1.get("base_url") is None
            and shadow1.get("selected_candidate") == "deepseek-v4-flash@deepseek"
            and shadow1.get("actual_vs_shadow") == "SAME"
        )
        print(f"[N1] baseline LOW no-route -> {'PASS' if ok1 else 'FAIL'}")
        if not ok1:
            failures += 1

        # ---------- N1b: Risk: LOW + aux_sole（受控）→ NO_ELIGIBLE ----------
        n1b_dir = EVIDENCE_ROOT / "N1b-aux-sole-no-route"
        n1b = _run_scenario(
            n1b_dir,
            _task(f"{BASE_TASK_ID}-N1b-LOW-AUX", "LOW",
                  "验证 FIX：仅含 aux-only 候选的池 → 无合格 executor → "
                  "configured model 保留。"),
            registry_mode="aux_sole",
            extra_env={
                cg.ENV_AUTH: (
                    f"{BASE_TASK_ID}-N1b-LOW-AUX|hermes|deepseek-v4-flash|deepseek"
                ),
            },
        )
        out1b = n1b["out"]
        run1b = _read_json(out1b / "run.json") or {}
        active1b = _read_json(out1b / "active_routing.json") or {}
        guard1b = _read_json(out1b / "cost_guard.json") or {}
        marker1b = _parse_marker(n1b["marker_hermes"])
        record1b = {
            "exit_code": n1b["exit_code"],
            "run_status": run1b.get("status"),
            "active_routing": {
                "routing_applied": active1b.get("routing_applied"),
                "selected": active1b.get("selected"),
                "routed_model": active1b.get("routed_model"),
                "fallback_attempted": active1b.get("fallback_attempted"),
                "reason": active1b.get("reason"),
                "aux_excluded_reason": _excluded_reason(active1b, "aux-model@custom"),
            },
            "guard": {"decision": guard1b.get("decision")},
            "invocation_env_evidence": {
                "model": marker1b.get("model_flag"),
                "provider": marker1b.get("provider_flag"),
                "base_url": marker1b.get("base_url"),
            },
        }
        scenario_record["scenarios"]["N1b-aux-sole-no-route"] = record1b
        ok1b = (
            n1b["exit_code"] == 0
            and run1b.get("status") == "SUCCESS"
            and active1b.get("routing_applied") is False
            and active1b.get("selected") is None
            and active1b.get("routed_model") is None
            and active1b.get("fallback_attempted") is False
            and (active1b.get("reason") or "").startswith(ar.REASON_NO_ELIGIBLE)
            and _excluded_reason(active1b, "aux-model@custom") == "AUXILIARY_ONLY"
            and guard1b.get("decision") == cg.DECISION_ALLOWED_AUTHORIZED_PAID
            and marker1b.get("model_flag") is None
            and marker1b.get("provider_flag") is None
            and marker1b.get("base_url") is None
        )
        print(f"[N1b] aux-sole pool no-route -> {'PASS' if ok1b else 'FAIL'}")
        if not ok1b:
            failures += 1

        # ---------- N2: Risk: LOW + main_free（受控）→ 仍真实路由 ----------
        n2_dir = EVIDENCE_ROOT / "N2-main-free-routed"
        n2 = _run_scenario(
            n2_dir,
            _task(f"{BASE_TASK_ID}-N2-LOW-MAIN-FREE", "LOW",
                  "验证 FIX 回归：真正主调用合格的 free executor 仍被 active "
                  "route（valid qualified Hermes executor behavior supported）。"),
            registry_mode="main_free",
            extra_env={},
        )
        out2 = n2["out"]
        run2 = _read_json(out2 / "run.json") or {}
        active2 = _read_json(out2 / "active_routing.json") or {}
        guard2 = _read_json(out2 / "cost_guard.json") or {}
        shadow2 = _read_json(out2 / "shadow_observation.json") or {}
        marker2 = _parse_marker(n2["marker_hermes"])
        record2 = {
            "exit_code": n2["exit_code"],
            "run_status": run2.get("status"),
            "active_routing": {
                "routing_applied": active2.get("routing_applied"),
                "selected": active2.get("selected"),
                "routed_model": active2.get("routed_model"),
                "routed_provider": active2.get("routed_provider"),
                "fallback_attempted": active2.get("fallback_attempted"),
                "reason": active2.get("reason"),
            },
            "guard": {
                "decision": guard2.get("decision"),
                "cost_class": guard2.get("cost_class"),
                "model": guard2.get("model"),
                "provider": guard2.get("provider"),
            },
            "invocation_env_evidence": {
                "model": marker2.get("model_flag"),
                "provider": marker2.get("provider_flag"),
                "base_url": marker2.get("base_url"),
            },
            "shadow": {
                "selected_candidate": shadow2.get("selected_candidate"),
                "actual_vs_shadow": shadow2.get("actual_vs_shadow"),
            },
        }
        scenario_record["scenarios"]["N2-main-free-routed"] = record2
        ok2 = (
            n2["exit_code"] == 0
            and run2.get("status") == "SUCCESS"
            and active2.get("routing_applied") is True
            and active2.get("selected") == "main-free@custom"
            and active2.get("routed_model") == "main-free"
            and active2.get("routed_provider") == "custom"
            and active2.get("fallback_attempted") is False
            and (active2.get("reason") or "").startswith(ar.REASON_APPLIED)
            and guard2.get("decision") == cg.DECISION_ALLOWED_FREE
            and guard2.get("cost_class") == cg.COST_LOCAL_FREE
            and guard2.get("model") == "main-free"
            and guard2.get("provider") == "custom"
            and marker2.get("model_flag") == "main-free"
            and marker2.get("provider_flag") == "custom"
            and marker2.get("base_url") == "http://127.0.0.1:11434/v1"
            and shadow2.get("selected_candidate") == "main-free@custom"
            and shadow2.get("actual_vs_shadow") == "SAME"
            and not (out2 / cg.CONSUMPTION_FILENAME).exists()  # ALLOWED_FREE 零 claim
        )
        print(f"[N2] main-free routed -> {'PASS' if ok2 else 'FAIL'}")
        if not ok2:
            failures += 1

        # ---------- N3: Risk: LOW + main_free + invocation failure → 无 fallback ----------
        n3_dir = EVIDENCE_ROOT / "N3-main-free-failure-no-fallback"
        n3 = _run_scenario(
            n3_dir,
            _task(f"{BASE_TASK_ID}-N3-LOW-FAIL", "LOW",
                  "验证 no-silent-fallback：routed invocation 失败 → 如实 "
                  "FRAMEWORK_ERROR，绝不静默回退其他模型。"),
            registry_mode="main_free",
            extra_env={"FAKE_HERMES_FAIL": "1"},
        )
        out3 = n3["out"]
        run3 = _read_json(out3 / "run.json") or {}
        active3 = _read_json(out3 / "active_routing.json") or {}
        marker3 = _parse_marker(n3["marker_hermes"])
        hermes_result = ""
        try:
            hermes_result = (out3 / "hermes_result.md").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            pass
        record3 = {
            "exit_code": n3["exit_code"],
            "run_status": run3.get("status"),
            "hermes_result_head": hermes_result.splitlines()[:1],
            "active_routing": {
                "routing_applied": active3.get("routing_applied"),
                "fallback_attempted": active3.get("fallback_attempted"),
            },
            "invocation_env_evidence": {
                "model": marker3.get("model_flag"),
                "provider": marker3.get("provider_flag"),
                "base_url": marker3.get("base_url"),
            },
            "codebuddy_spawned": n3["marker_codebuddy"].exists(),
        }
        scenario_record["scenarios"]["N3-main-free-failure-no-fallback"] = record3
        ok3 = (
            n3["exit_code"] == 0
            and run3.get("status") == "WAITING"  # 链中断 → 不伪装 SUCCESS
            and hermes_result.startswith("FRAMEWORK_ERROR")
            and active3.get("routing_applied") is True
            and active3.get("fallback_attempted") is False
            and marker3.get("model_flag") == "main-free"  # 失败前 routing env 已生效
        )
        print(f"[N3] routed failure no-fallback -> {'PASS' if ok3 else 'FAIL'}")
        if not ok3:
            failures += 1
    finally:
        (EVIDENCE_ROOT / "scenario_record.json").write_text(
            json.dumps(scenario_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"fresh-runner A3 EXECUTOR-QUALIFICATION-FIX N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
