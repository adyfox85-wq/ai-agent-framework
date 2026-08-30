"""AAF-v0.5-A0-PAID-GUARD-001-FIX-006：持久化 state_dir fail-open class 收口。

背景（Codex FIX-005 review BLOCKING）：``_claim_auth()`` 只拒绝
``state_dir is None``；``state_dir=""`` 经 ``Path("")`` 解析为相对当前工作目录
的 marker —— 不同 CWD 的独立进程各自都能成为 winner（ambiguous CWD-derived
persistence authority），且 marker 会落入调用者 CWD，而非明确、持久、共享的
授权状态目录。Runner 恒传 output_dir 只降低生产路径可达性，不能消除公共
``evaluate()`` / ``_claim_auth()`` 的契约违例。

FIX-006 修复（最小 scope，只关闭本 blocker）：
- 新增 ``_state_dir_validation_error()``：paid admission 的持久化 state_dir
  必须是**显式提供的、非空的、绝对路径**；None / 空串 / 纯空白 / ``Path("")``
  CWD fallback / ``"."`` / 相对路径 / 畸形或类型非法路径 / 任何 CWD 派生
  persistence authority → 返回 fail-closed 错误，**不创建任何 marker（含 CWD）**；
- ``_claim_auth()`` 在任何消费检查之前先校验 state_dir（失败 → False + 错误）；
- 合法绝对路径的 FIX-003/FIX-005 语义全部保持（exclusive-create 跨进程权威、
  并发恰一 winner、顺序 replay 拒绝）。

覆盖 TASK Verification（最低集）：
A. None / "" / 纯空白 / Path("") / "." / 相对路径 / 畸形（NUL、bytes、int）
   → BLOCKED，且 CWD 内零 marker、零相对目录创建
B. 多个独立进程、不同 CWD、invalid state_dir（"" 与 "./relative-state"）
   → 零 winner，任何 CWD 均无 marker / 相对目录
C. 有效绝对共享 state_dir + 并发进程 → 恰好一个 winner
D. 有效绝对共享 state_dir 顺序 replay → 首次 allowed、二次 blocked
E. 绝对路径是文件 / 路径中间组件是文件（unusable）/ marker 被目录占用
   → fail closed（含 consume 语义正确）
F. LOCAL_FREE 不受影响（state_dir=None / "" / "." 均 ALLOWED_FREE）
G. paid/unknown 无授权仍 blocked
H. FIX-002 endpoint / FREE 权威回归抽样保持绿色
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from ai_agent_framework import cost_guard as cg

ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).resolve().parent / "_auth_claim_worker.py"

SCOPE = "T1|hermes|deepseek-v4-flash|deepseek"

RELATIVE_STATE = "relative-state"
DOT_RELATIVE_STATE = "./relative-state"


def _paid_resolution(model="deepseek-v4-flash", provider="deepseek", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test paid resolution"],
    }


def _local_resolution(model="qwen3:4b", provider="ollama", base_url=None):
    return {
        "model": model,
        "provider": provider,
        "base_url": base_url,
        "model_source": cg.MODEL_SOURCE_ENV,
        "notes": ["test local resolution"],
    }


def _worker_env() -> dict:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        cg.ENV_MODEL: "deepseek-v4-flash",
        cg.ENV_PROVIDER: "deepseek",
        cg.ENV_AUTH: SCOPE,
    }


def _spawn_worker(state_dir_arg: str, cwd: Path, task_id: str = "T1"):
    """独立 python 进程在指定 CWD 内执行一次准入 claim（真实 resolve + env）。

    state_dir_arg：worker 的第一个 argv（真实值；"NONE" → None）。
    退出码：0 = ALLOWED_AUTHORIZED_PAID；3 = BLOCKED_COST_APPROVAL。
    """
    return subprocess.run(
        [sys.executable, "-u", str(WORKER), state_dir_arg, task_id],
        cwd=str(cwd),
        env=_worker_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


# ---------------------------------------------------------------------------
# A. 单次 evaluate：全部 invalid / ambiguous state_dir → BLOCKED 且零写入
# ---------------------------------------------------------------------------


def test_a_empty_state_dir_blocked_no_cwd_marker(monkeypatch, tmp_path):
    """state_dir="" → BLOCKED，且 CWD 内不创建任何 marker（FIX-005 阻塞点）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)  # 受控 CWD —— 旧实现会在此创建 marker
    rec = cg.evaluate("T1", "hermes", state_dir="")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("state_dir" in n and "absolute" in n.lower() for n in rec["notes"])
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists(), (
        "no CWD authorization marker may be created"
    )
    assert list(tmp_path.iterdir()) == [], f"CWD must stay untouched: {list(tmp_path.iterdir())}"


