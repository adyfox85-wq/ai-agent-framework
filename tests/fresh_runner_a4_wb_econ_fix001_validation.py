"""AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 — fresh-runner N+1 validation driver.

本任务收紧未来 A4 会消费的经济 authority 语义（fail-closed：缺失/自相矛盾的
经济元数据永远不能成为 authoritative cheap/free），按 TASK Fresh Runner 要求
必须 fresh-runner N+1。每个 runner 场景用**全新 python 进程**运行真实 runner
（tests/fresh_runner_wrapper.py）；fake hermes/codebuddy/codex .bat 是真实
child process；fake codebuddy 把完整 argv 落盘 marker（精确证明实际
invocation 形状——A4 FIX-001 起，真实 economic facts 下经济过滤后只有
hy4-preview 一个可信候选 → LOW 任务保持 CodeBuddy Auto；事实层本身不会
自动加 --model）。

  N1（Risk: LOW）  -> 全生命周期 SUCCESS；fake codebuddy marker ARGS 精确 =
                      "-p --output-format text -y"（CodeBuddy Auto，无 --model
                      ——FIX-001：真实 facts 只有 1 个可信候选，两候选 gate 后
                      不路由）；lifecycle/REPORT 正常（框架生命周期正常）。
  N2（fresh-process artifact + authority check）-> 全新 python 进程证明：
                      economic observation artifact（economic_facts.json）仍可
                      正常读取（facts_from_dict 解析成功、15 候选齐全、
                      freshness 与 classify_freshness(observed_at) 一致）+ 路由
                      权威零变化（selector LOW workbuddy 仍只选
                      deepseek-v4-flash；invocation 仍精确 Auto）。
  N3（fresh-process artifact regeneration）-> 全新 python 进程运行事实层
                      artifact 生成器（generate_facts_artifact.py，子进程）：
                      经济 artifact 仍可正常**生成**，重新生成的 economic_facts.json
                      可再读（facts_from_dict 解析、15 候选、hy3/hy4-preview
                      FRESH + authoritative cheap @ observed_at 不变）。
  N4（fresh-process fail-closed check）-> 全新 python 进程证明收紧后的
                      fail-closed 语义：multiplier=None / promotion_factor=None
                      的 FRESH discount 无已知便宜 rank；free+nonzero factor /
                      free+nonzero multiplier / discount 内部矛盾 / STALE /
                      UNKNOWN / raw 无法解释 parsed 值 → 一律不权威；
                      基线事实与路由权威零变化。

用法：python tests/fresh_runner_a4_wb_econ_fix001_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001/fresh-runner-validation/
（不提交）；可用环境变量 AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent_framework import cost_guard as cg  # noqa: E402
from ai_agent_framework.workbuddy_economics import (  # noqa: E402
    WORKBUDDY_CANDIDATE_IDS,
    facts_from_dict,
    is_authoritative_cheap,
)

WRAPPER = ROOT / "tests" / "fresh_runner_wrapper.py"
ARTIFACT_CHECK = ROOT / "tests" / "fresh_runner_a4_wb_econ_artifact_check.py"
FAILCLOSED_CHECK = ROOT / "tests" / "fresh_runner_a4_wb_econ_fix001_failclosed_check.py"
GENERATOR = (
    ROOT / ".aaf" / "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001"
    / "economic_probe" / "generate_facts_artifact.py"
)
ARTIFACT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001"
    / "economic_probe" / "economic_facts.json"
)
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

N1_TASK_ID = "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001-N1-LOW"

# production WorkBuddy invocation 的精确 Auto 形状（无 --model / --effort）。
# FIX-001（AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001）：真实 economic
# facts 下经济过滤后只有 1 个可信候选 → 两候选 gate 不满足 → LOW 任务保持
# CodeBuddy Auto（事实层本身从不自动加 --model）。
EXPECTED_AUTO_ARGS = "-p --output-format text -y"

_HERMES_BAT = r"""@echo off
rem AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 fresh-runner N+1 fake Hermes CLI.
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
echo Hermes Agent v0.20.5 fake WB-ECON-FIX001-N1
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
rem AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 fresh-runner N+1 fake
rem CodeBuddy CLI (WorkBuddy validator stage). Records the EXACT argv to the
rem marker file: production invocation must stay CodeBuddy Auto
rem ([-p --output-format text -y]), NO --model / --effort may appear even
rem though the economic fact layer now stores per-candidate multipliers and
rem promotions.
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
rem AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 fresh-runner N+1 fake
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


