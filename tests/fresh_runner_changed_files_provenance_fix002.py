"""AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-002 fresh-runner validation
driver（Run N+1，FIX-002 版）。

Requirement 13：本任务修改 Framework provenance/result-authority 逻辑——必须用
**一次** fresh-runner N+1 独立验证（不叠加冗余 N+1 循环，不复用父任务 N+1 作为
本任务证据）。每个场景用全新 python 进程运行真实 runner
（fresh_runner_wrapper.py），fake hermes.bat 是真实 child process，且**真的在
workspace 里创建一个 git commit**；workspace 是真实 git 仓库，因此
git_head / git_changed_files / remote_sync_state 全部走修复后的代码调用真实
git.exe。

N+1 必须独立证明（Requirement 13）：
1. 一个创建真实 tracked commit 的任务，同时存在一个无关的普通 untracked 文件：
   - 归一化 hermes_result.json 的 changed_files 含实际已提交的 task path
   - 无关 untracked 路径（arbitrary-file.txt）**缺席**
   - PRE_ALLOWED_UNTRACKED 常驻项缺席
   - commit == 实际 post-stage HEAD、commit_changed == true
   - raw agent 自报 changed_files=[] 不影响归一化（Framework Git 观察权威）
2. tracked working tree / remote state 如实上报（REPORT Remote Sync 段）
3. REPORT / lifecycle 生成健康（run.json SUCCESS、manifest.head 正确、
   REPORT.md 存在且含 SUCCESS / Remote Sync / Terminal Generation）

用法：python tests/fresh_runner_changed_files_provenance_fix002.py
退出码 = 失败场景数（0 = 通过）。证据写入
.aaf/AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-002/fresh-runner-validation/
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

WRAPPER = ROOT / "tests" / "fresh_runner_wrapper.py"
DEFAULT_EVIDENCE_ROOT = (
    ROOT / ".aaf" / "AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-002"
    / "fresh-runner-validation"
)
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()

TASK_ID = "AAF-CHANGED-FILES-N1-FIX002"
TASK_TEXT = f"""# Task ID
{TASK_ID}

# Task Name
fresh-runner changed-files provenance N+1 validation (FIX-002 untracked exclusion)

# Objective
验证归一化 changed_files：tracked commit 路径可见，任意普通 untracked 不污染

# Acceptance
1. framework 任务执行成功
2. 归一化 hermes_result.json 的 commit / commit_changed / changed_files 与 Git 事实一致
3. 无关普通 untracked 文件（arbitrary-file.txt）不进入 changed_files
4. REPORT / lifecycle 生成健康

Route: hermes
"""

# fake hermes.bat（ASCII only；cmd 元字符不在注释/内容中出现）：
# - `hermes --version` / `--help` / `config get model` -> probe 应答
# - `hermes chat ...` -> 在 %CD%（= workspace）修改 tracked 文件并**真实 commit**，
#   写 marker（真实 child 证据），然后输出 raw structured result
#   （changed_files 自报 [] —— 归一化必须由 Framework Git 观察覆盖）。
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
rem --- executor path: make a real tracked commit in the workspace (%CD%) ---
rem --- (only docs/n1_stage.md; arbitrary-file.txt stays untracked) ---
echo stage output v2 > docs\\n1_stage.md
git add docs/n1_stage.md
git commit -q -m "N1-FIX002 provenance fixture commit"
if defined FAKE_HERMES_MARKER (
  echo SPAWNED > "%FAKE_HERMES_MARKER%"
)
echo FAKE HERMES EXECUTOR: changed-files N+1 FIX-002 validation stub (no real inference)
echo.
echo AAF_STRUCTURED_RESULT_BEGIN
echo {"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}
echo AAF_STRUCTURED_RESULT_END
exit /b 0
"""

