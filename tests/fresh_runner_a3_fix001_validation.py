"""AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001 fresh-runner validation driver
（Run N+1，TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001）。

每个场景用**全新 python 进程**运行真实 runner（tests/fresh_runner_a3_fix001_wrapper.py），
fake hermes.bat / codebuddy.bat / codex.bat 是真实 child process；hermes chat 的
env 覆盖证据由 fake CLI 落盘 marker（MODEL=/PROVIDER=/BASE_URL= 行）。

  N1（Risk: LOW + baseline registry）   -> FIX 回归：qwen3 LOCAL_FREE 路径仍真实
       active route（routing_applied=true，qwen3:4b@custom，guard LOCAL_FREE →
       ALLOWED_FREE 零授权，fallback_attempted=false，全链 SUCCESS）。
  N2（Risk: LOW + FREE_PROMO sole registry, control） -> FIX 核心：selector 选中
       FREE_PROMO 候选（A1 语义不变），A3 cost gate 拒绝 → routing_applied=false、
       routed_model=None、configured deepseek-v4-flash@deepseek 保留（guard
       ALLOWED_AUTHORIZED_PAID + AAF_COST_AUTH 精确授权）、child 零 env 覆盖、
       fallback_attempted=false、REPORT/lifecycle SUCCESS。

用法：python tests/fresh_runner_a3_fix001_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001/fresh-runner-validation/（不提交）；
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

from ai_agent_framework import active_routing as ar  # noqa: E402
from ai_agent_framework import cost_guard as cg  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_a3_fix001_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT
    / ".aaf"
    / "AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

N1_TASK_ID = "AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001-N1-LOW"
N2_TASK_ID = "AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001-N2-FREE-PROMO"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A3-FIX-001 fresh-runner N+1 fake Hermes CLI (ASCII only on purpose:
rem cmd.exe parses metacharacters even inside REM lines, so NO > | & % in comments).
rem - `hermes config get model`    -> prints the CURRENT established model config
rem   (deepseek-v4-flash / deepseek): N2 FREE_PROMO control proves routing not applied.
rem - `hermes config get auxiliary`-> local Ollama slots (read-only discovery shape).
rem - `hermes --version` / `--help`-> static text (exit 0).
rem - `hermes chat ...`            -> writes env-based invocation evidence to the
rem   marker file (MODEL/PROVIDER/BASE_URL = the AAF_HERMES_* routing overrides
rem   visible INSIDE the real child process).
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
echo Hermes Agent v0.20.5 fake A3-FIX001-N1
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
echo FAKE HERMES EXECUTOR: fresh-runner N+1 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEBUDDY_BAT = r"""@echo off
rem AAF-v0.5-A3-FIX-001 fresh-runner N+1 fake CodeBuddy CLI (WorkBuddy validator stage).
rem ASCII only on purpose. Echoes the schema-valid WorkBuddy structured result.
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
rem AAF-v0.5-A3-FIX-001 fresh-runner N+1 fake Codex CLI (Reviewer stage).
rem ASCII only on purpose. Echoes the schema-valid Codex structured result.
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


