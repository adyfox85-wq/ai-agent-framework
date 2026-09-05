"""AAF-v0.5-COST-STOP-LOSS-001 focused tests.

覆盖（Requirement 10 / 7 机器可读 reason / 8 429·empty 早停）：
- long model wait terminates boundedly（per-attempt 有界，不等到 3600s 级）
- repeated empty-output terminates early（配置高 max_attempts 时不烧剩余 attempts）
- 429/quota 不无谓烧 full stage budget（reset 不可达 → 1 次 attempt 即 fail closed）
- 合法长跑 tool/test 工作不被 no-progress guard 误杀（guard 只作用于已完成失败之间）
- dirty workspace 在 stop-loss 后保留 / RESUME/recovery 仍可行（runner 集成）
- 机器可读 terminal reason 正确（stop_loss.json / workbuddy_attempts.json）

Hermetic：全部 fake Popen / fake subprocess.run / fake run_agent；零真实 Agent CLI。
"""
import json
import math
import os
import subprocess
import time
from pathlib import Path

import pytest

import ai_agent_framework.adapters as adapters_mod
import ai_agent_framework.cost_guard as cg
import ai_agent_framework.model_registry as mr
import ai_agent_framework.runner as runner_mod
import ai_agent_framework.stop_loss as sl_mod
import ai_agent_framework.workbuddy_retry as wb_retry_mod
from ai_agent_framework import fallback_paid_gate as fpg
from ai_agent_framework import fallback_runtime as fr
from ai_agent_framework.risk_contract import RISK_LOW

_REAL_RESOLVE = cg.resolve_effective_hermes  # conftest hermetic patch 前捕获

# ---------------------------------------------------------------------------
# A. stop_loss 模块（词汇表 / timeout 解析 / evidence / 分类）
# ---------------------------------------------------------------------------


def test_vocabulary_covers_all_required_reasons():
    for reason in (
        "ATTEMPT_TIMEOUT", "RETRIES_EXHAUSTED", "NO_PROGRESS",
        "RATE_LIMIT", "QUOTA", "PROVIDER_FAILURE", "TOOL_OR_TEST_STILL_ACTIVE",
    ):
        assert reason in sl_mod.TERMINAL_STOP_REASONS
    assert sl_mod.STOP_LOSS_ARTIFACT == "stop_loss.json"


def test_resolve_hermes_timeout_env_override_and_risk_tiers(monkeypatch):
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    monkeypatch.delenv(sl_mod.ENV_CODEX_ATTEMPT_TIMEOUT, raising=False)
    # env override（operator 逃生口）优先于分级默认
    monkeypatch.setenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, "123")
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="HIGH") == 123.0
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT)
    # Risk 分级默认（evidence-based：对应档位已观测成功 stage max 均低于该值）
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="CRITICAL") == 2400.0
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="HIGH") == 2400.0
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="MEDIUM") == 1500.0
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="LOW") == 1200.0
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="low") == 1200.0
    # 无 Risk / 未知 Risk（validation fail-closed 防御）→ 保守默认
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class=None) == 1800.0
    assert sl_mod.resolve_agent_attempt_timeout("hermes", risk_class="BOGUS") == 1800.0
    # codex：env override / 默认（review 无长 tool 任务）
    monkeypatch.setenv(sl_mod.ENV_CODEX_ATTEMPT_TIMEOUT, "77")
    assert sl_mod.resolve_agent_attempt_timeout("codex") == 77.0
    monkeypatch.delenv(sl_mod.ENV_CODEX_ATTEMPT_TIMEOUT)
    assert sl_mod.resolve_agent_attempt_timeout("codex") == 600.0
    # workbuddy 不消费该解析（retry 层 AAF_WORKBUDDY_* 自管）——返回默认供统一接口
    assert sl_mod.resolve_agent_attempt_timeout("workbuddy") == sl_mod.DEFAULT_HERMES_ATTEMPT_TIMEOUT


def test_detect_rate_limit_evidence_kinds():
    kind, detail = sl_mod.detect_rate_limit_evidence(
        "HTTP 429 Too Many Requests\nrate limit reached"
    )
    assert kind == "RATE_LIMIT" and detail
    kind, _ = sl_mod.detect_rate_limit_evidence("we hit a rate limit, reset in 30s")
    assert kind == "RATE_LIMIT"
    kind, _ = sl_mod.detect_rate_limit_evidence(
        "error: quota exceeded for this model (quota exhausted)"
    )
    assert kind == "QUOTA"
    kind, _ = sl_mod.detect_rate_limit_evidence("try again later")
    assert kind == "RATE_LIMIT"
    # 无 evidence → 不声称
    kind, _ = sl_mod.detect_rate_limit_evidence("all tests passed, 12 assertions ok")
    assert kind is None
    kind, _ = sl_mod.detect_rate_limit_evidence(None)
    assert kind is None


def test_parse_rate_limit_reset():
    assert sl_mod.parse_rate_limit_reset("Try again in 45 seconds") == 45.0
    assert sl_mod.parse_rate_limit_reset("rate limit reached; retry after 2 minutes") == 120.0
    assert sl_mod.parse_rate_limit_reset("the rate limit resets in 5 minutes") == 300.0
    assert sl_mod.parse_rate_limit_reset("back off 30s") == 30.0
    # 单位不明/无文案 → None（调用方尽早 stop，不猜）
    assert sl_mod.parse_rate_limit_reset("429 too many requests, retry after a while") is None
    assert sl_mod.parse_rate_limit_reset("all good") is None
    assert sl_mod.parse_rate_limit_reset(None) is None


def test_timeout_tool_activity_markers_heuristic():
    assert sl_mod.timeout_shows_tool_activity("running tests for feature x...") is True
    assert sl_mod.timeout_shows_tool_activity("pytest session started") is True
    assert sl_mod.timeout_shows_tool_activity("building module 3 of 5") is True
    assert sl_mod.timeout_shows_tool_activity("still thinking about the answer") is False
    assert sl_mod.timeout_shows_tool_activity(None) is False


def test_classify_terminal_reason_basic(monkeypatch):
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    # subprocess.TimeoutExpired（Hermes/Codex 单 attempt 有界终止）→ ATTEMPT_TIMEOUT
    exc = subprocess.TimeoutExpired("hermes", 2400.0)
    reason, detail = sl_mod.classify_terminal_reason(
        agent="hermes", exc=exc, wb_telemetry=None, result_text=None
    )
    assert reason == "ATTEMPT_TIMEOUT" and detail
    # WorkBuddy telemetry 自报 reason（rate-limit early stop）
    reason, _ = sl_mod.classify_terminal_reason(
        agent="workbuddy", exc=None,
        wb_telemetry={"outcome": "RETRIES_EXHAUSTED", "terminal_reason": "RATE_LIMIT"},
        result_text=None,
    )
    assert reason == "RATE_LIMIT"
    # WorkBuddy outcome 无 vocab reason（PERMANENT/CLEANUP）→ None（不写 stop_loss.json）
    reason, _ = sl_mod.classify_terminal_reason(
        agent="workbuddy", exc=None,
        wb_telemetry={"outcome": "PERMANENT_FAILURE", "terminal_reason": None},
        result_text=None,
    )
    assert reason is None
    # 普通 RuntimeError 无 stop-loss evidence → None
    reason, _ = sl_mod.classify_terminal_reason(
        agent="hermes", exc=RuntimeError("hermes failed (exit=1)\nSTDERR: boom"),
        wb_telemetry=None, result_text=None,
    )
    assert reason is None
    # RuntimeError 文本含 429 evidence → RATE_LIMIT（Hermes CLI 限频退出）
    reason, _ = sl_mod.classify_terminal_reason(
        agent="hermes",
        exc=RuntimeError("hermes failed (exit=1)\nSTDERR:\nHTTP 429 rate limit hit"),
        wb_telemetry=None, result_text=None,
    )
    assert reason == "RATE_LIMIT"


# ---------------------------------------------------------------------------
# B. WorkBuddy retry 层（self-contained fake Popen harness，语义同
#    tests/test_workbuddy_retry.py：behavior 逐次消费、taskkill 树杀、registry）
# ---------------------------------------------------------------------------


