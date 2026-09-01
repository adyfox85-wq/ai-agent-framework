"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 — fresh-runner N+1
validation driver（enforce two-candidate economic routing gate）。

本任务修改了 active routing authority gate（两候选 gate 现在作用于
capability + qualification + trustworthy economics **全部**过滤之后），按 TASK
Fresh Runner 要求必须 fresh-runner N+1。每个 runner 场景用**全新 python 进程**
运行真实 runner（wrapper 脚本）；fake hermes/codebuddy/codex .bat 是真实
child process；fake codebuddy 把完整 argv 落盘 marker（精确证明实际 invocation
形状）。

  N1（Risk: LOW, real facts, wrapper = fresh_runner_wrapper.py 零注入）
      -> 全生命周期 SUCCESS；**FIX-001 核心**：真实 baseline economic facts
      下经济过滤后只有 hy4-preview 一个 trustworthy candidate（deepseek-v4-flash
      freshness UNKNOWN 被经济排除）→ routing_applied=false / routed_model=None /
      fallback_used=false / reason = INSUFFICIENT_ECONOMIC_CANDIDATES；fake
      codebuddy marker ARGS 精确 = "-p --output-format text -y"（CodeBuddy
      Auto，无 --model）——当前真实 facts 不被人为伪造成可路由（Req 13）。
  N1b（Risk: LOW, controlled two_trustworthy, wrapper =
      fresh_runner_a4_wb_econ_fix001_wrapper.py + AAF_TEST_ECON_FACTS_MODE=
      two_trustworthy）-> 受控 deterministic 场景（Req 14，fixture/evidence
      injection，与真实 N1 明确区分）：两个 eligible 候选都有 trustworthy
      economics → routing_applied=true / selected=hy4-preview（rank 0 权威免费
      outranks rank 1 折扣）/ routed_model=hy4-preview / economically_trustworthy
      = [hy4-preview, deepseek-v4-flash]；fake codebuddy marker ARGS 精确 =
      "-p --output-format text -y --model hy4-preview"（恰好一个 --model，
      无 --effort）；artifact 与真实 invocation 一致。
  N2（Risk: HIGH, Fresh Runner B）-> 全生命周期 SUCCESS；routing_applied=false /
      routed_model=None（CodeBuddy Auto 保持）；fake codebuddy marker ARGS 精确 =
      "-p --output-format text -y"（无 --model）；lifecycle/REPORT 正常。
  N3（fresh-process, Fresh Runner C）-> fresh_runner_a4_wb_economic_routing_check.py：
      真实 facts → Auto（INSUFFICIENT_ECONOMIC_CANDIDATES）+ 受控两可信 →
      routed 分支可执行（env apply + run_agent argv 恰好一个 --model）+ 无
      silent fallback（fallback_used=false / retry 复用同一 args / validate
      fail-closed）。

用法：python tests/fresh_runner_a4_wb_economic_routing_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001/fresh-runner-validation/
（不提交）；可用环境变量 AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。

注意：N1 断言 routing_applied=false 依赖真实 facts 中 deepseek-v4-flash
freshness UNKNOWN（daily-only 夜间折扣无日期窗口）——事实层刷新后若
deepseek-v4-flash 获得 FRESH 窗口，N1 会如实变为可路由（这是事实层变化，
不是本 gate 的失败）；N1b 的受控 fixture 则永远稳定。
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
FIX_WRAPPER = ROOT / "tests" / "fresh_runner_a4_wb_econ_fix001_wrapper.py"
FRESH_CHECK = ROOT / "tests" / "fresh_runner_a4_wb_economic_routing_check.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

N1_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001-N1-LOW-REAL"
N1B_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001-N1B-LOW-CONTROLLED"
N2_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001-N2-HIGH"

# 受控场景的预期经济 winner（two_trustworthy fixture：hy4-preview rank 0 权威
# 免费 outranks deepseek-v4-flash rank 1 FRESH discount）。
EXPECTED_WINNER = "hy4-preview"
# 生产 WorkBuddy invocation 的精确形状。
EXPECTED_AUTO_ARGS = "-p --output-format text -y"
EXPECTED_ROUTED_ARGS = "-p --output-format text -y --model hy4-preview"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 fresh-runner N+1 fake Hermes CLI.
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
echo Hermes Agent v0.20.5 fake WB-ECON-ROUTE-FIX001-N1
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
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 fresh-runner N+1 fake
rem CodeBuddy CLI (WorkBuddy validator stage). Records the EXACT argv to the
rem marker file: N1 (LOW, real facts) must stay CodeBuddy Auto
rem ("-p --output-format text -y", no --model); N1b (LOW, controlled
rem two_trustworthy) must show "-p --output-format text -y --model hy4-preview"
rem (exactly one --model, no --effort); N2 (HIGH) must stay Auto.
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
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 fresh-runner N+1 fake Codex CLI
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


