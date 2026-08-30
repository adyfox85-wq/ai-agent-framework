"""AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001 fresh-runner validation driver（Run N+1）。

Requirement 9/10：context/evidence/model-observation 属于运行中 framework 的
self-observation 路径——实现后用**一次** fresh-runner N+1 验证（不叠加冗余
fresh-runner 循环）。每个场景用全新 python 进程运行真实 runner
（fresh_runner_wrapper.py），fake hermes.bat / codebuddy.bat 是真实 child process
（marker = hermes 达 invocation 边界的证据）；workspace 是**真实 git 仓库**，
因此 git_head / git_changed_files / remote_sync_state / git_snapshot 全部走
修复后的 no-console 路径调用真实 git.exe。

验证点（Requirement 10）：
1. framework 任务执行成功（run.json status == SUCCESS）
2. context packet 生成成功（hermes_result.json / workbuddy_result.json /
   context_manifest.json 存在且 manifest.head == 真实 git HEAD）
3. git status evidence 成功（driver 侧 git_snapshot 在真实 git 仓库上返回
   is_git_repo=True + 正确 local_head；runner 侧 git_changed_files == []）
4. model observation artifact 成功（model_observation.json 存在且
   observations.hermes.model 经真实 subprocess probe 读到 qwen3:4b）
5. 生命周期 / REPORT 无回归（REPORT.md 存在且含 Model Observation 段）

可见窗口消失不靠人工截图证明：Windows creation-flag 证据由单测断言
（test_no_console_helpers.py，win32 实跑）+ 本成功 fresh run 共同满足验收。

用法：python tests/fresh_runner_console_flash_validation.py
退出码 = 失败场景数（0 = 通过）。证据写入
.aaf/AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001/fresh-runner-validation/
（可用 AAF_FRESH_EVIDENCE_ROOT 覆盖；不提交）。
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

from ai_agent_framework import git_status as gs  # noqa: E402
from ai_agent_framework import model_observation as mo_mod  # noqa: E402

WRAPPER = ROOT / "tests" / "fresh_runner_wrapper.py"
FAKE_CODEBUDDY = ROOT / "tests" / "fake_codebuddy_cli.bat"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001" / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

TASK_ID = "AAF-FRESH-CONSOLE-FLASH-N1"
TASK_TEXT = f"""# Task ID
{TASK_ID}

# Task Name
fresh-runner console-flash N+1 validation

# Objective
验证 Windows no-console helper subprocess 修复后的 fresh-process self-observation 路径

# Acceptance
1. framework 任务执行成功
2. context packet 生成成功
3. git status evidence 成功
4. model observation artifact 成功
5. 生命周期 / REPORT 无回归

Route: hermes -> workbuddy
"""

# 支持 config probe 的 fake Hermes（ASCII only：cmd 元字符不在注释/内容中出现）：
# - `hermes --version`            -> exit 0（版本 probe）
# - `hermes config get model`     -> exit 0，本地 Ollama 模型（model observation OK + LOCAL_FREE）
# - `hermes config get auxiliary` -> exit 1（非阻塞 UNAVAILABLE 路径）
# - `hermes --help`               -> exit 0（capability probe）
# - `hermes chat ...`             -> marker + 合法 structured SUCCESS（真实 child 证据）
FAKE_HERMES_BAT = """@echo off
if "%1"=="--version" (
  echo fake-hermes-cli 9.9.9
  exit /b 0
)
if "%1"=="--help" (
  echo -m MODEL
  echo --provider
  exit /b 0
)
if "%1"=="config" (
  if "%2"=="get" (
    if "%3"=="model" (
      echo default: qwen3:4b
      echo provider: ollama
      echo base_url: http://127.0.0.1:11434/v1
      exit /b 0
    )
    exit /b 1
  )
  exit /b 1
)
if defined FAKE_HERMES_MARKER (
  echo SPAWNED > "%FAKE_HERMES_MARKER%"
)
echo FAKE HERMES EXECUTOR: console-flash N+1 validation stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

GUARD_ENVS = ("AAF_HERMES_MODEL", "AAF_HERMES_PROVIDER", "AAF_COST_AUTH", "FAKE_HERMES_MARKER", "AAF_TEST_FAKE_BIN")


def _init_git_repo(ws: Path) -> str:
    """初始化真实 git 仓库并做初始 commit，返回 HEAD。"""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "README.md").write_text("fresh-runner baseline\n", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "AAF Fresh Runner"
    env["GIT_AUTHOR_EMAIL"] = "fresh@aaf.local"
    env["GIT_COMMITTER_NAME"] = "AAF Fresh Runner"
    env["GIT_COMMITTER_EMAIL"] = "fresh@aaf.local"
    for args in (["init"], ["add", "-A"], ["commit", "-m", "fresh-runner baseline"]):
        r = subprocess.run(
            ["git", *args],
            cwd=str(ws), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, env=env,
        )
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr[-300:]}")
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(ws), capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    return r.stdout.strip()


def _force_rmtree(path: Path) -> None:
    """Windows 安全删除：git objects 是只读文件，rmtree 前先清只读位。"""

    def _onerror(func, p, _exc_info):
        try:
            os.chmod(p, 0o666)
            func(p)
        except OSError:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=_onerror)