class _FakeProc:
    """Scripted Popen fake（behaviors 逐次消费，每次 communicate 一个条目）。

    ('output', stdout, stderr) → exit=0 输出
    ('exit', code, stdout, stderr) → 指定退出码
    ('timeout',) → 抛 subprocess.TimeoutExpired
    ('sleep_timeout', seconds) → sleep 后抛 TimeoutExpired（长模型等待模拟）
    ('sleep_output', seconds, stdout, stderr) → sleep 后正常输出（合法长 tool 模拟）
    kill 后 communicate = drain 语义（返回 drained_*，returncode=-9）。
    """

    def __init__(self, pid, behavior_iter, drained_out="", drained_err=""):
        self.pid = pid
        self.behaviors = behavior_iter
        self.drained_out = drained_out
        self.drained_err = drained_err
        self.returncode = None
        self.killed = False

    def communicate(self, input=None, timeout=None):
        if self.killed:
            self.returncode = -9
            return self.drained_out, self.drained_err
        try:
            entry = next(self.behaviors)
        except StopIteration:
            self.returncode = 0
            return "", ""
        kind, *rest = entry
        if kind == "output":
            self.returncode = 0
            return rest[0], rest[1]
        if kind == "exit":
            self.returncode = rest[0]
            return rest[1], rest[2]
        if kind == "sleep_output":
            t = min(float(rest[0]), timeout if timeout is not None else float(rest[0]))
            time.sleep(t)
            self.returncode = 0
            return rest[1], rest[2]
        if kind == "sleep_timeout":
            t = min(float(rest[0]), timeout if timeout is not None else float(rest[0]))
            time.sleep(t)
            raise subprocess.TimeoutExpired("fake", t)
        if kind == "timeout":
            raise subprocess.TimeoutExpired("fake", timeout)
        raise AssertionError(f"unknown behavior {kind!r}")

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def _install_fake_popen(monkeypatch, behaviors, drained_out="", drained_err="",
                        taskkill_result=True):
    import itertools
    spawns = []
    counter = itertools.count(1000)
    behavior_iter = iter(behaviors)

    def fake_popen(*args, **kwargs):
        assert wb_retry_mod.active_child_pids() == [], "concurrent child registered"
        proc = _FakeProc(next(counter), behavior_iter, drained_out, drained_err)
        spawns.append(proc)
        return proc

    def fake_taskkill(pid, timeout=None):
        if not taskkill_result:
            return False
        for p in spawns:
            if p.pid == pid:
                p.killed = True
                p.returncode = -9
        return True

    monkeypatch.setattr(wb_retry_mod, "_Popen", fake_popen)
    monkeypatch.setattr(wb_retry_mod, "_taskkill", fake_taskkill)
    return spawns


def _make_policy(max_attempts=2, timeout=60.0, backoff=0.0, budget=None, reserve=0.0):
    budget = budget if budget is not None else (max_attempts * timeout + (max_attempts - 1) * backoff)
    return wb_retry_mod.WorkBuddyRetryPolicy(
        max_attempts=max_attempts,
        per_attempt_timeout=timeout,
        backoff_seconds=backoff,
        overall_stage_budget=budget,
        cleanup_reserve=reserve,
    )


def _run_retry(monkeypatch, behaviors, policy=None, drained_out="", drained_err=""):
    """直接调用 retry 编排层（fake CLI）。返回 (output, telemetry, spawns)。"""
    spawns = _install_fake_popen(
        monkeypatch, behaviors, drained_out=drained_out, drained_err=drained_err
    )
    policy = policy or _make_policy()
    out, telemetry = wb_retry_mod.run_workbuddy_with_retry(
        ["codebuddy", "-p", "--output-format", "text", "-y"],
        {"CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS": "1"},
        "PROMPT",
        Path("."),
        policy,
    )
    assert wb_retry_mod.active_child_pids() == []
    return out, telemetry, spawns


def _zero_cleanup_floor(monkeypatch):
    monkeypatch.setattr(wb_retry_mod, "MIN_SAFE_CLEANUP_RESERVE", 0.0)


def test_long_model_wait_terminates_boundedly(monkeypatch):
    """Requirement 10/2：单 attempt 超长模型等待必须**有界**终止（不等到 3600s 级）。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=1, timeout=0.3, backoff=0.0, budget=1.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(monkeypatch, [("sleep_timeout", 60.0)], policy=policy)
    telemetry = exc.value.telemetry
    assert telemetry["outcome"] == "RETRIES_EXHAUSTED"
    assert telemetry["attempt_count"] == 1
    assert telemetry["attempts"][0]["timed_out"] is True
    assert telemetry["terminal_reason"] == "ATTEMPT_TIMEOUT"
    # 墙钟有界：attempt timeout 0.3s，绝不睡到 60s（也不到 1s budget 级别）
    assert telemetry["stage_total_elapsed_seconds"] <= 1.0 + 0.2
    assert "terminal stop reason: ATTEMPT_TIMEOUT" in str(exc.value)


def test_repeated_empty_output_terminates_early(monkeypatch):
    """Requirement 8/10：配置高 max_attempts 时，连续 empty-output 提前终止（NO_PROGRESS）。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=5, timeout=60.0, backoff=0.0, budget=300.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(monkeypatch, [("output", "", ""), ("output", "", ""), ("output", "", "")],
                   policy=policy)
    telemetry = exc.value.telemetry
    assert telemetry["attempt_count"] == 3  # 第 4/5 次不再烧
    assert telemetry["terminal_reason"] == "NO_PROGRESS"
    assert "no-progress" in (telemetry["retry_suppressed_reason"] or "")
    assert telemetry["empty_occurred"] is True
    assert "terminal stop reason: NO_PROGRESS" in str(exc.value)


def test_two_empty_then_success_recovery_kept(monkeypatch):
    """既有恢复语义保留：empty,empty,success（实测恢复序列）不被阈值 2 误杀。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=3, timeout=60.0, backoff=0.0, budget=300.0)
    out, telemetry, _ = _run_retry(
        monkeypatch, [("output", "", ""), ("output", "", ""), ("output", "PASS ok", "")],
        policy=policy,
    )
    assert out == "PASS ok"
    assert telemetry["attempt_count"] == 3
    assert telemetry["outcome"] == "SUCCESS"
    assert telemetry["terminal_reason"] is None


def test_429_unreachable_reset_stops_early_no_budget_burn(monkeypatch):
    """Requirement 8/10：429 + reset 窗口远超剩余 budget → 1 次 attempt 即 fail closed。

    若按旧语义会再试 2 次并空等到 stage budget；新行为立即停止且墙钟极小。
    """
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=3, timeout=60.0, backoff=0.0, budget=300.0)
    stderr = "HTTP 429 Too Many Requests: rate limit reached, retry after 3600 seconds"
    start = time.monotonic()
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(monkeypatch, [("output", "", stderr)], policy=policy)
    elapsed = time.monotonic() - start
    telemetry = exc.value.telemetry
    assert telemetry["attempt_count"] == 1  # 没有无谓的后续 attempts
    assert telemetry["terminal_reason"] == "RATE_LIMIT"
    assert telemetry["rate_limit_occurred"] is True
    assert "rate limit" in (telemetry["retry_suppressed_reason"] or "")
    assert elapsed < 10.0  # 没有睡 3600s / 没有等到 300s budget
    assert telemetry["attempts"][0]["failure_class"] == "rate_limit"
    assert telemetry["attempts"][0]["rate_limit_reset_seconds"] == 3600.0


def test_quota_evidence_terminal_quota(monkeypatch):
    """quota 文案 → QUOTA terminal reason（不误报 RATE_LIMIT）。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=3, timeout=60.0, backoff=0.0, budget=300.0)
    stderr = "ERROR: daily quota exhausted, quota resets tomorrow"
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(monkeypatch, [("exit", 1, "", stderr)], policy=policy)
    telemetry = exc.value.telemetry
    assert telemetry["attempt_count"] == 1
    assert telemetry["terminal_reason"] == "QUOTA"
    assert telemetry["attempts"][0]["failure_class"] == "quota"


