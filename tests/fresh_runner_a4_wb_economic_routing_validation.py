"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 — fresh-runner N+1 validation driver.

本任务改变了 WorkBuddy production invocation authority（LOW 任务首次真实追加
--model），按 TASK Fresh Runner 要求必须 fresh-runner N+1。每个 runner 场景用
**全新 python 进程**运行真实 runner（tests/fresh_runner_wrapper.py）；fake
hermes/codebuddy/codex .bat 是真实 child process；fake codebuddy 把完整 argv
落盘 marker（精确证明实际 invocation 形状）。

  N1（Risk: LOW,  Fresh Runner A）-> 全生命周期 SUCCESS；active economic
      routing 生效：workbuddy_active_routing.json routing_applied=true /
      selected=hy4-preview / routed_model=hy4-preview / fallback_used=false /
      economically_trustworthy=[hy4-preview]（deepseek-v4-flash freshness
      UNKNOWN 被经济排除）；fake codebuddy marker ARGS 精确 =
      "-p --output-format text -y --model hy4-preview"（恰好一个 --model，
      无 --effort）；artifact 与真实 invocation 一致（requirement：artifact
      matches actual invocation）。
  N2（Risk: HIGH, Fresh Runner B）-> 全生命周期 SUCCESS；routing_applied=false /
      routed_model=None（CodeBuddy Auto 保持）；fake codebuddy marker ARGS 精确 =
      "-p --output-format text -y"（无 --model）；lifecycle/REPORT 正常。
  N3（fresh-process, Fresh Runner C）-> 无 silent fallback：全新 python 进程
      断言 fallback_used=false（artifact + fixed semantic）、routed invocation
      的 transport retry 复用同一 args（含 --model，绝不退回 Auto/换模型）、
      _workbuddy_invocation 恰好一个 --model 且无 --effort、validate fail-closed
      （Auto 保持时不得声称 routed_model）。

用法：python tests/fresh_runner_a4_wb_economic_routing_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001/fresh-runner-validation/
（不提交）；可用环境变量 AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。

注意：N1/N2 使用 runner 的真实 freshness 参考时间（wall clock）。N1 断言
routing_applied=true 依赖 hy4-preview 免费窗口（valid_until=2026-09-11T00:00:00+08:00）
仍 FRESH——窗口过期后 N1 会如实 fail（facts 过期 → fail closed 到 Auto 是
预期行为；刷新 = 重新运行 economic probe 并更新事实层）。
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
FRESH_CHECK = ROOT / "tests" / "fresh_runner_a4_wb_economic_routing_check.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

N1_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-N1-LOW"
N2_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-N2-HIGH"

# 预期经济 winner（baseline facts + 2026-09-02 参考时间：RANK_AUTHORITATIVE_CHEAP）。
EXPECTED_WINNER = "hy4-preview"
# 生产 WorkBuddy invocation 的精确形状。
EXPECTED_AUTO_ARGS = "-p --output-format text -y"
EXPECTED_ROUTED_ARGS = "-p --output-format text -y --model hy4-preview"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 fresh-runner N+1 fake Hermes CLI.
rem ASCII only on purpose (cmd.exe parses metacharacters inside REM lines).
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
echo Hermes Agent v0.20.5 fake WB-ECON-ROUTE-N1
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
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 fresh-runner N+1 fake CodeBuddy
rem CLI (WorkBuddy validator stage). Records the EXACT argv to the marker file:
rem N1 (LOW) must show "-p --output-format text -y --model hy4-preview"
rem (exactly one --model, no --effort); N2 (HIGH) must stay CodeBuddy Auto
rem ("-p --output-format text -y", no --model).
if defined FAKE_CODEBUDDY_MARKER (
  echo ARGS=%* > "%FAKE_CODEBUDDY_MARKER%"
)
echo FAKE CODEBUDDY EXECUTOR: fresh-runner N+1 stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"verdict": "PASS", "blocking_rework": false, "blocking_provenance": "structured", "findings": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

