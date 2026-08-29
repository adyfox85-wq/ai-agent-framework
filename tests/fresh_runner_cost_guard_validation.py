"""AAF-v0.5-A0 fresh-runner validation driver（Run N+1，TASK: AAF-v0.5-A0-PAID-GUARD-001 + FIX-002）。

每个场景用**全新 python 进程**运行真实 runner（fresh_runner_wrapper.py），
fake hermes.bat / codebuddy.bat 是真实 child process（argv marker 为调用证据）：

  S1  paid/unknown 无授权            -> WAITING + BLOCKED_COST_APPROVAL + hermes 未 spawn（marker 缺失）
  S2  local/free（ollama）           -> SUCCESS + ALLOWED_FREE + hermes 到达 invocation 边界（marker 存在，
                                        args 含 -m qwen3:4b --provider ollama）
  S3  paid + 精确 task/stage/model 授权 -> SUCCESS + ALLOWED_AUTHORIZED_PAID + marker 存在
  S4  paid + 其他 Task 的授权        -> WAITING + BLOCKED + marker 缺失（授权不泄漏）
  S5  paid + 其他 model 的授权       -> WAITING + BLOCKED + marker 缺失
  S6  无 env 覆盖 + config probe 失败  -> WAITING + BLOCKED + cost_class=COST_UNKNOWN + marker 缺失（fail closed）

FIX-002 新增（Codex REQUEST_CHANGE 对抗场景）：
  S7  伪装本地 URL（config probe 返回 base_url=https://localhost.evil.example/v1）
                                      -> WAITING + BLOCKED + cost_class=PAID_OR_UNKNOWN + marker 缺失
                                      （hostname/IP 语义，非 substring）
  S8  AAF_COST_FREE_MODELS 声明付费模型 -> WAITING + BLOCKED + marker 缺失 + notes 记录"IGNORED"
                                      （env 元数据不是权威 FREE 来源）
  S9  同一授权值 replay（消费记录已存在）-> WAITING + BLOCKED + authorization_consumed=true + marker 缺失
                                      （一次性：准入即消费；跨进程 replay 拒绝）

用法：python tests/fresh_runner_cost_guard_validation.py
退出码 = 失败场景数（0 = 全部通过）。运行时证据写入
.aaf/<TASK-ID>/fresh-runner-validation/（不提交）；可用环境变量
AAF_FRESH_EVIDENCE_ROOT 覆盖证据根目录。
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
FAKE_HERMES = ROOT / "tests" / "fake_hermes_cli.bat"
FAKE_HERMES_EVIL_LOCAL = ROOT / "tests" / "fake_hermes_cli_evil_local.bat"
FAKE_CODEBUDDY = ROOT / "tests" / "fake_codebuddy_cli.bat"
DEFAULT_EVIDENCE_ROOT = ROOT / ".aaf" / "AAF-v0.5-A0-PAID-GUARD-001" / "fresh-runner-validation"
EVIDENCE_ROOT = Path(
    os.environ.get("AAF_FRESH_EVIDENCE_ROOT", "").strip() or DEFAULT_EVIDENCE_ROOT
).resolve()  # resolve：fake bin / marker 路径必须是绝对路径（子进程 cwd=ws，相对路径会解析失败）

TASK_ID = "AAF-FRESH-GUARD-001"
TASK_TEXT = f"""# Task ID
{TASK_ID}

# Task Name
fresh-runner cost guard validation

# Objective
验证 v0.5 A0 Paid Guard 的 fresh-process 运行时行为