def test_rate_limit_reset_reachable_waits_then_succeeds(monkeypatch):
    """reset 窗口可解析且在剩余 budget 内 → 有界等到 reset 再试（1 次）→ 成功。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=2, timeout=5.0, backoff=0.0, budget=30.0)
    stderr = "429 rate limit; retry after 1 second"
    out, telemetry, spawns = _run_retry(
        monkeypatch, [("output", "", stderr), ("output", "PASS ok", "")], policy=policy
    )
    assert out == "PASS ok"
    assert telemetry["outcome"] == "SUCCESS"
    assert telemetry["attempt_count"] == 2
    assert telemetry["terminal_reason"] is None
    assert len(spawns) == 2
    assert telemetry["stage_total_elapsed_seconds"] >= 0.85  # 真实有界等待发生


def test_no_progress_guard_never_kills_active_tool_work(monkeypatch):
    """Requirement 10/5：合法长跑 tool/test 不被 no-progress guard 误杀。

    行为：attempt 在跑（sleep 模拟长工具）期间 guard 绝不介入；完成后成功。
    """
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=2, timeout=5.0, backoff=0.0, budget=30.0)
    out, telemetry, spawns = _run_retry(
        monkeypatch, [("sleep_output", 0.4, "PASS after long tool run", "")], policy=policy
    )
    assert out == "PASS after long tool run"
    assert telemetry["attempt_count"] == 1
    assert telemetry["outcome"] == "SUCCESS"
    assert len(spawns) == 1
    assert telemetry["stage_total_elapsed_seconds"] >= 0.35
    # 混合失败（empty → timeout）不构成"连续相同/空" → 继续 retry 至成功
    out2, telemetry2, _ = _run_retry(
        monkeypatch,
        [("output", "", ""), ("timeout",), ("output", "PASS ok2", "")],
        policy=_make_policy(max_attempts=3, timeout=0.3, backoff=0.0, budget=30.0),
    )
    assert out2 == "PASS ok2"
    assert telemetry2["attempt_count"] == 3


def test_timeout_with_tool_markers_terminal_tool_still_active(monkeypatch):
    """TOOL_OR_TEST_STILL_ACTIVE：timeout 清理排出的 partial output 含明确 markers。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=2, timeout=0.2, backoff=0.0, budget=30.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(
            monkeypatch,
            [("sleep_timeout", 30.0), ("sleep_timeout", 30.0)],
            policy=policy,
            drained_out="running tests for feature x, 42 passed so far",
        )
    telemetry = exc.value.telemetry
    assert telemetry["attempt_count"] == 2
    assert telemetry["terminal_reason"] == "TOOL_OR_TEST_STILL_ACTIVE"
    assert telemetry["attempts"][0]["timeout_activity_markers"] is True


def test_timeout_without_markers_terminal_attempt_timeout(monkeypatch):
    """无 markers 的 timeout → ATTEMPT_TIMEOUT（不把无证据 timeout 猜成 tool 活动）。"""
    _zero_cleanup_floor(monkeypatch)
    policy = _make_policy(max_attempts=2, timeout=0.2, backoff=0.0, budget=30.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        _run_retry(
            monkeypatch,
            [("sleep_timeout", 30.0), ("sleep_timeout", 30.0)],
            policy=policy,
        )
    telemetry = exc.value.telemetry
    assert telemetry["attempt_count"] == 2
    assert telemetry["terminal_reason"] == "ATTEMPT_TIMEOUT"
    assert telemetry["attempts"][0]["timeout_activity_markers"] is False
    # 机器 artifact 可序列化 & 全部 attempt 带新字段
    json.dumps(telemetry)
    assert "terminal_reason" in telemetry
    assert "rate_limit_reset_seconds" in telemetry["attempts"][0]
    assert "timeout_activity_markers" in telemetry["attempts"][0]


# ---------------------------------------------------------------------------
# C. adapters.run_agent（Hermes/Codex timeout 解析 + TimeoutExpired 传递）
# ---------------------------------------------------------------------------


def _capture_subprocess_run(monkeypatch, captured):
    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout,
                 env, **kwargs):
        captured.update(timeout=timeout, args=args)

        class FakeProc:
            returncode = 0
            stdout = "OK output"
            stderr = ""

        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_run_agent_hermes_codex_timeout_resolution(tmp_path, monkeypatch):
    """Hermes/Codex per-attempt timeout：显式参数 > env override > 分级默认。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    monkeypatch.delenv(sl_mod.ENV_CODEX_ATTEMPT_TIMEOUT, raising=False)
    captured = {}
    _capture_subprocess_run(monkeypatch, captured)
    monkeypatch.setattr(adapters_mod, "_require", lambda cmd: f"C:/fake/{cmd}.exe")

    # 默认：Hermes（无 Risk 上下文=保守 1800s 档）/ Codex 600（evidence-based 有界值）
    adapters_mod.run_agent("hermes", "TASK", tmp_path)
    assert captured["timeout"] == sl_mod.DEFAULT_HERMES_TIMEOUT_NO_RISK
    adapters_mod.run_agent("codex", "TASK", tmp_path)
    assert captured["timeout"] == sl_mod.DEFAULT_CODEX_ATTEMPT_TIMEOUT

    # env override
    monkeypatch.setenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, "321")
    adapters_mod.run_agent("hermes", "TASK", tmp_path)
    assert captured["timeout"] == 321.0
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT)

    # 显式 timeout 参数仍优先（既有调用方语义）
    adapters_mod.run_agent("hermes", "TASK", tmp_path, timeout=4321)
    assert captured["timeout"] == 4321


def test_run_agent_hermes_timeout_expired_propagates_for_classification(tmp_path, monkeypatch):
    """Hermes 长模型等待超时 → subprocess.TimeoutExpired 原样上抛（runner 据此分类
    ATTEMPT_TIMEOUT；A5 fallback 分类语义不变——既不是新异常类型也不是 RuntimeError）。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)

    def slow_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("hermes", kwargs.get("timeout", 2400.0))

    monkeypatch.setattr(subprocess, "run", slow_run)
    monkeypatch.setattr(adapters_mod, "_require", lambda cmd: f"C:/fake/{cmd}.exe")
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        adapters_mod.run_agent("hermes", "TASK", tmp_path)
    # 机器可读 reason 分类路径（stop_loss.classify_terminal_reason）
    reason, _ = sl_mod.classify_terminal_reason(
        agent="hermes", exc=exc.value, wb_telemetry=None, result_text=None
    )
    assert reason == "ATTEMPT_TIMEOUT"


# ---------------------------------------------------------------------------
# D. runner 集成（stop_loss.json artifact / dirty workspace 保留 / RESUME）
# ---------------------------------------------------------------------------

_RUNNER_TASK_TMPL = """# Task ID
{task_id}

# Task Name
stop-loss runner test

# Risk
{risk}

# Objective
implement and verify stop-loss behaviour

# Route
{route}

# Acceptance
1. behaviour verified
"""