def test_a_whitespace_state_dir_blocked_no_cwd_marker(monkeypatch, tmp_path):
    """state_dir='   '（纯空白）→ BLOCKED，且 CWD 内不创建任何 marker/目录。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)
    rec = cg.evaluate("T1", "hermes", state_dir="   ")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("state_dir" in n and "absolute" in n.lower() for n in rec["notes"])
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()
    assert list(tmp_path.iterdir()) == []


def test_a_dot_state_dir_blocked_no_cwd_marker(monkeypatch, tmp_path):
    """state_dir='.' → CWD 本身 → 拒绝；不创建 marker。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)
    rec = cg.evaluate("T1", "hermes", state_dir=".")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()
    assert list(tmp_path.iterdir()) == []


def test_a_path_dot_state_dir_blocked(monkeypatch, tmp_path):
    """state_dir=Path('.') → 相对 → 拒绝。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)
    rec = cg.evaluate("T1", "hermes", state_dir=Path("."))
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()


def test_a_empty_path_state_dir_blocked_no_cwd_marker(monkeypatch, tmp_path):
    """state_dir=Path('') → CWD fallback → 拒绝；CWD 无 marker。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)
    rec = cg.evaluate("T1", "hermes", state_dir=Path(""))
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert not (tmp_path / cg.CONSUMPTION_FILENAME).exists()
    assert list(tmp_path.iterdir()) == []


def test_a_relative_state_dir_blocked_no_dir_created(monkeypatch, tmp_path):
    """相对路径（'./relative-state' / 'relative-state'）→ BLOCKED，且不创建目录。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    monkeypatch.chdir(tmp_path)
    for sd in (DOT_RELATIVE_STATE, RELATIVE_STATE):
        rec = cg.evaluate("T1", "hermes", state_dir=sd)
        assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL, sd
        assert rec["authorization_consumed"] is False, sd
        assert not (tmp_path / RELATIVE_STATE).exists(), (
            f"no relative state dir may be created for {sd!r}"
        )
    assert list(tmp_path.iterdir()) == []


def test_a_unsupported_state_dir_types_blocked(monkeypatch):
    """bytes / int / 其他非 str 类型 → BLOCKED（不抛异常，fail closed 而非崩溃）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    for sd in (b"C:\\state", 123, ["C:\\state"], {"p": "C:\\state"}):
        rec = cg.evaluate("T1", "hermes", state_dir=sd)
        assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL, repr(sd)
        assert rec["authorization_consumed"] is False, repr(sd)
        assert any("state_dir" in n for n in rec["notes"]), repr(sd)


