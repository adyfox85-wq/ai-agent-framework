"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 — fresh-runner N+1 validation driver
（extend WorkBuddy economic routing to MEDIUM risk）。

本任务扩展 active-routing risk 域（explicit LOW -> explicit LOW + MEDIUM），
按 TASK Fresh Runner 要求必须 fresh-runner N+1。每个 runner 场景用**全新
python 进程**运行真实 runner（wrapper 脚本）；fake hermes/codebuddy/codex
.bat 是真实 child process；fake codebuddy 把完整 argv 落盘 marker（精确证明
实际 invocation 形状）。

  N1（Risk: MEDIUM, real facts/registry, wrapper = medium wrapper 零注入）
      -> 全生命周期 SUCCESS；**MEDIUM 真实数据**：真实 WorkBuddy 候选
      capability_tier=T4 不满足 MEDIUM selector floor T3 → 0 eligible →
      routing_applied=false / routed_model=None / fallback_used=false /
      reason=INSUFFICIENT_ELIGIBLE_CANDIDATES；fake codebuddy marker ARGS 精确
      = "-p --output-format text -y"（CodeBuddy Auto，无 --model）——当前真实
      数据不被人为放宽/伪造（Req 15）。
  N1b（Risk: MEDIUM, controlled medium_two_trustworthy, wrapper = medium
      wrapper + AAF_TEST_ECON_FACTS_MODE=medium_two_trustworthy）-> 受控
      deterministic 场景（fixture/evidence injection，与真实 N1 明确区分）：
      真实 registry 基础上新增两个 MEDIUM-eligible（T3+QUALIFIED）候选
      med-free（FRESH free rank 0）/ med-discount（FRESH discount rank 1）→
      routing_applied=true / selected=routed_model=med-free /
      economically_trustworthy=[med-free, med-discount]；fake codebuddy marker
      ARGS 精确 = "-p --output-format text -y --model med-free"（恰好一个
      --model，无 --effort）；artifact 与真实 invocation 一致；validator
      stage PASS、全链 SUCCESS。
  N2a（Risk: LOW, real facts）-> LOW 回归：routing_applied=false /
      INSUFFICIENT_ECONOMIC_CANDIDATES（trustworthy=1）/ argv 精确 Auto。
  N2b（Risk: LOW, controlled two_trustworthy）-> LOW 回归 routed 分支：
      routing_applied=true / selected=hy4-preview / argv 精确
      "-p --output-format text -y --model hy4-preview"（LOW 行为零变化，Req 9）。
  N3（Risk: HIGH, control）-> 全生命周期 SUCCESS；routing_applied=false /
      routed_model=None / reason=RISK_OUTSIDE_ACTIVE_SLICE；argv 精确 Auto
      无 --model。
  N4（fresh-process check）-> fresh_runner_a4_wb_econ_medium_check.py：
      MEDIUM 真实 → Auto（capability floor T3）；MEDIUM 受控 → routed +
      真实 argv 恰好一个 --model + retry 复用同一 args + 无 silent fallback；
      LOW 回归；HIGH/CRITICAL/missing → Auto；validate/env fail-closed。

用法：python tests/fresh_runner_a4_wb_econ_medium_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002/fresh-runner-validation/
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

WRAPPER = ROOT / "tests" / "fresh_runner_a4_wb_econ_medium_wrapper.py"
FRESH_CHECK = ROOT / "tests" / "fresh_runner_a4_wb_econ_medium_check.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

N1_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-N1-MEDIUM-REAL"
N1B_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-N1B-MEDIUM-CONTROLLED"
N2A_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-N2A-LOW-REAL"
N2B_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-N2B-LOW-CONTROLLED"
N3_TASK_ID = "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-N3-HIGH"

# 受控场景的预期经济 winner。
MEDIUM_WINNER = "med-free"     # MEDIUM 受控 fixture：rank 0 权威免费 outranks rank 1
LOW_WINNER = "hy4-preview"     # LOW 受控 fixture（fix001 同款）：rank 0 outranks rank 1