def _write_runner_task(tmp_path, task_id="T-SL-001", risk="HIGH",
                       route="hermes -> workbuddy -> codex"):
    task_file = tmp_path / "TASK.md"
    task_file.write_text(
        _RUNNER_TASK_TMPL.format(task_id=task_id, risk=risk, route=route),
        encoding="utf-8",
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    return task_file, ws, tmp_path / "out"


def test_runner_hermes_stop_loss_artifact_workspace_preserved_and_recovery(tmp_path, monkeypatch):
    """Requirement 3/10：Hermes ATTEMPT_TIMEOUT → fail closed（WAITING）+ stop_loss.json
    机器原因 + dirty workspace 与全部 artifacts 保留（RESUME/recovery 输入完整——
    manifest 引用无悬空；后续 recovery leg 在同一 workspace 上可成功收口，且 stop-loss
    run 产物原样保留为历史证据；不自动从零重启）。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    task_file, ws, out = _write_runner_task(tmp_path, risk="HIGH")
    calls = []
    seen_env = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        seen_env.append(os.environ.get(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT))
        if agent == "hermes":
            # 模拟：有真实进度（dirty file）后被有界 timeout 终止
            (ws / "dirty_work.py").write_text("WIP = True\n", encoding="utf-8")
            hermes_calls = [c for c in calls if c == "hermes"]
            if len(hermes_calls) == 1:
                raise subprocess.TimeoutExpired("hermes", 2400.0)
            return "implemented\nAAF_STRUCTURED_RESULT_BEGIN\n{\"status\": \"SUCCESS\"}\nAAF_STRUCTURED_RESULT_END"
        return {
            "hermes": "implemented",
            "workbuddy": "**Result: PASS**\nverified",
            "codex": "APPROVE",
        }[agent]

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)

    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    assert calls == ["hermes"]  # 链中断：后续节点不启动
    # Hermes stage 期间 timeout env overlay = HIGH 档 2400（且调用后被还原）
    assert seen_env == ["2400"]
    assert os.environ.get(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT) is None

    # 机器可读 stop reason
    sl = json.loads((out / "stop_loss.json").read_text(encoding="utf-8"))
    assert sl["terminal_reason"] == "ATTEMPT_TIMEOUT"
    assert sl["agent"] == "hermes"
    assert sl["task_id"] == "T-SL-001"
    # dirty workspace 保留（stop-loss 不清理任何已完成工作）
    assert (ws / "dirty_work.py").exists()
    assert (ws / "dirty_work.py").read_text(encoding="utf-8") == "WIP = True\n"
    hermes_md = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert hermes_md.startswith("FRAMEWORK_ERROR")
    # stage result json 引用 stop_loss
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage["stop_loss"]["terminal_reason"] == "ATTEMPT_TIMEOUT"
    assert stage["stop_loss"]["artifact_path"].endswith("stop_loss.json")

    # RESUME/recovery 输入完整：snapshot / route / prompt / result / manifest /
    # stop-loss 机器证据全部保留（链中断 = WB/Codex 合法未执行）——后续 recovery
    # 可基于同一 workspace 继续，不需从零重启。
    from ai_agent_framework.context_packet import read_manifest

    manifest = read_manifest(out)
    assert manifest["task"]["path"].endswith("TASK.snapshot.md")
    for required in (
        "TASK.snapshot.md", "route.json", "hermes_prompt.md",
        "hermes_result.md", "hermes_result.json", "context_manifest.json",
        "stop_loss.json",
    ):
        assert (out / required).exists(), required
    assert not (out / "workbuddy_result.md").exists()  # 链保护：未启动后续节点

    # Recovery leg（真实 AAF 恢复模式：保留 workspace + artifacts 的新执行）：
    # fake 修复后，在同一 workspace 上以新输出目录收口 → SUCCESS；dirty 工作保留。
    rec_task = tmp_path / "TASK-recovery.md"
    rec_task.write_text(
        _RUNNER_TASK_TMPL.format(task_id="T-SL-001-RESUME", risk="HIGH",
                                 route="hermes -> workbuddy -> codex"),
        encoding="utf-8",
    )
    out2 = tmp_path / "out-recovery"
    runner_mod.run(rec_task, ws, out2)
    assert "## Current Status\nSUCCESS" in (out2 / "REPORT.md").read_text(encoding="utf-8")
    assert (ws / "dirty_work.py").exists()
    # stop-loss run 的历史产物不被 recovery 改写（机器证据保留）
    sl_hist = json.loads((out / "stop_loss.json").read_text(encoding="utf-8"))
    assert sl_hist["terminal_reason"] == "ATTEMPT_TIMEOUT"


def test_runner_hermes_timeout_env_tier_follows_risk(tmp_path, monkeypatch):
    """Risk 分级 env overlay 正确注入 Hermes stage（且不泄漏到后续 stage）。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    expected = {"LOW": "1200", "MEDIUM": "1500", "HIGH": "2400"}
    for risk, want in expected.items():
        base = tmp_path / risk
        base.mkdir()
        task_file, ws, out = _write_runner_task(base, task_id=f"T-SL-TIER-{risk}", risk=risk)
        per_agent_env = {}

        def fake_run_agent(agent, prompt, workspace):
            per_agent_env[agent] = os.environ.get(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT)
            return {
                "hermes": "implemented",
                "workbuddy": "**Result: PASS**\nverified",
                "codex": "APPROVE",
            }[agent]

        monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
        report_path = runner_mod.run(task_file, ws, out)
        assert "## Current Status\nSUCCESS" in report_path.read_text(encoding="utf-8")
        assert per_agent_env.get("hermes") == want
        # workbuddy/codex stage 看不到 Hermes timeout overlay
        assert per_agent_env.get("workbuddy") is None
        assert per_agent_env.get("codex") is None
        # 成功 run 不产生 stop_loss.json
        assert not (out / "stop_loss.json").exists()
        # env overlay 调用后已还原
        assert os.environ.get(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT) is None


def test_runner_workbuddy_rate_limit_stop_loss_artifact(tmp_path, monkeypatch):
    """WorkBuddy RATE_LIMIT 早停 → runner 持久化 stop_loss.json 机器原因 + WAITING。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, raising=False)
    task_file, ws, out = _write_runner_task(
        tmp_path, task_id="T-SL-WBRL", risk="MEDIUM", route="workbuddy -> codex"
    )
    calls = []

    def fake_run_agent(agent, prompt, workspace):
        calls.append(agent)
        if agent == "workbuddy":
            telemetry = {
                "agent": "workbuddy",
                "outcome": "RETRIES_EXHAUSTED",
                "attempt_count": 1,
                "retried": False,
                "terminal_reason": "RATE_LIMIT",
                "rate_limit_occurred": True,
                "retry_suppressed_reason": "rate limit reset not reachable — early stop-loss",
                "attempts": [{"attempt_index": 1, "status": "FAILED",
                              "failure_class": "rate_limit",
                              "retry_reason": "429 rate limit"}],
                "last_failure": {"attempt_index": 1, "retry_reason": "429 rate limit"},
                "policy": {"max_attempts": 2},
                "timeout_occurred": False,
                "empty_occurred": False,
                "cleanup_failure_occurred": False,
            }
            adapters_mod._workbuddy_telemetry = telemetry
            raise wb_retry_mod.WorkBuddyRetriesExhausted(
                "WorkBuddy stage RETRIES_EXHAUSTED after 1 attempt(s) "
                "terminal stop reason: RATE_LIMIT",
                telemetry,
            )
        return "APPROVE"

    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    report_path = runner_mod.run(task_file, ws, out)
    report = report_path.read_text(encoding="utf-8")
    assert "## Current Status\nWAITING" in report
    assert calls == ["workbuddy"]
    sl = json.loads((out / "stop_loss.json").read_text(encoding="utf-8"))
    assert sl["terminal_reason"] == "RATE_LIMIT"
    assert sl["agent"] == "workbuddy"
    assert sl["attempt_count"] == 1
    artifact = json.loads((out / "workbuddy_attempts.json").read_text(encoding="utf-8"))
    assert artifact["terminal_reason"] == "RATE_LIMIT"
    # stage result json 机器引用
    stage = json.loads((out / "workbuddy_result.json").read_text(encoding="utf-8"))
    assert stage["stop_loss"]["terminal_reason"] == "RATE_LIMIT"


# ---------------------------------------------------------------------------
# E. Shared Hermes stage deadline（AAF-v0.5-COST-STOP-LOSS-001-FIX-001；Codex
#    REQUEST_CHANGE blocker 收口）—— stop_loss 纯函数 + adapters.run_agent 裁剪
#
# Requirement 1（单一权威 stage deadline）、2（original+fallback 共享同一绝对
# deadline）、3（fallback 前 remaining = deadline - now）、4/8（effective =
# min(per_attempt, remaining)）、5（耗尽/低于安全下限 → 不发起第二模型）。
# ---------------------------------------------------------------------------

class _FakeClock:
    """可注入单调时钟（monkeypatch sl_mod._monotonic）——runner 的 deadline 计算、
    剩余预算求值、adapters 裁剪全部经 stop_loss._monotonic() 取时；单点 patch
    即整链确定性（测试零真实等待）。"""

    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _install_fake_clock(monkeypatch, start=1000.0):
    clock = _FakeClock(start)
    monkeypatch.setattr(sl_mod, "_monotonic", clock)
    return clock


def test_shared_deadline_vocab_and_defaults():
    """FIX-001 词汇/默认：STAGE_BUDGET_EXHAUSTED ∈ 机器可读词汇表；stage budget
    默认 = 3600s（原 ~3600s 无进度问题边界），安全下限 = 60s。"""
    assert sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED == "STAGE_BUDGET_EXHAUSTED"
    assert sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED in sl_mod.TERMINAL_STOP_REASONS
    assert sl_mod.DEFAULT_HERMES_STAGE_BUDGET == 3600.0
    assert sl_mod.DEFAULT_HERMES_STAGE_MIN_REMAINING == 60.0
    for env in (sl_mod.ENV_HERMES_STAGE_BUDGET, sl_mod.ENV_HERMES_STAGE_DEADLINE,
                sl_mod.ENV_HERMES_STAGE_MIN_REMAINING):
        assert env.startswith("AAF_")


def test_resolve_hermes_stage_budget_override_and_defaults(monkeypatch):
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_BUDGET, raising=False)
    assert sl_mod.resolve_hermes_stage_budget() == sl_mod.DEFAULT_HERMES_STAGE_BUDGET
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_BUDGET, "1234")
    assert sl_mod.resolve_hermes_stage_budget() == 1234.0
    for bad in ("abc", "-5", "0"):
        monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_BUDGET, bad)
        assert sl_mod.resolve_hermes_stage_budget() == sl_mod.DEFAULT_HERMES_STAGE_BUDGET


def test_resolve_min_remaining_override_zero_allowed(monkeypatch):
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, raising=False)
    assert sl_mod.resolve_hermes_stage_min_remaining() == 60.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "7")
    assert sl_mod.resolve_hermes_stage_min_remaining() == 7.0
    # operator 可显式归零（禁用 60s 安全下限；remaining<=0/近零边界仍停——
    # FIX-002：0 只解除安全下限，不解除耗尽边界）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "0")
    assert sl_mod.resolve_hermes_stage_min_remaining() == 0.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "-3")
    assert sl_mod.resolve_hermes_stage_min_remaining() == 60.0


def test_shared_deadline_absolute_remaining_and_fallback_gate(monkeypatch):
    """Requirement 1/3/5：deadline 是绝对 wall-clock 值（不随 attempt 重置）；
    remaining = deadline - now 单调递减；耗尽/低于安全下限 → gate 拒绝并给出
    机器可读 reason。"""
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, raising=False)
    # 无 deadline env（非 Hermes stage / 直接调用方）→ 既有语义（不 gate）
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is True and state["remaining_seconds"] is None
    # 首次 invocation 前一次性设置绝对 deadline
    deadline = sl_mod.hermes_stage_deadline_value(budget_seconds=2400.0)
    assert deadline == 3400.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, f"{deadline:g}")
    assert sl_mod.hermes_stage_remaining_seconds() == 2400.0
    # original 消耗大部分预算——deadline 不 reset，remaining 单调下降
    clock.advance(2300)
    assert sl_mod.hermes_stage_remaining_seconds() == 100.0
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is True and state["remaining_seconds"] == 100.0
    # 低于安全下限（< 60s）→ 拒绝发起第二模型
    clock.advance(50)
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False
    assert state["remaining_seconds"] == 50.0
    assert state["minimum_required_seconds"] == 60.0
    assert "below the safe minimum" in state["suppressed_reason"]
    # env 调低下限至 0：remaining 50 ≥ 0 → 恢复 allowed（边界精确）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "0")
    assert sl_mod.hermes_fallback_allowed()["allowed"] is True
    # 真正耗尽（remaining < 0）即使 min=0 也拒绝
    clock.advance(60)
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False and state["remaining_seconds"] == -10.0
    # FIX-002：非法 deadline env（present but malformed）→ 0.0 fail-closed
    # （视为已到期：adapter spawn 前早停 + gate 拒绝，绝不回退到不 gate 的
    # None 放行态）；只有 env **absent** 才返回 None（非 Hermes stage 语义）。
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "not-a-number")
    assert sl_mod.hermes_stage_remaining_seconds() == 0.0
    assert sl_mod.hermes_fallback_allowed()["allowed"] is False
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_DEADLINE)
    assert sl_mod.hermes_stage_remaining_seconds() is None


def test_effective_attempt_timeout_min_remaining_formula(monkeypatch):
    """Requirement 8：effective = min(per_attempt, remaining)；无 deadline →
    per-attempt 原样。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, raising=False)
    assert sl_mod.effective_attempt_timeout(2400.0) == 2400.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "1100")  # remaining=100
    assert sl_mod.effective_attempt_timeout(2400.0) == 100.0
    assert sl_mod.effective_attempt_timeout(50.0) == 50.0  # per-attempt 更小仍优先
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "900")  # remaining=-100
    assert sl_mod.effective_attempt_timeout(2400.0) <= 0.0  # 耗尽 → ≤0（调用方早停）