def test_a_nul_byte_state_dir_blocked(monkeypatch):
    """含 NUL 的畸形路径 → BLOCKED（Path/mkdir 的 ValueError 不得逃逸 evaluate）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    rec = cg.evaluate("T1", "hermes", state_dir="C:\\bad\x00path")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("NUL" in n for n in rec["notes"])


def test_a_claim_function_level_all_invalid_fail_closed(monkeypatch, tmp_path):
    """函数级：_claim_auth/_consume_auth 对全部 invalid 输入返回 False + 错误。"""
    monkeypatch.chdir(tmp_path)
    invalid = (None, "", "   ", ".", Path(""), DOT_RELATIVE_STATE, RELATIVE_STATE,
               b"C:\\state", 123, "C:\\bad\x00path")
    for sd in invalid:
        ok, err = cg._claim_auth(SCOPE, SCOPE, sd)
        assert ok is False, repr(sd)
        assert err, repr(sd)
        ok2, err2 = cg._consume_auth(SCOPE, SCOPE, sd)
        assert ok2 is False, repr(sd)
        assert err2, repr(sd)
    assert list(tmp_path.iterdir()) == []


def test_a_validator_direct_contract(tmp_path):
    """_state_dir_validation_error：合法绝对路径 → None；其余 → 错误文本。"""
    assert cg._state_dir_validation_error(str(tmp_path)) is None
    assert cg._state_dir_validation_error(tmp_path) is None  # Path 对象亦可
    assert cg._state_dir_validation_error(os.path.abspath(".")) is None
    for sd in (None, "", "   ", ".", Path(""), DOT_RELATIVE_STATE, RELATIVE_STATE,
               b"C:\\state", 123, "C:\\bad\x00path", "C:foo", "\\foo"):
        assert cg._state_dir_validation_error(sd) is not None, repr(sd)


# ---------------------------------------------------------------------------
# B. 多个独立进程 + 不同 CWD + invalid state → 零 winner、零写入
# ---------------------------------------------------------------------------


def test_b_multiple_processes_different_cwds_invalid_state_zero_winners(tmp_path):
    """6 个独立进程、各自不同 CWD、invalid state_dir（"" / "./relative-state"）
    → 零 winner；任何 CWD 都不产生 marker 或相对目录（旧实现各自可 winner）。"""
    cwds = []
    for i in range(6):
        d = tmp_path / f"cwd{i}"
        d.mkdir()
        cwds.append(d)
    state_args = ["", "", "./relative-state", "./relative-state", ".", "   "]
    results = [_spawn_worker(sa, cwd) for sa, cwd in zip(state_args, cwds)]

    winners = [r for r in results if r.returncode == 0]
    losers = [r for r in results if r.returncode == 3]
    assert winners == [], f"invalid state_dir must yield zero winners: {results}"
    assert len(losers) == 6, f"all must be blocked: {results}"
    for r in losers:
        assert '"decision": "BLOCKED_COST_APPROVAL"' in r.stdout, r
        assert '"authorization_consumed": false' in r.stdout, r
    for d in cwds:
        assert not (d / cg.CONSUMPTION_FILENAME).exists(), f"marker in {d}"
        assert not (d / RELATIVE_STATE).exists(), f"relative dir created in {d}"
        assert list(d.iterdir()) == [], f"worker CWD must stay untouched: {d}"


# ---------------------------------------------------------------------------
# C. 有效绝对共享 state_dir + 并发进程 → 恰好一个 winner
# ---------------------------------------------------------------------------


def test_c_shared_absolute_state_dir_concurrent_exactly_one_winner(tmp_path):
    """6 个独立进程 + 同一绝对共享 state_dir → 恰 1 个 ALLOWED，其余 BLOCKED
    （FIX-003 filesystem exclusive-create 跨进程权威保持）。"""
    shared = tmp_path / "shared"
    shared.mkdir()
    procs = [_spawn_worker(str(shared), tmp_path) for _ in range(6)]
    winners = [r for r in procs if r.returncode == 0]
    losers = [r for r in procs if r.returncode == 3]
    assert len(winners) == 1, f"exactly one winner expected: {procs}"
    assert len(losers) == 5, f"five blocked expected: {procs}"
    marker = shared / cg.CONSUMPTION_FILENAME
    assert marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["consumed_auth_fingerprint"] == cg._auth_fingerprint(SCOPE)
    assert "consumed_auth" not in payload


# ---------------------------------------------------------------------------
# D. 有效绝对共享 state_dir 顺序 replay → 首次 allowed、二次 blocked
# ---------------------------------------------------------------------------


def test_d_sequential_replay_first_allowed_second_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    r1 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r1["decision"] == cg.DECISION_ALLOWED_AUTHORIZED_PAID
    assert r1["authorization_consumed"] is True
    r2 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r2["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r2["authorization_consumed"] is True
    cg._CONSUMED_AUTHS.clear()  # fresh 进程等价（仅剩磁盘 marker）
    r3 = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert r3["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert r3["authorization_consumed"] is True


# ---------------------------------------------------------------------------
# E. 绝对路径不可用（文件 / 中间组件是文件 / marker 被目录占用）→ fail closed
# ---------------------------------------------------------------------------


def test_e_absolute_state_dir_is_file_blocked(monkeypatch, tmp_path):
    """绝对路径本身是文件 → BLOCKED（mkdir FileExistsError）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    state_dir = tmp_path / "afile"
    state_dir.write_text("x")
    rec = cg.evaluate("T1", "hermes", state_dir=state_dir)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("persist" in n for n in rec["notes"])


def test_e_absolute_state_dir_under_file_blocked(monkeypatch, tmp_path):
    """绝对路径的中间组件是文件（unusable）→ BLOCKED（NotADirectoryError→OSError）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    afile = tmp_path / "afile"
    afile.write_text("x")
    state_dir = afile / "sub"
    rec = cg.evaluate("T1", "hermes", state_dir=state_dir)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("persist" in n for n in rec["notes"])


def test_e_marker_path_occupied_by_directory_fails_closed(monkeypatch, tmp_path):
    """绝对 state_dir 可用但 marker 路径被目录占用 → BLOCKED（状态不确定→fail closed）。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    (tmp_path / cg.CONSUMPTION_FILENAME).mkdir()
    rec = cg.evaluate("T1", "hermes", state_dir=tmp_path)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is True  # 已占用 → 视为已消费