def _run_scenario(
    scenario_dir: Path, task_text: str, extra_env: dict,
    wrapper: Path = WRAPPER,
) -> dict:
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
                "AAF_WORKBUDDY_MODEL", "AAF_TEST_ECON_FACTS_MODE"):
        if var in env:
            del env[var]
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(wrapper), str(task_file), "--workspace", str(ws),
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
        "scenario": (
            "N1-low-real-facts-auto + N1b-low-controlled-two-candidate-routed "
            "+ N2-high-auto-control + N3-no-silent-fallback"
        ),
        "task_id": "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001",
        "purpose": (
            "fresh-runner N+1 for the two-candidate economic routing gate: a "
            "fresh runner process executes (N1) a synthetic explicit Risk: LOW "
            "task under REAL baseline economic facts (only hy4-preview "
            "trustworthy; deepseek-v4-flash freshness UNKNOWN) — must stay "
            "CodeBuddy Auto (routing_applied=false / routed_model=None / "
            "INSUFFICIENT_ECONOMIC_CANDIDATES, argv exactly '-p --output-format "
            "text -y', no --model) — the current real facts are NOT fabricated "
            "into a routable state; (N1b) the SAME LOW task under a CONTROLLED "
            "two-trustworthy fixture (evidence injection, clearly distinct from "
            "real runtime) — must active-route (routing_applied=true / "
            "selected=hy4-preview / economically_trustworthy=[hy4-preview, "
            "deepseek-v4-flash] / argv exactly '-p --output-format text -y "
            "--model hy4-preview', exactly one --model, no --effort) proving the "
            "active-route branch still works; (N2) a Risk: HIGH control task — "
            "CodeBuddy Auto preserved; (N3) a fresh-process no-silent-fallback "
            "check (fallback_used=false fixed semantic; retry reuses the SAME "
            "routed args; no hidden Auto/model retry path; validate fail-closed)."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: LOW + REAL facts（Fresh Runner A：必须 Auto） ----------
        n1_dir = EVIDENCE_ROOT / "N1-low-real-facts-auto"
        n1 = _run_scenario(
            n1_dir,
            _task(N1_TASK_ID, "LOW",
                  "验证 FIX-001：真实 economic facts 下经济过滤后只剩 1 个可信候选 → WorkBuddy 保持 CodeBuddy Auto（无 --model）。"),
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
            "reason": (wb_route1.get("reason") or "")[:120],
            "codebuddy_argv": args1,
            "invocation_stays_auto": args1 == EXPECTED_AUTO_ARGS,
        }
        scenario_record["scenarios"]["N1-low-real-facts-auto"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and wb1.get("verdict") == "PASS"
            and cx1.get("verdict") == "APPROVE"
            and (out1 / "REPORT.md").exists()
            and (out1 / "context_manifest.json").exists()
            and wb_route1.get("routing_applied") is False
            and wb_route1.get("selected") is None
            and wb_route1.get("routed_model") is None
            and wb_route1.get("fallback_used") is False
            and len(wb_route1.get("economically_trustworthy") or []) == 1
            and (wb_route1.get("reason") or "").startswith(
                "INSUFFICIENT_ECONOMIC_CANDIDATES"
            )
            and args1 == EXPECTED_AUTO_ARGS
            and "--model" not in (args1 or "")
        )
        print(f"[N1] LOW real facts -> Auto {'PASS' if ok1 else 'FAIL'} (argv={args1!r})")
        if not ok1:
            failures += 1

        # ---------- N1b: Risk: LOW + CONTROLLED two-trustworthy fixture ----------
        # （Req 14：受控 deterministic fresh-process scenario，与真实 N1 明确
        #  区分；fixture/evidence injection 仅存在于 wrapper，生产代码零改动）
        n1b_dir = EVIDENCE_ROOT / "N1b-low-controlled-two-candidate"
        n1b = _run_scenario(
            n1b_dir,
            _task(N1B_TASK_ID, "LOW",
                  "受控场景：两个 qualified + trustworthy candidates → active route 分支仍可执行，WorkBuddy 真实 invocation 恰好一个 --model <winner>。"),
            extra_env={"AAF_TEST_ECON_FACTS_MODE": "two_trustworthy"},
            wrapper=FIX_WRAPPER,
        )
        out1b = n1b["out"]
        run1b = _read_json(out1b / "run.json") or {}
        wb1b = _read_json(out1b / "workbuddy_result.json") or {}
        cx1b = _read_json(out1b / "codex_result.json") or {}
        wb_route1b = _read_json(out1b / "workbuddy_active_routing.json") or {}
        args1b = _read_codebuddy_marker(n1b["marker_codebuddy"])
        record1b = {
            "exit_code": n1b["exit_code"],
            "run_status": run1b.get("status"),
            "workbuddy_verdict": wb1b.get("verdict"),
            "codex_verdict": cx1b.get("verdict"),
            "routing_applied": wb_route1b.get("routing_applied"),
            "selected": wb_route1b.get("selected"),
            "routed_model": wb_route1b.get("routed_model"),
            "fallback_used": wb_route1b.get("fallback_used"),
            "economically_trustworthy": wb_route1b.get("economically_trustworthy"),
            "codebuddy_argv": args1b,
            "artifact_matches_invocation": (
                bool(wb_route1b.get("routing_applied"))
                and wb_route1b.get("routed_model") == EXPECTED_WINNER
                and args1b == EXPECTED_ROUTED_ARGS
            ),
        }
        scenario_record["scenarios"]["N1b-low-controlled-two-candidate"] = record1b
        ok1b = (
            n1b["exit_code"] == 0
            and run1b.get("status") == "SUCCESS"
            and wb1b.get("verdict") == "PASS"
            and cx1b.get("verdict") == "APPROVE"
            and (out1b / "REPORT.md").exists()
            and wb_route1b.get("routing_applied") is True
            and wb_route1b.get("selected") == EXPECTED_WINNER
            and wb_route1b.get("routed_model") == EXPECTED_WINNER
            and wb_route1b.get("fallback_used") is False
            and wb_route1b.get("economically_trustworthy") == [
                EXPECTED_WINNER, "deepseek-v4-flash",
            ]
            and args1b == EXPECTED_ROUTED_ARGS
            and (args1b or "").count("--model") == 1
            and "--effort" not in (args1b or "")
        )
        print(
            f"[N1b] LOW controlled two-candidate -> routed "
            f"{'PASS' if ok1b else 'FAIL'} (argv={args1b!r})"
        )
        if not ok1b:
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
    print(f"fresh-runner A4-WB-ECONOMIC-ROUTING-FIX-001 N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