_CODEX_BAT = r"""@echo off
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 fresh-runner N+1 fake Codex CLI
rem (Reviewer stage).
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


def _task(task_id: str, risk: str, objective: str) -> str:
    body = _TASK_TMPL.format(task_id=task_id, name=task_id, objective=objective)
    return body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)


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
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "AAF_TEST_FAKE_BIN": str(fakebin),
        "FAKE_HERMES_MARKER": str(marker_hermes),
        "FAKE_CODEBUDDY_MARKER": str(marker_codebuddy),
    }
    # A3/A4 路由的 env 必须干净：A3/A4 自己负责设置覆盖或保持 configured。
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL, cg.ENV_AUTH,
                "AAF_WORKBUDDY_MODEL"):
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
        "marker_codebuddy": marker_codebuddy,
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_codebuddy_marker(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "ARGS":
            return value.strip()
    return None


def main() -> int:
    failures = 0
    scenario_record: dict = {
        "scenario": "N1-low-active-route + N2-high-auto-control + N3-no-silent-fallback",
        "task_id": "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001",
        "purpose": (
            "fresh-runner N+1: a fresh runner process executes (N1) a synthetic "
            "explicit Risk: LOW task and (N2) a Risk: HIGH control task through "
            "the full hermes -> workbuddy -> codex lifecycle with fake CLIs; the "
            "fake codebuddy records its exact argv. N1 must show the ACTIVE "
            "economic route: workbuddy_active_routing.json routing_applied=true / "
            "selected=hy4-preview / routed_model=hy4-preview / fallback_used=false "
            "and the real argv exactly '-p --output-format text -y --model "
            "hy4-preview' (exactly one --model, no --effort) — artifact matches "
            "actual invocation. N2 must preserve CodeBuddy Auto: routing_applied="
            "false / routed_model=None and argv exactly '-p --output-format text "
            "-y' (no --model). N3 is a fresh-process no-silent-fallback check "
            "(fallback_used=false fixed semantic; retry reuses the SAME routed "
            "args; no hidden Auto/model retry path; validate fail-closed)."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: LOW（Fresh Runner A：active economic route） ----------
        n1_dir = EVIDENCE_ROOT / "N1-low"
        n1 = _run_scenario(
            n1_dir,
            _task(N1_TASK_ID, "LOW",
                  "验证 A4 LOW active economic routing：真实 WorkBuddy invocation 携带经济 winner 的 --model。"),
            extra_env={},
        )
        out1 = n1["out"]
        run1 = _read_json(out1 / "run.json") or {}
        wb1 = _read_json(out1 / "workbuddy_result.json") or {}
        cx1 = _read_json(out1 / "codex_result.json") or {}
        wb_route1 = _read_json(out1 / "workbuddy_active_routing.json") or {}
        args1 = _read_codebuddy_marker(n1["marker_codebuddy"])
        record1 = {
            "exit_code": n1["exit_code"],
            "run_status": run1.get("status"),
            "workbuddy_verdict": wb1.get("verdict"),
            "codex_verdict": cx1.get("verdict"),
            "routing_applied": wb_route1.get("routing_applied"),
            "selected": wb_route1.get("selected"),
            "routed_model": wb_route1.get("routed_model"),
            "fallback_used": wb_route1.get("fallback_used"),
            "economically_trustworthy": wb_route1.get("economically_trustworthy"),
            "codebuddy_argv": args1,
            "artifact_matches_invocation": (
                bool(wb_route1.get("routing_applied"))
                and wb_route1.get("routed_model") == EXPECTED_WINNER
                and args1 == EXPECTED_ROUTED_ARGS
            ),
        }
        scenario_record["scenarios"]["N1-low-active-route"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and wb1.get("verdict") == "PASS"
            and cx1.get("verdict") == "APPROVE"
            and (out1 / "REPORT.md").exists()
            and (out1 / "context_manifest.json").exists()
            and wb_route1.get("routing_applied") is True
            and wb_route1.get("selected") == EXPECTED_WINNER
            and wb_route1.get("routed_model") == EXPECTED_WINNER
            and wb_route1.get("fallback_used") is False
            and wb_route1.get("economically_trustworthy") == [EXPECTED_WINNER]
            and args1 == EXPECTED_ROUTED_ARGS
            and (args1 or "").count("--model") == 1
            and "--effort" not in (args1 or "")
        )
        print(f"[N1] LOW active route -> {'PASS' if ok1 else 'FAIL'} (argv={args1!r})")
        if not ok1:
            failures += 1

        # ---------- N2: Risk: HIGH（Fresh Runner B：CodeBuddy Auto 保持） ----------
        n2_dir = EVIDENCE_ROOT / "N2-high-control"
        n2 = _run_scenario(
            n2_dir,
            _task(N2_TASK_ID, "HIGH",
                  "验证 control case：HIGH 任务保持 CodeBuddy Auto（无 --model）。"),
            extra_env={
                cg.ENV_AUTH: f"{N2_TASK_ID}|hermes|deepseek-v4-flash|deepseek",
            },
        )
        out2 = n2["out"]
        run2 = _read_json(out2 / "run.json") or {}
        wb2 = _read_json(out2 / "workbuddy_result.json") or {}
        cx2 = _read_json(out2 / "codex_result.json") or {}
        wb_route2 = _read_json(out2 / "workbuddy_active_routing.json") or {}
        args2 = _read_codebuddy_marker(n2["marker_codebuddy"])
        record2 = {
            "exit_code": n2["exit_code"],
            "run_status": run2.get("status"),
            "workbuddy_verdict": wb2.get("verdict"),
            "codex_verdict": cx2.get("verdict"),
            "routing_applied": wb_route2.get("routing_applied"),
            "routed_model": wb_route2.get("routed_model"),
            "reason": (wb_route2.get("reason") or "")[:80],
            "codebuddy_argv": args2,
            "invocation_stays_auto": args2 == EXPECTED_AUTO_ARGS,
        }
        scenario_record["scenarios"]["N2-high-control"] = record2
        ok2 = (
            n2["exit_code"] == 0
            and run2.get("status") == "SUCCESS"
            and wb2.get("verdict") == "PASS"
            and cx2.get("verdict") == "APPROVE"
            and (out2 / "REPORT.md").exists()
            and wb_route2.get("routing_applied") is False
            and wb_route2.get("routed_model") is None
            and wb_route2.get("fallback_used") is False
            and args2 == EXPECTED_AUTO_ARGS
            and "--model" not in (args2 or "")
        )
        print(f"[N2] HIGH control + Auto invocation -> {'PASS' if ok2 else 'FAIL'} (argv={args2!r})")
        if not ok2:
            failures += 1

        # ---------- N3: fresh-process no-silent-fallback check（Fresh Runner C） ----------
        n3 = subprocess.run(
            [sys.executable, str(FRESH_CHECK)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        record3 = {
            "exit_code": n3.returncode,
            "stdout_tail": (n3.stdout or "")[-1500:],
            "stderr_tail": (n3.stderr or "")[-1500:],
        }
        scenario_record["scenarios"]["N3-no-silent-fallback"] = record3
        ok3 = n3.returncode == 0
        print(f"[N3] fresh-process no-silent-fallback -> {'PASS' if ok3 else 'FAIL'}")
        if not ok3:
            failures += 1
    finally:
        (EVIDENCE_ROOT / "scenario_record.json").write_text(
            json.dumps(scenario_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"fresh-runner A4-WB-ECONOMIC-ROUTING N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