# Acceptance
1. 通过
"""

GUARD_ENVS = (
    "AAF_HERMES_MODEL",
    "AAF_HERMES_PROVIDER",
    "AAF_COST_AUTH",
    "AAF_COST_FREE_MODELS",
    "FAKE_HERMES_MARKER",
    "AAF_TEST_FAKE_BIN",
)

SCENARIOS = [
    {
        "id": "S1-paid-no-auth",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "marker": False,
            "result_md": "COST_APPROVAL_REQUIRED",
        },
        "env": {"AAF_HERMES_MODEL": "deepseek-v4-flash", "AAF_HERMES_PROVIDER": "deepseek"},
    },
    {
        "id": "S2-local-free-allowed",
        "expect": {
            "status": "SUCCESS",
            "decision": "ALLOWED_FREE",
            "marker": True,
        },
        "env": {"AAF_HERMES_MODEL": "qwen3:4b", "AAF_HERMES_PROVIDER": "ollama"},
    },
    {
        "id": "S3-paid-exact-auth-allowed",
        "expect": {
            "status": "SUCCESS",
            "decision": "ALLOWED_AUTHORIZED_PAID",
            "marker": True,
        },
        "env": {
            "AAF_HERMES_MODEL": "deepseek-v4-flash",
            "AAF_HERMES_PROVIDER": "deepseek",
            "AAF_COST_AUTH": f"{TASK_ID}|hermes|deepseek-v4-flash|deepseek",
        },
    },
    {
        "id": "S4-auth-other-task-blocked",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "marker": False,
        },
        "env": {
            "AAF_HERMES_MODEL": "deepseek-v4-flash",
            "AAF_HERMES_PROVIDER": "deepseek",
            "AAF_COST_AUTH": "SOME-OTHER-TASK|hermes|deepseek-v4-flash|deepseek",
        },
    },
    {
        "id": "S5-auth-other-model-blocked",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "marker": False,
        },
        "env": {
            "AAF_HERMES_MODEL": "deepseek-v4-flash",
            "AAF_HERMES_PROVIDER": "deepseek",
            "AAF_COST_AUTH": f"{TASK_ID}|hermes|some-other-model|deepseek",
        },
    },
    {
        "id": "S6-unresolved-fail-closed",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "cost_class": "COST_UNKNOWN",
            "marker": False,
        },
        "env": {},  # 无 env 覆盖 → config probe（fake hermes 对 config 返回 exit 1）→ 无法解析
    },
    {
        "id": "S7-fake-local-url-blocked",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "cost_class": "PAID_OR_UNKNOWN",
            "marker": False,
            "cost_metadata_contains": "localhost.evil.example",
        },
        # 无 env 覆盖 → config probe 返回 paid model + 伪装本地 base_url
        # （旧 substring 实现会把 https://localhost.evil.example/v1 判为 LOCAL_FREE）
        "env": {},
        "fake_hermes": FAKE_HERMES_EVIL_LOCAL,
    },
    {
        "id": "S8-free-env-ignored-blocked",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "cost_class": "PAID_OR_UNKNOWN",
            "marker": False,
            "notes_contain": "IGNORED",
        },
        # AAF_COST_FREE_MODELS 声明远程付费模型 → 仍然 BLOCKED（不是权威 FREE 来源）
        "env": {
            "AAF_HERMES_MODEL": "deepseek-v4-flash",
            "AAF_HERMES_PROVIDER": "deepseek",
            "AAF_COST_FREE_MODELS": "deepseek-v4-flash@deepseek,deepseek-v4-flash",
        },
    },
    {
        "id": "S9-auth-replay-blocked",
        "expect": {
            "status": "WAITING",
            "decision": "BLOCKED_COST_APPROVAL",
            "cost_class": "PAID_OR_UNKNOWN",
            "marker": False,
            "authorization_consumed": True,
        },
        # pre_consume：驱动先用生产消费函数写消费记录（模拟 admission #1 已发生），
        # 再用同一授权值运行真实 runner → 一次性语义拒绝 replay（跨进程实证）。
        "pre_consume": True,
        "env": {
            "AAF_HERMES_MODEL": "deepseek-v4-flash",
            "AAF_HERMES_PROVIDER": "deepseek",
            "AAF_COST_AUTH": f"{TASK_ID}|hermes|deepseek-v4-flash|deepseek",
        },
    },
]


def _spawn_fresh_runner(scenario: dict, scenario_dir: Path) -> subprocess.CompletedProcess:
    fake_bin = scenario_dir / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy(scenario.get("fake_hermes", FAKE_HERMES), fake_bin / "hermes.bat")
    shutil.copy(FAKE_CODEBUDDY, fake_bin / "codebuddy.bat")
    env = scenario["env"]

    task_file = scenario_dir / "TASK.md"
    task_file.write_text(TASK_TEXT, encoding="utf-8")
    ws = scenario_dir / "ws"
    ws.mkdir(exist_ok=True)
    out = scenario_dir / "out"

    child_env = {k: v for k, v in os.environ.items() if k not in GUARD_ENVS}
    child_env["PYTHONPATH"] = str(ROOT)
    child_env["AAF_TEST_FAKE_BIN"] = str(fake_bin)
    child_env["FAKE_HERMES_MARKER"] = str(scenario_dir / "hermes_invoked.marker")
    for k, v in env.items():
        child_env[k] = v

    return subprocess.run(
        [sys.executable, "-u", str(WRAPPER), str(task_file), "--workspace", str(ws), "--output", str(out)],
        cwd=str(ROOT),
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def _run_scenario(scenario: dict, root: Path) -> tuple[bool, list[str]]:
    sid = scenario["id"]
    expect = scenario["expect"]
    env = scenario["env"]
    scenario_dir = root / sid
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True)

    # S9 replay：先用生产消费函数写入消费记录（admission #1 已发生的等价状态），
    # 再运行真实 runner —— 一次性语义必须在跨进程下拒绝同一授权值。
    if scenario.get("pre_consume"):
        auth = env["AAF_COST_AUTH"]
        scope = auth
        out_dir = scenario_dir / "out"
        ok, err = cg._consume_auth(auth, scope, out_dir)
        if not ok:
            return False, [f"pre_consume failed: {err}"]

    proc = _spawn_fresh_runner(scenario, scenario_dir)
    out_dir = scenario_dir / "out"
    failures: list[str] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    if proc.returncode != 0:
        failures.append(f"runner exit={proc.returncode}: {proc.stderr[-500:]}")
        return not failures, failures

    run_json = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
    guard = json.loads((out_dir / "cost_guard.json").read_text(encoding="utf-8"))
    marker = scenario_dir / "hermes_invoked.marker"
    marker_text = marker.read_text(encoding="utf-8", errors="replace") if marker.exists() else None
    hermes_md = (out_dir / "hermes_result.md").read_text(encoding="utf-8")

    _check("run.status", run_json["status"] == expect["status"], f"{run_json['status']} != {expect['status']}")
    _check("guard.decision", guard["decision"] == expect["decision"], guard["decision"])
    if "cost_class" in expect:
        _check("guard.cost_class", guard["cost_class"] == expect["cost_class"], guard["cost_class"])
    if "cost_metadata_contains" in expect:
        meta = json.dumps(guard.get("cost_metadata") or {}, ensure_ascii=False)
        _check("guard.cost_metadata", expect["cost_metadata_contains"] in meta, meta[:300])
    if "notes_contain" in expect:
        notes = " | ".join(guard.get("notes") or [])
        _check("guard.notes", expect["notes_contain"] in notes, notes[:300])
    if "authorization_consumed" in expect:
        _check(
            "guard.authorization_consumed",
            guard.get("authorization_consumed") is expect["authorization_consumed"],
            f"authorization_consumed={guard.get('authorization_consumed')}",
        )
    if "marker" in expect:
        if expect["marker"]:
            _check("hermes.spawned", marker_text is not None, "marker missing — Hermes subprocess was not created")
        else:
            _check("hermes.not_spawned", marker_text is None, "marker exists — Hermes WAS spawned despite block")
    if "result_md" in expect:
        _check("result_md", expect["result_md"] in hermes_md, hermes_md[:200])

    # 场景记录（evidence 便于复查）
    record = {
        "scenario": sid,
        "env": scenario["env"],
        "expect": expect,
        "runner_exit": proc.returncode,
        "run_status": run_json["status"],
        "guard_decision": guard["decision"],
        "guard_cost_class": guard["cost_class"],
        "guard_required_scope": guard.get("required_scope"),
        "guard_authorization_present": guard.get("authorization_present"),
        "guard_authorization_matched": guard.get("authorization_matched"),
        "guard_authorization_consumed": guard.get("authorization_consumed"),
        "guard_cost_metadata": guard.get("cost_metadata"),
        "guard_notes": guard.get("notes"),
        "consumption_marker_exists": (out_dir / cg.CONSUMPTION_FILENAME).exists(),
        "hermes_marker_exists": marker_text is not None,
        "hermes_marker": marker_text,
        "hermes_result_head": hermes_md[:300],
    }
    (scenario_dir / "scenario_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not failures, failures


def main() -> int:
    if not (FAKE_HERMES.exists() and FAKE_CODEBUDDY.exists() and WRAPPER.exists()):
        print("missing validation support files", file=sys.stderr)
        return 99
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    failed = 0
    print("=" * 72)
    print("AAF-v0.5-A0 Paid Guard — fresh-runner validation (Run N+1)")
    print(f"fresh python: {sys.executable}")
    print(f"runner code:  {ROOT / 'ai_agent_framework' / 'runner.py'}")
    print("=" * 72)
    for scenario in SCENARIOS:
        ok, failures = _run_scenario(scenario, EVIDENCE_ROOT)
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {scenario['id']}")
        for f in failures:
            print(f"      - {f}")
        if not ok:
            failed += 1
    print("-" * 72)
    print(f"RESULT: {len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    print(f"evidence: {EVIDENCE_ROOT}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