def _run_scenario(scenario_dir: Path, task_text: str, extra_env: dict) -> dict:
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
        "FAKE_HERMES_MARKER": str(marker_hermes),
        "FAKE_CODEBUDDY_MARKER": str(marker_codebuddy),
        "FAKE_CODEX_MARKER": str(marker_codex),
    }
    # A3 路由的 env 必须干净：A3 自己负责设置覆盖（N1）或保持 configured（N2）。
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
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_marker(path: Path) -> dict:
    """解析 fake hermes chat 落盘的 env 证据（MODEL=/PROVIDER=/BASE_URL= 行）。

    N1（routing applied）→ MODEL=qwen3:4b / PROVIDER=custom /
    BASE_URL=http://127.0.0.1:11434/v1；N2（FREE_PROMO 被拒，不路由）→ 三行均为空。
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


def main() -> int:
    failures = 0
    scenario_record: dict = {
        "scenario": "N1-low-baseline-routed + N2-low-free-promo-blocked",
        "task_id": "AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001",
        "purpose": (
            "AAF-v0.5-A3-HERMES-FREE-ROUTING-001-FIX-001 fresh-runner N+1: a fresh "
            "runner process executes (N1) a synthetic explicit Risk: LOW task against "
            "the unchanged A1 baseline registry — active routing still really routes "
            "to qwen3:4b@custom (LOCAL_FREE + QUALIFIED + T4): routing_applied=true, "
            "guard ALLOWED_FREE/LOCAL_FREE, child sees qwen3:4b/custom/local endpoint, "
            "fallback_attempted=false, zero auth claim, full chain SUCCESS; and (N2) "
            "the same explicit Risk: LOW task against a test-only registry whose sole "
            "eligible candidate is FREE_PROMO + QUALIFIED + T4 — the A2 selector still "
            "selects it (A1 FREE_OF_COST_CLASSES semantics unchanged), but the A3 "
            "active-routing cost gate (strictly FREE/LOCAL_FREE) rejects it: "
            "routing_applied=false, routed_model=None, configured "
            "deepseek-v4-flash@deepseek preserved (guard ALLOWED_AUTHORIZED_PAID via "
            "exact AAF_COST_AUTH), zero env overrides in the child, "
            "fallback_attempted=false, REPORT/lifecycle SUCCESS."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: LOW + baseline → active route to qwen3:4b@custom ----------
        n1_dir = EVIDENCE_ROOT / "N1-low-baseline-routed"
        n1 = _run_scenario(
            n1_dir,
            _task(N1_TASK_ID, "LOW",
                  "验证 FIX-001 回归：LOW 任务应仍真实路由到 qwen3:4b@custom。"),
            extra_env={},
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
                "routed_provider": active1.get("routed_provider"),
                "fallback_attempted": active1.get("fallback_attempted"),
                "authoritative": active1.get("authoritative"),
                "reason": active1.get("reason"),
                "configured_model": active1.get("configured_model"),
            },
            "guard": {
                "decision": guard1.get("decision"),
                "cost_class": guard1.get("cost_class"),
                "model": guard1.get("model"),
                "provider": guard1.get("provider"),
            },
            "invocation_env_evidence": {
                "model": marker1.get("model_flag"),
                "provider": marker1.get("provider_flag"),
                "base_url": marker1.get("base_url"),
            },
            "shadow": {
                "authoritative": shadow1.get("authoritative"),
                "execution_affected": shadow1.get("execution_affected"),
                "actual_vs_shadow": shadow1.get("actual_vs_shadow"),
            },
        }
        scenario_record["scenarios"]["N1-low-baseline-routed"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and active1.get("routing_applied") is True
            and active1.get("selected") == "qwen3:4b@custom"
            and active1.get("routed_model") == "qwen3:4b"
            and active1.get("routed_provider") == "custom"
            and active1.get("fallback_attempted") is False
            and active1.get("authoritative") is True
            and guard1.get("decision") == cg.DECISION_ALLOWED_FREE
            and guard1.get("cost_class") == cg.COST_LOCAL_FREE
            and guard1.get("model") == "qwen3:4b"
            and guard1.get("provider") == "custom"
            and marker1.get("model_flag") == "qwen3:4b"
            and marker1.get("provider_flag") == "custom"
            and marker1.get("base_url") == "http://127.0.0.1:11434/v1"
            and shadow1.get("authoritative") is False
            and shadow1.get("execution_affected") is False
            and shadow1.get("actual_vs_shadow") == "SAME"
            and not (out1 / cg.CONSUMPTION_FILENAME).exists()  # ALLOWED_FREE 零 claim
        )
        print(f"[N1] LOW baseline routed -> {'PASS' if ok1 else 'FAIL'}")
        if not ok1:
            failures += 1

        # ---------- N2: Risk: LOW + FREE_PROMO sole registry（control）→ 不路由 ----------
        n2_dir = EVIDENCE_ROOT / "N2-low-free-promo-blocked"
        n2 = _run_scenario(
            n2_dir,
            _task(N2_TASK_ID, "LOW",
                  "验证 FIX-001 control：FREE_PROMO 候选不得 active route，"
                  "configured model 保留。"),
            extra_env={
                "AAF_TEST_REGISTRY_MODE": "promo_sole",
                cg.ENV_AUTH: f"{N2_TASK_ID}|hermes|deepseek-v4-flash|deepseek",
            },
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
                "routed_base_url": active2.get("routed_base_url"),
                "fallback_attempted": active2.get("fallback_attempted"),
                "authoritative": active2.get("authoritative"),
                "reason": active2.get("reason"),
                "configured_model": active2.get("configured_model"),
                "configured_provider": active2.get("configured_provider"),
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
                "authoritative": shadow2.get("authoritative"),
                "actual_vs_shadow": shadow2.get("actual_vs_shadow"),
            },
        }
        scenario_record["scenarios"]["N2-low-free-promo-blocked"] = record2
        ok2 = (
            n2["exit_code"] == 0
            and run2.get("status") == "SUCCESS"
            and active2.get("routing_applied") is False
            and active2.get("selected") == "promo-model@custom"  # selector 语义未变
            and active2.get("routed_model") is None
            and active2.get("routed_provider") is None
            and active2.get("routed_base_url") is None
            and active2.get("fallback_attempted") is False
            and active2.get("authoritative") is True
            and (active2.get("reason") or "").startswith(ar.REASON_SELECTED_NOT_FREE)
            and "FREE_PROMO" in (active2.get("reason") or "")
            and active2.get("configured_model") == "deepseek-v4-flash"
            and active2.get("configured_provider") == "deepseek"
            and guard2.get("decision") == cg.DECISION_ALLOWED_AUTHORIZED_PAID
            and guard2.get("model") == "deepseek-v4-flash"
            and guard2.get("provider") == "deepseek"
            and marker2.get("model_flag") is None  # 无覆盖：configured model 原样
            and marker2.get("provider_flag") is None
            and marker2.get("base_url") is None
            and shadow2.get("authoritative") is False
            and (out2 / cg.CONSUMPTION_FILENAME).exists()  # paid 授权确实被消费
        )
        print(f"[N2] LOW FREE_PROMO blocked -> {'PASS' if ok2 else 'FAIL'}")
        if not ok2:
            failures += 1
    finally:
        (EVIDENCE_ROOT / "scenario_record.json").write_text(
            json.dumps(scenario_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"fresh-runner A3 FIX-001 N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