# ---------------------------------------------------------------------------
# FIX-002 focused regressions（TASK: AAF-v0.5-COST-STOP-LOSS-001-FIX-002 ——
# Codex REQUEST_CHANGE blockers 1-3 收口：预算/截止有限性 · 无损 deadline
# 序列化 · remaining<=0 & fp 近零边界恒拒绝 fallback）
# ---------------------------------------------------------------------------


def test_fix002_budget_nonfinite_invalid_fail_safe_to_default(monkeypatch):
    """Blocker 1（Test A/B/C）：stage budget env = inf / -inf / NaN / <=0 /
    malformed / float 溢出（1e999→inf）→ resolve 一律 fail-safe 到有界默认，
    返回恒为有限正数——预算绝不可能产生无限 deadline/remaining（Requirement 1）。
    min-remaining resolver 对非有限值同样 fail-safe（inf/-inf/NaN → 默认 60s）。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_BUDGET, raising=False)
    for bad in ("inf", "-inf", "Infinity", "nan", "NaN", "0", "-5", "abc", "1e999"):
        monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_BUDGET, bad)
        resolved = sl_mod.resolve_hermes_stage_budget()
        assert resolved == sl_mod.DEFAULT_HERMES_STAGE_BUDGET
        assert math.isfinite(resolved) and resolved > 0
    # 合法有限正数不受影响（Test G 单元面）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_BUDGET, "3605.25")
    assert sl_mod.resolve_hermes_stage_budget() == 3605.25
    # min-remaining：非有限（inf/-inf/NaN）→ 默认 60s（负数/非法同）
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, raising=False)
    for bad in ("inf", "-inf", "nan", "-1", "abc"):
        monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, bad)
        assert sl_mod.resolve_hermes_stage_min_remaining() == 60.0


def test_fix002_deadline_value_guards_nonfinite_nonpositive_budget(monkeypatch):
    """Blocker 1 兜底：显式传入 hermes_stage_deadline_value 的非有限/非正
    budget 同样被拒（fail-safe 到默认）——deadline 恒为有限正数（绝无 inf/nan）。"""
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    for bad in (float("inf"), float("-inf"), float("nan"), 0.0, -1.0):
        deadline = sl_mod.hermes_stage_deadline_value(budget_seconds=bad)
        assert deadline == 1000.0 + sl_mod.DEFAULT_HERMES_STAGE_BUDGET
        assert math.isfinite(deadline) and deadline > 0
    # 合法有限正数照常
    assert sl_mod.hermes_stage_deadline_value(budget_seconds=3605.0) == 4605.0


def test_fix002_deadline_serialization_never_extends_budget(monkeypatch):
    """Blocker 2（Test D，Codex 独立复现数值）：monotonic=1000001 + budget=3605
    → 精确 deadline=1003606。默认 :g 只留 6 位有效数字 → '1.00361e+06' → 解析后
    有效预算 3609s（+4s 越界）；repr round-trip 使 float(repr(x)) == x 恒成立 →
    parsed deadline == 精确值，有效预算 == 配置 3605s（parsed <= exact，不放大）。"""
    clock = _install_fake_clock(monkeypatch, start=1000001.0)
    budget = 3605.0
    exact_deadline = sl_mod.hermes_stage_deadline_value(budget_seconds=budget)
    assert exact_deadline == 1003606.0
    # 复现 :g 放大缺陷（同 Codex 独立实测：配置 3605s → 解析后 3609s）
    legacy_serialized = f"{exact_deadline:g}"
    assert legacy_serialized == "1.00361e+06"
    assert float(legacy_serialized) - clock.now == 3609.0  # 越界 +4s
    # 无损序列化：解析值 == 精确值（误差 0）
    serialized = sl_mod.format_stage_deadline(exact_deadline)
    assert serialized == "1003606.0"
    assert float(serialized) == exact_deadline
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, serialized)
    assert sl_mod.hermes_stage_remaining_seconds() == budget  # 有效预算未被放大
    # 分数 budget 同样无损 round-trip（绝不向前扩展）
    frac = sl_mod.hermes_stage_deadline_value(budget_seconds=3605.25)
    assert float(sl_mod.format_stage_deadline(frac)) == frac
    assert float(sl_mod.format_stage_deadline(frac)) <= clock.now + 3605.25


def test_fix002_remaining_zero_blocks_fallback_even_min_remaining_zero(monkeypatch):
    """Blocker 3（Test E，Codex 独立复现）：AAF_HERMES_STAGE_MIN_REMAINING=0
    只解除 60s 安全下限——remaining == 0（边界精确命中）仍恒拒绝 fallback，
    机器 reason 走 exhausted（zero boundary）分支，不再出现 allowed=true。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "1000")  # remaining == 0.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "0")
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False
    assert state["remaining_seconds"] == 0.0
    assert state["minimum_required_seconds"] == 0.0
    assert "zero boundary" in state["suppressed_reason"]
    # 负 remaining（min=0）同样拒绝（FIX-001 语义保持；exhausted 分支）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "999.999")  # remaining=-0.001
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False
    assert state["remaining_seconds"] < 0.0
    assert "zero boundary" in state["suppressed_reason"]


