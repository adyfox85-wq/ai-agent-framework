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
import os
import subprocess
import time
from pathlib import Path

import pytest

import ai_agent_framework.adapters as adapters_mod
import ai_agent_framework.runner as runner_mod
import ai_agent_framework.stop_loss as sl_mod
import ai_agent_framework.workbuddy_retry as wb_retry_mod

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