GUARD_ENVS = ("AAF_HERMES_MODEL", "AAF_HERMES_PROVIDER", "AAF_COST_AUTH",
              "FAKE_HERMES_MARKER", "AAF_TEST_FAKE_BIN")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "AAF Fresh Runner",
    "GIT_AUTHOR_EMAIL": "fresh@aaf.local",
    "GIT_COMMITTER_NAME": "AAF Fresh Runner",
    "GIT_COMMITTER_EMAIL": "fresh@aaf.local",
}

# 无关普通 untracked 文件名（非 PRE_ALLOWED_UNTRACKED）——污染回归场景
ARBITRARY_UNTRACKED = "arbitrary-file.txt"


def _git(ws: Path, *args, env=None, check: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(ws), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr[-300:]}")
    return r.stdout.strip()


def _init_git_repo(ws: Path) -> str:
    """初始化真实 git 仓库 + 初始 commit（含 tracked 的 docs/n1_stage.md），
    返回 baseline HEAD。"""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "README.md").write_text("fresh-runner baseline\n", encoding="utf-8")
    d = ws / "docs"
    d.mkdir()
    (d / "n1_stage.md").write_text("stage output v1\n", encoding="utf-8")
    env = {**os.environ, **GIT_IDENTITY}
    _git(ws, "init", "-q", env=env)
    _git(ws, "config", "user.email", "t@t", env=env)
    _git(ws, "config", "user.name", "t", env=env)
    _git(ws, "add", "-A", env=env)
    _git(ws, "commit", "-q", "-m", "fresh-runner baseline", env=env)
    return _git(ws, "rev-parse", "HEAD", env=env)


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
    baseline = _init_git_repo(ws)
    # 无关普通 untracked 文件：stage 前已存在、stage 后仍 untracked（污染场景）
    (ws / ARBITRARY_UNTRACKED).write_text("unrelated noise\n", encoding="utf-8")
    # PRE_ALLOWED_UNTRACKED 常驻项：stage 前后一直存在且从未被提交
    for rel in (".aaf/registry.json", "AAF_TASK004_PROCESS_CHECK.txt",
                "scripts/start_bridge_hidden.vbs"):
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("resident artifact\n", encoding="utf-8")

    fake_bin = scenario_dir / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    (fake_bin / "hermes.bat").write_text(FAKE_HERMES_BAT, encoding="utf-8")

    task_file = scenario_dir / "TASK.md"
    task_file.write_text(TASK_TEXT, encoding="utf-8")
    out = scenario_dir / "out"

    child_env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    child_env.update(GIT_IDENTITY)
    child_env["PYTHONPATH"] = str(ROOT)
    child_env["AAF_TEST_FAKE_BIN"] = str(fake_bin)
    child_env["FAKE_HERMES_MARKER"] = str(scenario_dir / "hermes_invoked.marker")
    child_env["AAF_HERMES_MODEL"] = "qwen3:4b"
    child_env["AAF_HERMES_PROVIDER"] = "ollama"

    proc = subprocess.run(
        [sys.executable, "-u", str(WRAPPER), str(task_file),
         "--workspace", str(ws), "--output", str(out)],
        cwd=str(ROOT), env=child_env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    if proc.returncode != 0:
        failures.append(f"runner exit={proc.returncode}: {proc.stderr[-800:]}")
        return not failures, failures

    # --- 1) lifecycle / run 健康 ---
    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    _check("run.status", run_json["status"] == "SUCCESS",
           f"run_json.status={run_json['status']}")

    # --- 2) 归一化 hermes_result.json 与 Git 事实一致 ---
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    post_head = _git(ws, "rev-parse", "HEAD")
    _check("commit.eq.head_after", stage["commit"] == post_head,
           f"stage.commit={stage['commit']} != HEAD {post_head}")
    _check("commit.moved", post_head != baseline,
           "stage 未创建新 commit（HEAD 未变）")
    _check("commit_changed.true", stage["commit_changed"] is True,
           f"commit_changed={stage['commit_changed']}")
    changed = stage.get("changed_files") or []
    _check("changed_files.has_committed_path", "M docs/n1_stage.md" in changed,
           f"changed_files={changed}（tracked committed path 必须可见）")
    _check("changed_files.no_arbitrary_untracked",
           not any(ARBITRARY_UNTRACKED in f for f in changed),
           f"普通 untracked 污染 changed_files={changed}")
    _check("changed_files.no_pre_allowed",
           not any("AAF_TASK004" in f or "start_bridge_hidden" in f
                   or ".aaf" in f or "??" in f for f in changed),
           f"PRE_ALLOWED_UNTRACKED 污染 changed_files={changed}")
    # raw agent 自报 changed_files=[]，归一化仍为 Git 观察事实
    _check("framework_authority_over_self_report", bool(changed),
           "归一化 changed_files 为空（Framework 未覆盖 agent 自报）")

    # --- 3) tracked working tree / remote state 如实上报 ---
    porcelain = _git(ws, "status", "--porcelain", "-uall")
    tracked_dirty = [l for l in porcelain.splitlines()
                     if l.strip() and not l.strip().startswith("??")]
    _check("worktree.clean", not tracked_dirty,
           f"stage commit 后 tracked worktree 应 CLEAN，实际: {porcelain!r}")
    _check("arbitrary.untracked.still_present", ARBITRARY_UNTRACKED in porcelain,
           "arbitrary-file.txt 应在 stage 后仍是 untracked（场景前提）")
    _check("hermes.spawned", (scenario_dir / "hermes_invoked.marker").exists(),
           "marker 缺失 — Hermes stage subprocess 未达 invocation 边界")

    report = (out / "REPORT.md").read_text(encoding="utf-8")
    _check("report.status", "## Current Status\nSUCCESS" in report,
           "REPORT 未标记 SUCCESS")
    _check("report.remote_sync", "## Remote Sync" in report,
           "REPORT 缺 Remote Sync 段")
    # Remote Sync 门（§5.1）只忽略 PRE_ALLOWED_UNTRACKED：场景中存在无关普通
    # untracked（arbitrary-file.txt）→ tracked tree 如实上报 DIRTY 且列出该噪音
    # 文件（诚实性检查；该门语义非本任务范围，changed_files 的排除才是）。
    _check("report.remote_sync.tree_dirty_honest",
           "Tracked Working Tree: DIRTY" in report
           and ARBITRARY_UNTRACKED in report,
           "REPORT tracked tree 未如实上报 DIRTY + 噪音 untracked 路径")
    _check("report.remote_sync.commit_unknown",
           "Commit Sync: UNKNOWN" in report,
           "REPORT commit_sync 未如实上报 UNKNOWN（无 upstream）")
    _check("report.terminal_generation", "## Terminal Generation" in report,
           "REPORT 缺 Terminal Generation 段")

    manifest = json.loads((out / "context_manifest.json").read_text(encoding="utf-8"))
    _check("manifest.head", manifest.get("head") == baseline,
           f"manifest.head={manifest.get('head')} != start HEAD {baseline}")

    # 证据记录
    record = {
        "task": TASK_ID,
        "runner_exit": proc.returncode,
        "run_status": run_json["status"],
        "baseline_head": baseline,
        "post_stage_head": post_head,
        "stage_commit": stage.get("commit"),
        "stage_commit_changed": stage.get("commit_changed"),
        "stage_changed_files": changed,
        "raw_agent_changed_files_self_report": [],
        "arbitrary_untracked_path": ARBITRARY_UNTRACKED,
        "worktree_porcelain": _git(ws, "status", "--porcelain"),
        "hermes_marker_exists": (scenario_dir / "hermes_invoked.marker").exists(),
        "artifacts": sorted(p.name for p in out.iterdir()),
        "runner_stdout_tail": proc.stdout[-600:],
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def main() -> int:
    if not WRAPPER.exists():
        print("missing validation support files", file=sys.stderr)
        return 99
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print("AAF-v0.5-A1-CLOSURE-PROTOCOL-CORRECTION-001-FIX-002 — fresh-runner "
          "changed-files provenance validation (Run N+1)")
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