def test_fix002_near_zero_fp_remainder_denied_strictly_positive_allowed(monkeypatch):
    """Blocker 3（Test F）：deadline 边界处的浮点近零正残差（1e-9 级）在 min=0
    下同样视为耗尽（< STAGE_BUDGET_ZERO_EPSILON = 1µs）——绝不因 fp 噪声放行
    注定无法收敛的 invocation；真实可用剩余（>= 零边界）才放行。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "0")
    # +1e-9 正残差 → 拒绝（exhausted：at/below zero boundary）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "1000.000000001")
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False
    assert 0.0 < state["remaining_seconds"] < sl_mod.STAGE_BUDGET_ZERO_EPSILON
    assert "zero boundary" in state["suppressed_reason"]
    # -1e-9 负残差 → 拒绝
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "999.999999999")
    assert sl_mod.hermes_fallback_allowed()["allowed"] is False
    # 真实可用剩余（0.5s，min=0）→ 放行（只有耗尽/低于下限才拒绝）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "1000.5")
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is True and state["remaining_seconds"] == 0.5
    # 低于 60s 默认下限但高于零边界 → 拒绝（below safe minimum 分支）
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "60")
    state = sl_mod.hermes_fallback_allowed()
    assert state["allowed"] is False
    assert "below the safe minimum" in state["suppressed_reason"]


def test_fix002_exhausted_gate_feeds_machine_stop_loss_record(monkeypatch):
    """Blocker 4（记录面）：耗尽/无效 deadline 态的 gate 结果（allowed=False +
    machine reason）直接驱动 build_stop_loss_record → terminal_reason =
    STAGE_BUDGET_EXHAUSTED（机器可读词汇表成员），绝无 None 回退/静默放行。
    覆盖两种耗尽形态：remaining == 0（min=0）与 malformed deadline env（→0.0）。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    exc = subprocess.TimeoutExpired("hermes", 2400.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, "0")
    for deadline_env in ("1000", "not-a-number"):  # remaining==0 / malformed→0.0
        monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, deadline_env)
        state = sl_mod.hermes_fallback_allowed()
        assert state["allowed"] is False
        record = sl_mod.build_stop_loss_record(
            agent="hermes", task_id="T-SL-FIX002-4", exc=exc,
            wb_telemetry=None, result_text=None, elapsed_seconds=2400.89,
            stage_budget_exhausted=state,
        )
        assert record is not None
        assert record["terminal_reason"] == sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED
        assert sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED in sl_mod.TERMINAL_STOP_REASONS
        assert record["agent"] == "hermes"
        assert "remaining budget" in record["detail"]
    # 无 deadline env（非 Hermes stage 上下文）→ gate 不裁剪（既有语义不变）
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, raising=False)
    assert sl_mod.hermes_fallback_allowed()["allowed"] is True