# 生产 WorkBuddy invocation 的精确形状。
EXPECTED_AUTO_ARGS = "-p --output-format text -y"
EXPECTED_MEDIUM_ROUTED_ARGS = f"-p --output-format text -y --model {MEDIUM_WINNER}"
EXPECTED_LOW_ROUTED_ARGS = f"-p --output-format text -y --model {LOW_WINNER}"

# Hermes stage 的 paid 授权 scope（MEDIUM/HIGH 任务：A3 只路由 LOW → hermes 用
# configured deepseek-v4-flash@deepseek → PAID_OR_UNKNOWN → 需要精确 task-scoped
# 授权；LOW 任务由 A3 路由到本地 qwen3 → ALLOWED_FREE，零授权）。
def _hermes_auth(task_id: str) -> str:
    return f"{task_id}|hermes|deepseek-v4-flash|deepseek"


_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 fresh-runner N+1 fake Hermes CLI.
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
echo Hermes Agent v0.20.5 fake WB-ECON-ROUTING-002-N1
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
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 fresh-runner N+1 fake
rem CodeBuddy CLI (WorkBuddy validator stage). Records the EXACT argv to the
rem marker file: N1 (MEDIUM real) must stay CodeBuddy Auto
rem ("-p --output-format text -y", no --model); N1b (MEDIUM controlled
rem medium_two_trustworthy) must show
rem "-p --output-format text -y --model med-free" (exactly one --model,
rem no --effort); N2b (LOW controlled) must show
rem "-p --output-format text -y --model hy4-preview"; N3 (HIGH) must stay Auto.
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
rem AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 fresh-runner N+1 fake
rem Codex CLI (Reviewer stage).
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
{task_id}

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
    body = _TASK_TMPL.format(task_id=task_id, objective=objective)
    return body.replace("# Objective\n", f"Risk: {risk}\n\n# Objective\n", 1)


def _make_fakebin(scenario_dir: Path) -> Path:
    fakebin = scenario_dir / "fakebin"
    fakebin.mkdir(parents=True, exist_ok=True)
    (fakebin / "hermes.bat").write_text(_HERMES_BAT, encoding="utf-8")
    (fakebin / "codebuddy.bat").write_text(_CODEBUDDY_BAT, encoding="utf-8")
    (fakebin / "codex.bat").write_text(_CODEX_BAT, encoding="utf-8")
    return fakebin


def _run_scenario(scenario_dir: Path, task_text: str, extra_env: dict | None = None,
                  hermes_auth: bool = False) -> dict:
    scenario_dir.mkdir(parents=True, exist_ok=True)
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
    for var in (cg.ENV_MODEL, cg.ENV_PROVIDER, cg.ENV_BASE_URL, cg.ENV_AUTH):
        if var in env:
            del env[var]
    if extra_env:
        env.update(extra_env)
    if hermes_auth:
        env[cg.ENV_AUTH] = _hermes_auth(_task_id_from_text(task_text))
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