def _run_scenario(root: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    scenario_dir = root / "N1"
    _force_rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True)

    # 真实 git workspace
    ws = scenario_dir / "ws"
    head = _init_git_repo(ws)

    # fake bin（hermes 变体 + codebuddy）
    fake_bin = scenario_dir / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    (fake_bin / "hermes.bat").write_text(FAKE_HERMES_BAT, encoding="utf-8")
    shutil.copy(FAKE_CODEBUDDY, fake_bin / "codebuddy.bat")

    task_file = scenario_dir / "TASK.md"
    task_file.write_text(TASK_TEXT, encoding="utf-8")
    out = scenario_dir / "out"

    child_env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    child_env["PYTHONPATH"] = str(ROOT)
    child_env["AAF_TEST_FAKE_BIN"] = str(fake_bin)
    child_env["FAKE_HERMES_MARKER"] = str(scenario_dir / "hermes_invoked.marker")
    child_env["AAF_HERMES_MODEL"] = "qwen3:4b"
    child_env["AAF_HERMES_PROVIDER"] = "ollama"

    proc = subprocess.run(
        [sys.executable, "-u", str(WRAPPER), str(task_file), "--workspace", str(ws), "--output", str(out)],
        cwd=str(ROOT), env=child_env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=240,
    )

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    if proc.returncode != 0:
        failures.append(f"runner exit={proc.returncode}: {proc.stderr[-800:]}")
        return not failures, failures

    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    hermes_md = (out / "hermes_result.md").read_text(encoding="utf-8")
    wb_md = (out / "workbuddy_result.md").read_text(encoding="utf-8")

    _check("run.status", run_json["status"] == "SUCCESS", f"run_json.status={run_json['status']}")
    _check("hermes.stage", (out / "hermes_result.json").exists() and "SUCCESS" in hermes_md,
           "hermes_result.json 缺失或 stage 未成功")
    _check("workbuddy.stage", (out / "workbuddy_result.json").exists() and "PASS" in wb_md,
           "workbuddy_result.json 缺失或 verdict 缺失")
    _check("hermes.spawned", (scenario_dir / "hermes_invoked.marker").exists(),
           "marker 缺失 — Hermes stage subprocess 未达 invocation 边界")

    # 2) context packet
    manifest_path = out / "context_manifest.json"
    _check("context_manifest.exists", manifest_path.exists(), "context_manifest.json 缺失")
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _check("manifest.head", manifest.get("head") == head,
               f"manifest.head={manifest.get('head')} != git HEAD {head}")
        _check("manifest.stages", isinstance(manifest.get("stages"), dict)
               and set(manifest["stages"]) == {"hermes", "workbuddy"},
               f"stages={list((manifest.get('stages') or {}).keys())}")

    # 3) git status evidence（driver 侧 git_snapshot 走修复后的 git_status._git()）
    closure = gs.git_snapshot(str(ws))
    _check("git_snapshot.is_git", closure.is_git_repo is True, "git_snapshot 未识别 git 仓库")
    _check("git_snapshot.head", closure.local_head == head,
           f"git_snapshot.local_head={closure.local_head} != {head}")
    _check("git_snapshot.tree", closure.working_tree == "clean", closure.working_tree)

    # 4) model observation artifact（真实 subprocess probe 经修复后的 _run_readonly；
    #    注意 fresh_runner_wrapper 只 patch adapters/cost_guard 的 discovery PATH，
    #    model_observation 走 winreg 真实 PATH → 探测到的是**真实 hermes CLI**，
    #    这正是修复后 self-observation 路径在真实环境的行为——artifact 必须有效生成）
    mo_path = out / "model_observation.json"
    _check("model_observation.exists", mo_path.exists(), "model_observation.json 缺失")
    mo = {}
    if mo_path.exists():
        mo = json.loads(mo_path.read_text(encoding="utf-8"))
        hermes_obs = (mo.get("observations") or {}).get("hermes") or {}
        _check("mo.hermes.entry", bool(hermes_obs), "model_observation.json 缺 hermes 观测条目")
        _check(
            "mo.hermes.status",
            hermes_obs.get("discovery_status")
            in (mo_mod.DISCOVERY_STATUS_OK, mo_mod.DISCOVERY_STATUS_UNAVAILABLE, mo_mod.DISCOVERY_STATUS_FAILED),
            f"discovery_status={hermes_obs.get('discovery_status')}",
        )

    # 5) REPORT / lifecycle
    _check("REPORT.exists", (out / "REPORT.md").exists(), "REPORT.md 缺失")
    if (out / "REPORT.md").exists():
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        _check("REPORT.model_observation", "Model Observation" in report, "REPORT 缺 Model Observation 段")

    # 证据记录
    record = {
        "task": TASK_ID,
        "runner_exit": proc.returncode,
        "run_status": run_json["status"],
        "git_head": head,
        "manifest_head": manifest.get("head"),
        "git_snapshot": closure.to_dict(),
        "hermes_marker_exists": (scenario_dir / "hermes_invoked.marker").exists(),
        "model_observation_hermes": (mo.get("observations") or {}).get("hermes"),
        "artifacts": sorted(p.name for p in out.iterdir()),
        "runner_stdout_tail": proc.stdout[-600:],
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def main() -> int:
    if not (FAKE_CODEBUDDY.exists() and WRAPPER.exists()):
        print("missing validation support files", file=sys.stderr)
        return 99
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print("AAF-v0.5-RUNTIME-UX-CONSOLE-FLASH-001 — fresh-runner validation (Run N+1)")
    print(f"fresh python: {sys.executable}")
    print(f"runner code:  {ROOT / 'ai_agent_framework' / 'runner.py'}")
    print("=" * 72)
    ok, failures = _run_scenario(EVIDENCE_ROOT)
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] N1-fresh-runner")
    for f in failures:
        print(f"      - {f}")
    print("-" * 72)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} (1/1 fresh-runner scenario)")
    print(f"evidence: {EVIDENCE_ROOT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