def test_run_agent_clips_to_remaining_stage_budget(tmp_path, monkeypatch):
    """Requirement 4/8：Hermes invocation（original 或 fallback 都走同一
    run_agent）的 subprocess timeout 被裁剪到共享 deadline 剩余预算——剩余
    500s 时绝不会拿到完整 2400s per-attempt budget。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, "2400")  # HIGH 档 per-attempt
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "1500")  # remaining = 500
    captured = {}
    _capture_subprocess_run(monkeypatch, captured)
    monkeypatch.setattr(adapters_mod, "_require", lambda cmd: f"C:/fake/{cmd}.exe")
    adapters_mod.run_agent("hermes", "TASK", tmp_path)
    assert captured["timeout"] == 500.0  # min(2400, 500)——fallback 不能重启完整预算
    # per-attempt 显式参数同样被裁剪（既有显式参数优先级保留，但被 deadline 兜底）
    captured["timeout"] = None
    adapters_mod.run_agent("hermes", "TASK", tmp_path, timeout=4321)
    assert captured["timeout"] == 500.0


def test_run_agent_exhausted_deadline_raises_timeout_without_spawn(tmp_path, monkeypatch):
    """remaining ≤ 0 → subprocess.TimeoutExpired 有界早停，child 绝不 spawn；
    分类路径与真实 timeout 相同（ATTEMPT_TIMEOUT）。"""
    _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, "900")  # remaining = -100
    spawned = []

    def boom(*args, **kwargs):
        spawned.append(True)
        raise AssertionError("subprocess.run must not be called once the deadline is exhausted")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(adapters_mod, "_require", lambda cmd: f"C:/fake/{cmd}.exe")
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        adapters_mod.run_agent("hermes", "TASK", tmp_path)
    assert spawned == []
    assert exc.value.timeout == sl_mod.resolve_agent_attempt_timeout("hermes")
    reason, _ = sl_mod.classify_terminal_reason(
        agent="hermes", exc=exc.value, wb_telemetry=None, result_text=None
    )
    assert reason == "ATTEMPT_TIMEOUT"


def test_original_timeout_plus_fallback_cannot_exceed_stage_budget(tmp_path, monkeypatch):
    """Requirement C（runner 级语义的 enforcement 点）：original + fallback 两次
    invocation 共享同一绝对 deadline；第二次的 effective timeout 只能是剩余预算
    （绝无 2400+2400）；original 消耗完整预算后第二次在 spawn 前有界早停——
    累计墙钟不可能超过配置的 stage budget。"""
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_ATTEMPT_TIMEOUT, "2400")
    budget = 2400.0
    deadline = sl_mod.hermes_stage_deadline_value(budget_seconds=budget)
    assert deadline == 3400.0
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, f"{deadline:g}")
    captured = {}
    _capture_subprocess_run(monkeypatch, captured)
    monkeypatch.setattr(adapters_mod, "_require", lambda cmd: f"C:/fake/{cmd}.exe")

    def invoke_once():
        captured["timeout"] = None
        remaining_before = sl_mod.hermes_stage_remaining_seconds()
        adapters_mod.run_agent("hermes", "TASK", tmp_path)
        effective = captured["timeout"]
        assert effective is not None
        assert effective <= remaining_before + 1e-9  # 绝不超该时刻剩余预算
        return effective

    # original 拿满自己 per-attempt（2400 == 此刻剩余）→ 预算用尽
    t1 = invoke_once()
    assert t1 == 2400.0
    clock.advance(t1)
    assert sl_mod.hermes_stage_remaining_seconds() == 0.0
    with pytest.raises(subprocess.TimeoutExpired):
        invoke_once()  # fallback：剩余 0 → 不 spawn，有界早停
    assert captured["timeout"] is None
    # 变体：original 用掉 1200 → fallback 只剩 min(2400, 1200) = 1200（不是完整 2400）
    deadline2 = clock.now + budget  # 新 stage 的绝对 deadline
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, f"{deadline2:g}")
    t1b = invoke_once()
    assert t1b == 2400.0
    clock.advance(1200.0)  # original 实际消耗 1200 后失败
    t2 = invoke_once()  # fallback
    assert t2 == 1200.0  # min(2400, remaining 1200)——共享 deadline 收口
    # original + fallback 累计墙钟恰好贴住/不超 deadline2（无 2400+2400 空间）
    assert clock.now <= deadline2 + 1e-9
    assert sl_mod.hermes_stage_remaining_seconds() >= -1e-9


# ---------------------------------------------------------------------------
# F. Shared Hermes stage deadline —— 真实 runner Hermes stage 集成
#    （Requirement A/B/C/D/E/F；fake run_agent + 受控 registry + 注入时钟，
#     与 test_a5_fallback_runtime.py 第 2 节同型——A5 fallback 层真实执行）
# ---------------------------------------------------------------------------

def _dl_entry(model: str, *, provider: str = "custom", cost: str = "LOCAL_FREE",
              base_url: str | None = "http://127.0.0.1:11434/v1",
              locality: str = "local", tier: str = "T4") -> mr.RegistryEntry:
    return mr.RegistryEntry(
        model=model,
        provider=provider,
        base_url=base_url,
        applicable_agents=("hermes",),
        capability_tier=tier,
        cost_class=cost,
        locality=locality,
        qualification=mr.RuntimeQualification(
            status=mr.QUAL_STATUS_QUALIFIED,
            scope=mr.QUAL_SCOPE_MAIN,
            evidence=("stop-loss-deadline-test-fixture",),
            observed_at="2026-09-05T00:00:00",
        ),
        evidence=("stop-loss-deadline-test-fixture",),
    )


def _dl_registry(*entries: mr.RegistryEntry) -> dict[str, mr.RegistryEntry]:
    return {e.key(): e for e in entries}


def _dl_structured_ok(agent: str) -> str:
    if agent == "hermes":
        block = '{"status": "SUCCESS", "commit": null, "changed_files": [], "warnings": []}'
    elif agent == "workbuddy":
        block = ('{"verdict": "PASS", "blocking_rework": false, '
                 '"blocking_provenance": "structured", "findings": [], "warnings": []}')
    else:
        block = '{"verdict": "APPROVE", "blocking_rework": false, "findings": [], "warnings": []}'
    return f"ok\nAAF_STRUCTURED_RESULT_BEGIN\n{block}\nAAF_STRUCTURED_RESULT_END"


def _dl_run_runner(tmp_path, monkeypatch, fake_run_agent, *,
                   task_id="T-SL-DL-001", budget="2400", clock=None,
                   cost_auth=None, min_remaining=None):
    """scrub 相关 env + （可选）注入时钟 + budget env + （可选）cost auth /
    min_remaining env + fake run_agent 下跑真实 runner；返回 (out, clock)。
    clock 需在 fake_run_agent 定义前由测试安装（fake 要在调用内推进时钟模拟
    original 消耗预算）。"""
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_DEADLINE, raising=False)
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_BUDGET, raising=False)
    monkeypatch.delenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, raising=False)
    monkeypatch.delenv(cg.ENV_AUTH, raising=False)
    if clock is None:
        clock = _install_fake_clock(monkeypatch, start=1000.0)
    monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_BUDGET, budget)
    if min_remaining is not None:
        monkeypatch.setenv(sl_mod.ENV_HERMES_STAGE_MIN_REMAINING, min_remaining)
    if cost_auth is not None:
        monkeypatch.setenv(cg.ENV_AUTH, cost_auth)
    monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
    task_file, ws, out = _write_runner_task(
        tmp_path, task_id=task_id, risk=RISK_LOW,
        route="hermes -> workbuddy -> codex",
    )
    runner_mod.run(task_file, ws, out)
    return out, clock


def test_runner_shared_deadline_original_and_fallback_same_absolute_value(
        tmp_path, monkeypatch):
    """Requirement A/2/7（free fallback）：original 与 fallback 消费**同一个**
    绝对 deadline env（值完全一致、不 reset）；original 消耗大部分预算后 fallback
    只拿到剩余预算（1200s 而非重启的完整 per-attempt budget）。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _dl_registry(
        _dl_entry("aaa-orig"), _dl_entry("zzz-fb"),
    ))
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    seen = {"calls": [], "deadlines": {}, "models": {}, "remaining_at_fallback": None}

    def fake_run_agent(agent, prompt, workspace):
        seen["calls"].append(agent)
        seen["deadlines"].setdefault(agent, []).append(
            os.environ.get(sl_mod.ENV_HERMES_STAGE_DEADLINE))
        seen["models"].setdefault(agent, []).append(os.environ.get(cg.ENV_MODEL))
        if agent == "hermes":
            if seen["calls"].count("hermes") == 1:
                clock.advance(1200.0)  # original 消耗 2400s 预算中的 1200 后超时
                raise subprocess.TimeoutExpired("hermes", 2400.0)
            # 第二次 = A5 free fallback invocation（候选 env 覆盖已生效）
            seen["remaining_at_fallback"] = sl_mod.hermes_stage_remaining_seconds()
            return _dl_structured_ok(agent)
        return _dl_structured_ok(agent)

    out, _clock = _dl_run_runner(tmp_path, monkeypatch, fake_run_agent,
                                 task_id="T-SL-DL-A", budget="2400", clock=clock)
    # 两次 hermes invocation 看到同一个绝对 deadline 值（未 reset；Requirement 2/7）
    # FIX-002：runner 以无损 repr 序列化（:g 只留 6 位有效数字，可向未来舍入）
    assert seen["deadlines"]["hermes"] == [
        sl_mod.format_stage_deadline(3400.0), sl_mod.format_stage_deadline(3400.0)
    ]
    # original 消耗 1200s → fallback 只剩 1200s（不是完整 2400s per-attempt budget）
    assert seen["remaining_at_fallback"] == 1200.0
    assert seen["remaining_at_fallback"] >= sl_mod.DEFAULT_HERMES_STAGE_MIN_REMAINING
    # A3 初始 routing → original aaa-orig；A5 fallback → 候选 zzz-fb
    assert seen["models"]["hermes"] == ["aaa-orig", "zzz-fb"]
    assert seen["calls"] == ["hermes", "hermes", "workbuddy", "codex"]
    # deadline env 只属于 Hermes stage：workbuddy/codex stage 看不到
    assert seen["deadlines"]["workbuddy"] == [None]
    assert seen["deadlines"]["codex"] == [None]
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    audit = fr.load_fallback_runtime(out)
    assert audit is not None and audit["fallback_attempted"] is True
    assert audit["fallback_used"] is True and audit["final_actual_model"] == "zzz-fb"
    assert not (out / "stop_loss.json").exists()  # 成功 run 无 stop-loss claim
    assert os.environ.get(sl_mod.ENV_HERMES_STAGE_DEADLINE) is None  # 已还原