def _task_id_from_text(task_text: str) -> str:
    for line in task_text.splitlines():
        line = line.strip()
        if line.startswith("AAF-v0.5-"):
            return line
    return "UNKNOWN-TASK"


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
        "scenario": "N1-medium-real + N1b-medium-controlled + N2a/N2b-low-regression + N3-high-control + N4-fresh-process",
        "task_id": "AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002",
        "purpose": (
            "fresh-runner N+1 for extending WorkBuddy economic active routing "
            "from explicit LOW to explicit LOW + MEDIUM: (N1) a fresh runner "
            "process executes a synthetic explicit Risk: MEDIUM task through the "
            "full hermes -> workbuddy -> codex lifecycle with fake CLIs — under "
            "REAL registry facts the WorkBuddy stage stays CodeBuddy Auto "
            "(real candidates capability_tier=T4 < MEDIUM selector floor T3 -> "
            "0 eligible -> INSUFFICIENT_ELIGIBLE_CANDIDATES), argv exactly "
            "'-p --output-format text -y' (no --model); (N1b) the same MEDIUM "
            "task under a controlled two-trustworthy fixture routes: "
            "routing_applied=true / winner=med-free / argv exactly "
            "'-p --output-format text -y --model med-free' (exactly one --model, "
            "no --effort) with artifact matching the real invocation; (N2a) LOW "
            "real-facts regression stays Auto (INSUFFICIENT_ECONOMIC_CANDIDATES); "
            "(N2b) LOW controlled two-trustworthy regression still routes to "
            "hy4-preview; (N3) HIGH control stays Auto; (N4) a fresh-process "
            "check proves MEDIUM real->Auto, MEDIUM controlled->routed with real "
            "argv exactly one --model + retry reusing the same args (no silent "
            "fallback), LOW regression, HIGH/CRITICAL/missing -> Auto, and "
            "validate/env fail-closed semantics."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: MEDIUM + REAL facts/registry ----------
        n1_dir = EVIDENCE_ROOT / "N1-medium-real-facts-auto"
        n1 = _run_scenario(
            n1_dir,
            _task(N1_TASK_ID, "MEDIUM",
                  "验证 MEDIUM risk 域扩展：真实 registry（WorkBuddy 候选 T4 < MEDIUM floor T3 → 0 eligible）→ WorkBuddy 保持 CodeBuddy Auto（无 --model）；真实数据不被人为放宽/伪造（Req 15）。"),
            hermes_auth=True,
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
            "risk_class": wb_route1.get("risk_class"),
            "routing_applied": wb_route1.get("routing_applied"),
            "selected": wb_route1.get("selected"),
            "routed_model": wb_route1.get("routed_model"),
            "eligible": wb_route1.get("eligible"),
            "fallback_used": wb_route1.get("fallback_used"),
            "reason": (wb_route1.get("reason") or "")[:120],
            "codebuddy_argv": args1,
            "invocation_stays_auto": args1 == EXPECTED_AUTO_ARGS,
        }
        scenario_record["scenarios"]["N1-medium-real-facts-auto"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and wb1.get("verdict") == "PASS"
            and cx1.get("verdict") == "APPROVE"
            and (out1 / "REPORT.md").exists()
            and (out1 / "context_manifest.json").exists()
            and wb_route1.get("risk_class") == "MEDIUM"
            and wb_route1.get("routing_applied") is False
            and wb_route1.get("selected") is None
            and wb_route1.get("routed_model") is None
            and wb_route1.get("eligible") == []
            and wb_route1.get("fallback_used") is False
            and (wb_route1.get("reason") or "").startswith(
                "INSUFFICIENT_ELIGIBLE_CANDIDATES"
            )
            and args1 == EXPECTED_AUTO_ARGS
            and "--model" not in (args1 or "")
        )
        print(f"[N1] MEDIUM real facts -> Auto {'PASS' if ok1 else 'FAIL'} (argv={args1!r})")
        if not ok1:
            failures += 1

        # ---------- N1b: Risk: MEDIUM + CONTROLLED two-trustworthy fixture ----------
        n1b_dir = EVIDENCE_ROOT / "N1b-medium-controlled-two-candidate"
        n1b = _run_scenario(
            n1b_dir,
            _task(N1B_TASK_ID, "MEDIUM",
                  "受控场景：两个 MEDIUM-eligible（T3）+ trustworthy candidates → active route 分支生效，WorkBuddy 真实 invocation 恰好一个 --model <winner>（med-free）。"),
            extra_env={"AAF_TEST_ECON_FACTS_MODE": "medium_two_trustworthy"},
            hermes_auth=True,
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
            "risk_class": wb_route1b.get("risk_class"),
            "routing_applied": wb_route1b.get("routing_applied"),
            "selected": wb_route1b.get("selected"),
            "routed_model": wb_route1b.get("routed_model"),
            "economically_trustworthy": wb_route1b.get("economically_trustworthy"),
            "fallback_used": wb_route1b.get("fallback_used"),
            "codebuddy_argv": args1b,
            "artifact_matches_invocation": (
                bool(wb_route1b.get("routing_applied"))
                and wb_route1b.get("routed_model") == MEDIUM_WINNER
                and args1b == EXPECTED_MEDIUM_ROUTED_ARGS
            ),
        }
        scenario_record["scenarios"]["N1b-medium-controlled-two-candidate"] = record1b
        ok1b = (
            n1b["exit_code"] == 0
            and run1b.get("status") == "SUCCESS"
            and wb1b.get("verdict") == "PASS"
            and cx1b.get("verdict") == "APPROVE"
            and (out1b / "REPORT.md").exists()
            and wb_route1b.get("risk_class") == "MEDIUM"
            and wb_route1b.get("routing_applied") is True
            and wb_route1b.get("selected") == MEDIUM_WINNER
            and wb_route1b.get("routed_model") == MEDIUM_WINNER
            and wb_route1b.get("economically_trustworthy") == [
                MEDIUM_WINNER, "med-discount",
            ]
            and wb_route1b.get("fallback_used") is False
            and args1b == EXPECTED_MEDIUM_ROUTED_ARGS
            and (args1b or "").count("--model") == 1
            and "--effort" not in (args1b or "")
        )
        print(
            f"[N1b] MEDIUM controlled two-candidate -> routed "
            f"{'PASS' if ok1b else 'FAIL'} (argv={args1b!r})"
        )
        if not ok1b:
            failures += 1

        # ---------- N2a: Risk: LOW + REAL facts（LOW 回归：Auto 保持） ----------
        n2a_dir = EVIDENCE_ROOT / "N2a-low-real-facts-auto"
        n2a = _run_scenario(
            n2a_dir,
            _task(N2A_TASK_ID, "LOW",
                  "LOW 回归：真实 economic facts 下经济过滤后只剩 1 个可信候选 → WorkBuddy 保持 CodeBuddy Auto（无 --model），LOW 行为零变化。"),
        )
        out2a = n2a["out"]
        run2a = _read_json(out2a / "run.json") or {}
        wb2a = _read_json(out2a / "workbuddy_result.json") or {}
        cx2a = _read_json(out2a / "codex_result.json") or {}
        wb_route2a = _read_json(out2a / "workbuddy_active_routing.json") or {}
        args2a = _read_codebuddy_marker(n2a["marker_codebuddy"])
        record2a = {
            "exit_code": n2a["exit_code"],
            "run_status": run2a.get("status"),
            "routing_applied": wb_route2a.get("routing_applied"),
            "routed_model": wb_route2a.get("routed_model"),
            "economically_trustworthy_count": len(wb_route2a.get("economically_trustworthy") or []),
            "reason": (wb_route2a.get("reason") or "")[:100],
            "codebuddy_argv": args2a,
        }
        scenario_record["scenarios"]["N2a-low-real-facts-auto"] = record2a
        ok2a = (
            n2a["exit_code"] == 0
            and run2a.get("status") == "SUCCESS"
            and wb2a.get("verdict") == "PASS"
            and cx2a.get("verdict") == "APPROVE"
            and wb_route2a.get("routing_applied") is False
            and wb_route2a.get("routed_model") is None
            and len(wb_route2a.get("economically_trustworthy") or []) == 1
            and (wb_route2a.get("reason") or "").startswith(
                "INSUFFICIENT_ECONOMIC_CANDIDATES"
            )
            and args2a == EXPECTED_AUTO_ARGS
        )
        print(f"[N2a] LOW real facts -> Auto (regression) {'PASS' if ok2a else 'FAIL'} (argv={args2a!r})")
        if not ok2a:
            failures += 1

        # ---------- N2b: Risk: LOW + CONTROLLED two_trustworthy（LOW routed 回归） ----------
        n2b_dir = EVIDENCE_ROOT / "N2b-low-controlled-routed"
        n2b = _run_scenario(
            n2b_dir,
            _task(N2B_TASK_ID, "LOW",
                  "LOW 回归（routed 分支）：受控两可信 fixture → routing_applied=true / winner=hy4-preview / 真实 invocation 恰好一个 --model。"),
            extra_env={"AAF_TEST_ECON_FACTS_MODE": "two_trustworthy"},
        )
        out2b = n2b["out"]
        run2b = _read_json(out2b / "run.json") or {}
        wb2b = _read_json(out2b / "workbuddy_result.json") or {}
        cx2b = _read_json(out2b / "codex_result.json") or {}
        wb_route2b = _read_json(out2b / "workbuddy_active_routing.json") or {}
        args2b = _read_codebuddy_marker(n2b["marker_codebuddy"])
        record2b = {
            "exit_code": n2b["exit_code"],
            "run_status": run2b.get("status"),
            "routing_applied": wb_route2b.get("routing_applied"),
            "selected": wb_route2b.get("selected"),
            "routed_model": wb_route2b.get("routed_model"),
            "codebuddy_argv": args2b,
        }
        scenario_record["scenarios"]["N2b-low-controlled-routed"] = record2b
        ok2b = (
            n2b["exit_code"] == 0
            and run2b.get("status") == "SUCCESS"
            and wb2b.get("verdict") == "PASS"
            and cx2b.get("verdict") == "APPROVE"
            and wb_route2b.get("routing_applied") is True
            and wb_route2b.get("selected") == LOW_WINNER
            and wb_route2b.get("routed_model") == LOW_WINNER
            and args2b == EXPECTED_LOW_ROUTED_ARGS
            and (args2b or "").count("--model") == 1
        )
        print(f"[N2b] LOW controlled two-trustworthy -> routed (regression) {'PASS' if ok2b else 'FAIL'} (argv={args2b!r})")
        if not ok2b:
            failures += 1

        # ---------- N3: Risk: HIGH（control：Auto 保持） ----------
        n3_dir = EVIDENCE_ROOT / "N3-high-control"
        n3 = _run_scenario(
            n3_dir,
            _task(N3_TASK_ID, "HIGH",
                  "验证 control case：HIGH 在 active slice（LOW+MEDIUM）之外 → 保持 CodeBuddy Auto（无 --model）。"),
            hermes_auth=True,
        )
        out3 = n3["out"]
        run3 = _read_json(out3 / "run.json") or {}
        wb3 = _read_json(out3 / "workbuddy_result.json") or {}
        cx3 = _read_json(out3 / "codex_result.json") or {}
        wb_route3 = _read_json(out3 / "workbuddy_active_routing.json") or {}
        args3 = _read_codebuddy_marker(n3["marker_codebuddy"])
        record3 = {
            "exit_code": n3["exit_code"],
            "run_status": run3.get("status"),
            "routing_applied": wb_route3.get("routing_applied"),
            "routed_model": wb_route3.get("routed_model"),
            "fallback_used": wb_route3.get("fallback_used"),
            "reason": (wb_route3.get("reason") or "")[:80],
            "codebuddy_argv": args3,
        }
        scenario_record["scenarios"]["N3-high-control"] = record3
        ok3 = (
            n3["exit_code"] == 0
            and run3.get("status") == "SUCCESS"
            and wb3.get("verdict") == "PASS"
            and cx3.get("verdict") == "APPROVE"
            and (out3 / "REPORT.md").exists()
            and wb_route3.get("routing_applied") is False
            and wb_route3.get("routed_model") is None
            and wb_route3.get("fallback_used") is False
            and (wb_route3.get("reason") or "").startswith(
                "RISK_OUTSIDE_ACTIVE_SLICE"
            )
            and args3 == EXPECTED_AUTO_ARGS
            and "--model" not in (args3 or "")
        )
        print(f"[N3] HIGH control + Auto invocation -> {'PASS' if ok3 else 'FAIL'} (argv={args3!r})")
        if not ok3:
            failures += 1

        # ---------- N4: fresh-process no-silent-fallback / regression check ----------
        n4 = subprocess.run(
            [sys.executable, str(FRESH_CHECK)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        record4 = {
            "exit_code": n4.returncode,
            "stdout_tail": (n4.stdout or "")[-2000:],
            "stderr_tail": (n4.stderr or "")[-1500:],
        }
        scenario_record["scenarios"]["N4-fresh-process-check"] = record4
        ok4 = n4.returncode == 0
        print(f"[N4] fresh-process check (no-silent-fallback + regression) -> {'PASS' if ok4 else 'FAIL'}")
        if not ok4:
            failures += 1
    finally:
        (EVIDENCE_ROOT / "scenario_record.json").write_text(
            json.dumps(scenario_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"fresh-runner A4-WB-ECONOMIC-ROUTING-002 (MEDIUM) N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