def test_e_invalid_state_dir_never_consumes_runner_level(tmp_path, monkeypatch):
    """runner 集成：matched paid + state_dir 相对 → guard BLOCKED → Hermes 零 spawn。"""
    from ai_agent_framework import runner as runner_mod

    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        return {"hermes": "implemented", "workbuddy": "**Result: PASS**\nverified"}[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, "T-EXEC|hermes|deepseek-v4-flash|deepseek")

    task_text = """# Task ID
T-EXEC

# Task Name
执行链测试

# Objective
实现功能并验收

# Acceptance
1. 通过
"""
    task_file = tmp_path / "TASK.md"
    task_file.write_text(task_text, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(tmp_path / "ws")
    # runner 被喂相对 output_dir（CWD 派生 authority）→ paid admission 必须 BLOCKED
    report_path = runner_mod.run(task_file, ws, Path("out-relative"))
    report = report_path.read_text(encoding="utf-8")
    assert calls == []  # Hermes subprocess 未被创建
    assert "## Current Status\nWAITING" in report
    guard = json.loads((Path("out-relative") / "cost_guard.json").read_text(encoding="utf-8"))
    assert guard["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert guard["authorization_consumed"] is False
    assert not (Path("out-relative") / cg.CONSUMPTION_FILENAME).exists(), (
        "relative state_dir must not create a marker"
    )


# ---------------------------------------------------------------------------
# F. LOCAL_FREE 不受影响（state_dir 无效也 ALLOWED_FREE）
# ---------------------------------------------------------------------------


def test_f_local_free_unaffected_by_invalid_state_dir(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _local_resolution())
    for sd in (None, "", "   ", ".", "./relative-state"):
        rec = cg.evaluate("T1", "hermes", state_dir=sd)
        assert rec["decision"] == cg.DECISION_ALLOWED_FREE, repr(sd)
        assert rec["cost_class"] == cg.COST_LOCAL_FREE, repr(sd)
        assert rec["required_scope"] is None, repr(sd)


def test_f_local_base_url_endpoint_local_free(monkeypatch):
    monkeypatch.setattr(
        cg, "resolve_effective_hermes",
        lambda: _paid_resolution(base_url="http://127.0.0.1:11434/v1"),
    )
    rec = cg.evaluate("T1", "hermes", state_dir="")
    assert rec["decision"] == cg.DECISION_ALLOWED_FREE


# ---------------------------------------------------------------------------
# G. paid/unknown 无授权仍 blocked
# ---------------------------------------------------------------------------


def test_g_paid_without_authorization_blocked(monkeypatch):
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    rec = cg.evaluate("T1", "hermes", state_dir=None)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_present"] is False
    assert rec["required_scope"] == SCOPE


# ---------------------------------------------------------------------------
# H. FIX-002/FIX-003/FIX-005 回归抽样保持绿色
# ---------------------------------------------------------------------------


def test_h_fake_local_endpoint_regression_samples():
    """FIX-002 hostname/IP 语义抽样：伪装本地/非 loopback → PAID_OR_UNKNOWN。"""
    for url in (
        "https://localhost.evil.example/v1",
        "http://0.0.0.0:11434/v1",
        "https://8.8.8.8/v1",
        "http://localhost.localdomain/v1",
        "http://127.0.0.1.example.com/v1",
        "http:///v1",
        "http://localhost:99999/v1",
        "ftp://localhost/v1",
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_PAID_OR_UNKNOWN, url


def test_h_exact_local_endpoint_regression_samples():
    """exact localhost / loopback IP → LOCAL_FREE（FIX-002 语义保持）。"""
    for url in (
        "http://localhost:11434/v1",
        "http://127.0.0.2:11434/v1",
        "http://[::1]:11434/v1",
    ):
        cls, _ = cg.classify_cost("m", "p", url)
        assert cls == cg.COST_LOCAL_FREE, url


def test_h_free_env_still_ignored(monkeypatch):
    """AAF_COST_FREE_MODELS 仍非权威：声明付费模型为 free → 无授权仍 BLOCKED。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_FREE_MODELS, "deepseek-v4-flash@deepseek")
    rec = cg.evaluate("T1", "hermes", state_dir=None)
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["cost_class"] == cg.COST_PAID_OR_UNKNOWN
    assert any("IGNORED" in n for n in rec["notes"])


def test_h_state_dir_none_still_blocked(monkeypatch):
    """FIX-005 语义保持：state_dir=None → BLOCKED + REQUIRED note。"""
    monkeypatch.setattr(cg, "resolve_effective_hermes", lambda: _paid_resolution())
    monkeypatch.setenv(cg.ENV_AUTH, SCOPE)
    rec = cg.evaluate("T1", "hermes")
    assert rec["decision"] == cg.DECISION_BLOCKED_COST_APPROVAL
    assert rec["authorization_consumed"] is False
    assert any("state_dir" in n and "REQUIRED" in n for n in rec["notes"])