def test_runner_fast_original_failure_leaves_valid_fallback_budget(tmp_path, monkeypatch):
    """Requirement E：original 快速失败（几乎没消耗预算）→ fallback 拿到充足
    有效预算并成功；共享 deadline 未被 early-failure 缩短。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _dl_registry(
        _dl_entry("aaa-orig"), _dl_entry("zzz-fb"),
    ))
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    seen = {"hermes_calls": 0, "remaining_at_fallback": None}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen["hermes_calls"] += 1
            if seen["hermes_calls"] == 1:
                clock.advance(30.0)  # 快速失败（429 级秒退），预算几乎未消耗
                raise RuntimeError("hermes failed (exit=1)\nSTDERR:\nHTTP 429 rate limit hit")
            seen["remaining_at_fallback"] = sl_mod.hermes_stage_remaining_seconds()
            return _dl_structured_ok(agent)
        return _dl_structured_ok(agent)

    out, _clock = _dl_run_runner(tmp_path, monkeypatch, fake_run_agent,
                                 task_id="T-SL-DL-E", budget="2400", clock=clock)
    assert seen["hermes_calls"] == 2
    # 剩余预算 ≈ 2400 - 30 = 2370s >> 安全下限：fallback 有充足有效预算
    assert seen["remaining_at_fallback"] == 2370.0
    assert seen["remaining_at_fallback"] > 2000.0
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    assert not (out / "stop_loss.json").exists()


def test_runner_original_exhausts_budget_fallback_not_invoked_machine_reason(
        tmp_path, monkeypatch):
    """Requirement B+F：original invocation 耗尽共享 stage budget → fallback 不
    被发起（FREE/PAID 都拦截在 A5 层入口前）；stage fail closed 且 stop reason
    机器可读（STAGE_BUDGET_EXHAUSTED ∈ 词汇表；stop_loss.json + stage result
    json 双通道）。"""
    monkeypatch.setattr(mr, "baseline_registry", lambda: _dl_registry(
        _dl_entry("aaa-orig"), _dl_entry("zzz-fb"),
    ))
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            if hermes_calls["n"] == 1:
                clock.advance(2390.0)  # 消耗 2400s 预算中的 2390 → 剩 10 < 60s 下限
                raise subprocess.TimeoutExpired("hermes", 2400.0)
            raise AssertionError("fallback must NOT be invoked once the shared stage "
                                 "budget is exhausted")
        return _dl_structured_ok(agent)

    out, _clock = _dl_run_runner(tmp_path, monkeypatch, fake_run_agent,
                                 task_id="T-SL-DL-B", budget="2400", clock=clock)
    assert hermes_calls["n"] == 1  # 无第二模型（FREE 或 PAID 都没有）
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"
    result_md = (out / "hermes_result.md").read_text(encoding="utf-8")
    assert result_md.startswith("FRAMEWORK_ERROR")  # 原始失败保留（不伪装）
    # A5 层未进入：零 fallback/gate/paid artifact（evidence 集中在 stop_loss.json）
    assert not (out / "fallback_runtime.json").exists()
    assert not (out / "paid_escalation_gate.json").exists()
    assert not (out / "paid_fallback_runtime.json").exists()
    # 机器可读 stop reason（Requirement F + stop_loss 词汇表成员）
    sl = json.loads((out / "stop_loss.json").read_text(encoding="utf-8"))
    assert sl["terminal_reason"] == sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED
    assert sl_mod.STOP_REASON_STAGE_BUDGET_EXHAUSTED in sl_mod.TERMINAL_STOP_REASONS
    assert "remaining budget" in sl["detail"] and "10.0s" in sl["detail"]
    assert sl["agent"] == "hermes"
    stage = json.loads((out / "hermes_result.json").read_text(encoding="utf-8"))
    assert stage["stop_loss"]["terminal_reason"] == "STAGE_BUDGET_EXHAUSTED"
    # 共享 deadline env 已还原（不泄漏到后续调用方）
    assert os.environ.get(sl_mod.ENV_HERMES_STAGE_DEADLINE) is None


def test_runner_paid_fallback_obeys_same_shared_deadline_exhausted(tmp_path, monkeypatch):
    """Requirement D（paid，耗尽侧）：paid-only registry + exact auth；original
    耗尽共享 budget → 恰 0 次 paid invocation（与 free 一样被同一 deadline 拦截
    在 A5 层入口前）；授权未被消费（gate 未运行）；机器 reason 正确。"""
    task_id = "T-SL-DL-PAID-D1"
    monkeypatch.setattr(mr, "baseline_registry", lambda: _dl_registry(
        _dl_entry("aaa-orig"),
        _dl_entry("zzz-paid", provider="remote-api", cost="PAID",
                  base_url=None, locality="remote"),
    ))
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    hermes_calls = {"n": 0}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            hermes_calls["n"] += 1
            if hermes_calls["n"] == 1:
                clock.advance(2390.0)
                raise subprocess.TimeoutExpired("hermes", 2400.0)
            raise AssertionError("paid fallback must NOT be invoked once the shared "
                                 "stage budget is exhausted")
        return _dl_structured_ok(agent)

    out, _clock = _dl_run_runner(tmp_path, monkeypatch, fake_run_agent,
                                 task_id=task_id, budget="2400", clock=clock)
    assert hermes_calls["n"] == 1  # paid fallback 同样被 deadline gate 拦截
    assert fpg.load_paid_gate(out) is None  # gate 未运行 → A0 授权未消费
    assert fr.load_paid_fallback_runtime(out) is None
    assert not (out / "cost_auth_consumed.json").exists()
    sl = json.loads((out / "stop_loss.json").read_text(encoding="utf-8"))
    assert sl["terminal_reason"] == "STAGE_BUDGET_EXHAUSTED"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "WAITING"


def test_runner_paid_fallback_success_under_shared_deadline(tmp_path, monkeypatch):
    """Requirement D（paid，预算充足侧）：paid-only registry + exact auth +
    original 快速失败 → paid fallback 恰一次成功；shared deadline 全程约束同一
    预算（env 值跨 original/paid 两次 invocation 一致）。"""
    task_id = "T-SL-DL-PAID-D2"
    monkeypatch.setattr(cg, "resolve_effective_hermes", _REAL_RESOLVE)
    monkeypatch.setattr(mr, "baseline_registry", lambda: _dl_registry(
        _dl_entry("aaa-orig"),
        _dl_entry("zzz-paid", provider="remote-api", cost="PAID",
                  base_url=None, locality="remote"),
    ))
    clock = _install_fake_clock(monkeypatch, start=1000.0)
    seen = {"hermes_calls": 0, "deadlines": [], "models": []}

    def fake_run_agent(agent, prompt, workspace):
        if agent == "hermes":
            seen["hermes_calls"] += 1
            seen["deadlines"].append(os.environ.get(sl_mod.ENV_HERMES_STAGE_DEADLINE))
            seen["models"].append(os.environ.get(cg.ENV_MODEL))
            if seen["hermes_calls"] == 1:
                clock.advance(30.0)  # 快速失败；预算几乎未消耗
                raise RuntimeError("original invocation failed (simulated)")
            return _dl_structured_ok(agent)  # paid fallback 成功
        return _dl_structured_ok(agent)

    out, _clock = _dl_run_runner(
        tmp_path, monkeypatch, fake_run_agent, task_id=task_id, budget="2400",
        cost_auth=cg.scope_string(task_id, "hermes", "zzz-paid", "remote-api"),
    )
    assert seen["hermes_calls"] == 2
    assert seen["models"] == ["aaa-orig", "zzz-paid"]  # original + paid candidate
    # original 与 paid fallback 看到同一绝对 deadline（共享预算，未 reset；
    # FIX-002：runner 无损 repr 序列化）
    assert seen["deadlines"] == [
        sl_mod.format_stage_deadline(3400.0), sl_mod.format_stage_deadline(3400.0)
    ]
    paid = fr.load_paid_fallback_runtime(out)
    assert paid is not None
    assert paid["fallback_attempted"] is True and paid["fallback_used"] is True
    assert paid["paid_candidate"] == "zzz-paid@remote-api"
    fr.validate_paid_fallback_runtime_record(paid)
    gate = fpg.load_paid_gate(out)
    assert gate is not None and gate["gate_decision"] == "AUTHORIZED"
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "SUCCESS"
    assert not (out / "stop_loss.json").exists()
    assert os.environ.get(sl_mod.ENV_HERMES_STAGE_DEADLINE) is None