def _run_scenario(scenario_dir: Path, task_text: str, extra_env: dict | None = None) -> dict:
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
        "scenario": "N1-low + N2-artifact-authority + N3-regenerate + N4-failclosed",
        "task_id": "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001",
        "purpose": (
            "fresh-runner N+1 for the tightened economic fail-closed semantics: "
            "(N1) a fresh runner process executes a synthetic explicit Risk: LOW "
            "task through the full hermes -> workbuddy -> codex lifecycle with "
            "fake CLIs — the fake codebuddy records its exact argv. Since A4 "
            "FIX-001 (two-candidate economic routing gate), a LOW task's "
            "WorkBuddy stage stays CodeBuddy Auto under REAL economic facts "
            "(only hy4-preview is economically trustworthy -> gate requires "
            ">= 2): N1 argv is exactly '-p --output-format text -y' (no --model, "
            "no --effort); (N2) a fresh-process "
            "check proving the economic observation artifact is still readable as "
            "designed and routing authority is unchanged; (N3) a fresh process regenerates "
            "economic_facts.json via the fact-layer generator (artifacts still "
            "generatable) and re-reads it; (N4) a fresh-process check proving "
            "malformed/incomplete/contradictory economic facts fail closed "
            "(never authoritative cheap/free, never enter known ordering) while "
            "baseline facts and routing authority stay unchanged."
        ),
        "scenarios": {},
    }
    try:
        # ---------- N1: Risk: LOW 全生命周期 ----------
        # FIX-001 起：真实 economic facts 下经济过滤后只剩 hy4-preview 一个
        # 可信候选 → 两候选 gate（capability+qualification+trustworthy
        # economics 全部过滤后 >= 2）不满足 → WorkBuddy 保持 CodeBuddy Auto。
        n1_dir = EVIDENCE_ROOT / "N1-low"
        n1 = _run_scenario(
            n1_dir,
            _task(
                N1_TASK_ID,
                "LOW",
                "验证经济 fail-closed 语义收紧后 framework 生命周期正常"
                "（FIX-001：真实 facts 只有 1 个可信候选 → WorkBuddy stage 保持 CodeBuddy Auto，无 --model）。",
            ),
            # Hermes stage：EXECUTOR-QUALIFICATION-FIX 起 LOW 真实 facts 不再路由
            # qwen3（aux-only 排除）→ configured deepseek 保留 → 精确授权走 A0。
            extra_env={
                cg.ENV_AUTH: f"{N1_TASK_ID}|hermes|deepseek-v4-flash|deepseek",
            },
        )
        out1 = n1["out"]
        run1 = _read_json(out1 / "run.json") or {}
        wb1 = _read_json(out1 / "workbuddy_result.json") or {}
        cx1 = _read_json(out1 / "codex_result.json") or {}
        args1 = _read_codebuddy_marker(n1["marker_codebuddy"])
        record1 = {
            "exit_code": n1["exit_code"],
            "run_status": run1.get("status"),
            "workbuddy_verdict": wb1.get("verdict"),
            "codex_verdict": cx1.get("verdict"),
            "report_exists": (out1 / "REPORT.md").exists(),
            "manifest_exists": (out1 / "context_manifest.json").exists(),
            "codebuddy_argv": args1,
            "invocation_stays_auto": args1 == EXPECTED_AUTO_ARGS,
        }
        scenario_record["scenarios"]["N1-low"] = record1
        ok1 = (
            n1["exit_code"] == 0
            and run1.get("status") == "SUCCESS"
            and wb1.get("verdict") == "PASS"
            and cx1.get("verdict") == "APPROVE"
            and (out1 / "REPORT.md").exists()
            and (out1 / "context_manifest.json").exists()
            and args1 == EXPECTED_AUTO_ARGS
            and "--model" not in (args1 or "")
            and "--effort" not in (args1 or "")
        )
        print(f"[N1] LOW lifecycle + CodeBuddy Auto -> {'PASS' if ok1 else 'FAIL'} (argv={args1!r})")
        if not ok1:
            failures += 1

        # ---------- N2: fresh-process artifact + authority check ----------
        n2 = subprocess.run(
            [sys.executable, str(ARTIFACT_CHECK)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        record2 = {
            "exit_code": n2.returncode,
            "stdout_tail": (n2.stdout or "")[-1500:],
            "stderr_tail": (n2.stderr or "")[-1500:],
        }
        scenario_record["scenarios"]["N2-artifact-authority-fresh-process"] = record2
        ok2 = n2.returncode == 0
        print(f"[N2] fresh-process artifact+authority -> {'PASS' if ok2 else 'FAIL'}")
        if not ok2:
            failures += 1

        # ---------- N3: fresh-process artifact regeneration ----------
        regen = subprocess.run(
            [sys.executable, str(GENERATOR)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        regen_ok = regen.returncode == 0 and ARTIFACT.exists()
        reread_ok = False
        reread_note = ""
        if regen_ok:
            try:
                doc = json.loads(ARTIFACT.read_text(encoding="utf-8"))
                stored = facts_from_dict(doc)
                reread_ok = set(stored) == set(WORKBUDDY_CANDIDATE_IDS) and len(stored) == 15
                ref = None
                for mid, fact in stored.items():
                    ref = datetime.fromisoformat(fact.observed_at)
                    break
                hy3 = stored["hy3"]
                hy4 = stored["hy4-preview"]
                reread_ok = reread_ok and is_authoritative_cheap(hy3, ref)
                reread_ok = reread_ok and is_authoritative_cheap(hy4, ref)
                reread_ok = reread_ok and doc["facts"]["hy3"]["freshness"] == "FRESH"
                reread_ok = reread_ok and doc["facts"]["hy4-preview"]["freshness"] == "FRESH"
                if not reread_ok:
                    reread_note = "facts/authoritative-cheap/freshness mismatch after regeneration"
            except (OSError, ValueError) as exc:
                reread_note = f"regenerated artifact not parseable: {exc}"
        record3 = {
            "exit_code": regen.returncode,
            "generator_stdout_tail": (regen.stdout or "")[-800:],
            "artifact_exists": ARTIFACT.exists(),
            "reread_ok": reread_ok,
            "note": reread_note,
        }
        scenario_record["scenarios"]["N3-artifact-regeneration-fresh-process"] = record3
        ok3 = regen_ok and reread_ok
        print(f"[N3] fresh-process artifact regeneration+re-read -> {'PASS' if ok3 else 'FAIL'}")
        if not ok3:
            failures += 1

        # ---------- N4: fresh-process fail-closed check ----------
        n4 = subprocess.run(
            [sys.executable, str(FAILCLOSED_CHECK)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        record4 = {
            "exit_code": n4.returncode,
            "stdout_tail": (n4.stdout or "")[-1500:],
            "stderr_tail": (n4.stderr or "")[-1500:],
        }
        scenario_record["scenarios"]["N4-failclosed-fresh-process"] = record4
        ok4 = n4.returncode == 0
        print(f"[N4] fresh-process fail-closed -> {'PASS' if ok4 else 'FAIL'}")
        if not ok4:
            failures += 1
    finally:
        (EVIDENCE_ROOT / "scenario_record.json").write_text(
            json.dumps(scenario_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"fresh-runner A4-WB-ECONOMICS-FIX-001 N+1: failures={failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
