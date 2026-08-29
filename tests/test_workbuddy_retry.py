"""AAF-v0.4-TASK-011 + FIX-001 — WorkBuddy Stage Reliability / Bounded Retry tests.

Test matrix（Requirement 20）+ 真实 incident regressions（Requirement 21）：
A. attempt1 empty → attempt2 success        → stage success / Codex eligible
B. attempt1 timeout → attempt2 success      → stage success
C. all attempts empty                        → FRAMEWORK_ERROR（fail closed）
D. all attempts timeout                      → bounded FRAMEWORK_ERROR
E. permanent executable/auth/config failure  → no pointless retry
F. valid WorkBuddy FAIL output               → no retry / blocking preserved
G. timeout child cleaned before retry
H. retry never creates concurrent processes
I. overall stage budget enforced
J. attempt telemetry accurate
K. model/config unchanged across retries
+ CLOSURE-002（exit=0 + placeholder-only stderr）与 CLOSURE-003（TimeoutExpired）
  两个真实 incident 的回归。

FIX-001（confirmed-dead-before-retry + single absolute stage deadline）：
22A. taskkill 失败 + kill 失败 + 进程存活 → 无 retry / fail closed / 不注销
22B. taskkill 失败但 fallback kill 确认退出 → cleanup confirmed / retry 允许
22C. 确认终止后 reap 失败 → 按资源安全语义如实分类（retryable + evidence）
22D. registry 保留 unsafe child 直到 terminal handling
22E. 下一 attempt/run 不能与 unsafe child 重叠（Registry Gate）
23A. attempt timeout + cleanup + backoff 消费同一绝对 deadline
23B. cleanup 等待被剩余 deadline 裁剪（无独立全尺寸等待）
23C. 剩余安全 budget 不足 → 不启动下一次 attempt
23D. reported stage elapsed 尊重配置 budget（确定性容差）
23E. cleanup reserve 防止首次 attempt 吃掉全部 budget
24.  既有 retry 矩阵保持 + telemetry 暴露 cleanup/deadline evidence

全部使用 mocked subprocess / fake CLI（Requirement 25）；唯一的真实子进程测试用
python sleep（非 CodeBuddy，不消耗积分、不等待真实 3600s）。不驱动任何 GUI。
"""
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ai_agent_framework.adapters as adapters_mod
import ai_agent_framework.model_observation as model_observation_mod
import ai_agent_framework.runner as runner_mod
import ai_agent_framework.workbuddy_retry as wb_retry_mod


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProc:
    """Scripted Popen fake。behaviors 逐次消费（每次 communicate 一个条目）：

    ('output', stdout, stderr)                       → exit=0 输出
    ('exit', code, stdout, stderr)                   → 指定退出码
    ('timeout',)                                     → 抛 subprocess.TimeoutExpired
    ('sleep_timeout', seconds)                       → sleep 后抛 TimeoutExpired
    kill 后 communicate = drain 语义（返回 drained_*，returncode=-9）。

    FIX-001 扩展（清理失败路径，Requirement 22/25）：
    - alive_after_kill=True: kill() 后 poll() 仍返回 None（进程“杀不死”，仍存活）
    - kill_raises: kill() 抛指定异常（kill 调用本身失败）
    - reap_raises=True: kill 后 communicate 仍抛 OSError（reap 失败）
    - communicate_timeouts: 记录每次 communicate 的 timeout 参数（deadline 裁剪证据）
    """

    def __init__(self, pid, behavior_iter, drained_out='', drained_err='',
                 alive_after_kill=False, kill_raises=None, reap_raises=False):
        self.pid = pid
        self.behaviors = behavior_iter
        self.drained_out = drained_out
        self.drained_err = drained_err
        self.returncode = None
        self.killed = False
        self.communicate_calls = 0
        self.inputs = []
        self.communicate_timeouts = []
        self.spawn_args = None
        self.spawn_kwargs = None
        self.alive_after_kill = alive_after_kill
        self.kill_raises = kill_raises
        self.reap_raises = reap_raises

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        self.inputs.append(input)
        self.communicate_timeouts.append(timeout)
        if self.killed:
            if self.alive_after_kill:
                raise OSError('process still alive (simulated)')
            if self.reap_raises:
                raise OSError('pipe drain failed (simulated reap failure)')
            self.returncode = -9
            return self.drained_out, self.drained_err
        try:
            entry = next(self.behaviors)
        except StopIteration:
            self.returncode = 0
            return '', ''
        kind, *rest = entry
        if kind == 'output':
            self.returncode = 0
            return rest[0], rest[1]
        if kind == 'exit':
            self.returncode = rest[0]
            return rest[1], rest[2]
        if kind == 'timeout':
            raise subprocess.TimeoutExpired('fake', timeout)
        if kind == 'sleep_timeout':
            t = min(float(rest[0]), timeout if timeout is not None else float(rest[0]))
            time.sleep(t)
            raise subprocess.TimeoutExpired('fake', t)
        raise AssertionError(f'unknown behavior {kind!r}')

    def poll(self):
        if self.alive_after_kill and self.killed:
            return None  # 已被 kill 但进程仍存活（final liveness check 必须失败）
        return self.returncode

    def kill(self):
        if self.kill_raises:
            exc = self.kill_raises if isinstance(self.kill_raises, Exception) else OSError('kill failed (simulated)')
            raise exc
        self.killed = True
        if not self.alive_after_kill:
            self.returncode = -9


def install_fake_popen(monkeypatch, behaviors, drained_out='', drained_err='',
                       taskkill_result=True):
    """替换 retry 层 _Popen；spawn 时断言无并发 active child（Requirement H）。

    behaviors 是一个共享迭代器：所有 attempt 按顺序消费同一脚本序列。
    taskkill_result: 脚本化 taskkill 返回值（True=树杀成功；False=taskkill 失败），
    或一个 callable ``fn(pid, timeout=None)``（用于断言 deadline 裁剪证据）。
    """
    spawns = []
    counter = itertools.count(1000)
    behavior_iter = iter(behaviors)

    def fake_popen(*args, **kwargs):
        assert wb_retry_mod.active_child_pids() == [], (
            'concurrent WorkBuddy child still registered before spawn'
        )
        proc = FakeProc(next(counter), behavior_iter, drained_out, drained_err)
        proc.spawn_args = args[0] if args else None
        proc.spawn_kwargs = kwargs
        spawns.append(proc)
        return proc

    monkeypatch.setattr(wb_retry_mod, '_Popen', fake_popen)
    if callable(taskkill_result):
        monkeypatch.setattr(wb_retry_mod, '_taskkill', taskkill_result)
    else:
        monkeypatch.setattr(
            wb_retry_mod, '_taskkill', lambda pid, timeout=None: taskkill_result
        )
    return spawns


def make_policy(max_attempts=2, timeout=60.0, backoff=0.0, budget=None, reserve=0.0):
    budget = (
        budget if budget is not None
        else (max_attempts * timeout + (max_attempts - 1) * backoff)
    )
    return wb_retry_mod.WorkBuddyRetryPolicy(
        max_attempts=max_attempts,
        per_attempt_timeout=timeout,
        backoff_seconds=backoff,
        overall_stage_budget=budget,
        cleanup_reserve=reserve,
    )


def run_retry(monkeypatch, behaviors, policy=None, prompt='PROMPT', workspace=None,
              taskkill_result=True):
    """直接调用 retry 编排层（fake CLI）。返回 (output, telemetry, spawns)。"""
    spawns = install_fake_popen(monkeypatch, behaviors, taskkill_result=taskkill_result)
    policy = policy or make_policy()
    ws = workspace or Path('.')
    out, telemetry = wb_retry_mod.run_workbuddy_with_retry(
        ['codebuddy', '-p', '--output-format', 'text', '-y'],
        {'CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS': '1'},
        prompt,
        ws,
        policy,
    )
    assert wb_retry_mod.active_child_pids() == []  # 无 orphan（Requirement 10）
    return out, telemetry, spawns


# ---------------------------------------------------------------------------
# Failure classification（Requirement 1 / 21）
# ---------------------------------------------------------------------------


def test_classify_timeout_retryable():
    cls, reason = wb_retry_mod.classify_failure(
        timed_out=True, returncode=None, stdout='', stderr=''
    )
    assert cls is wb_retry_mod.FailureClass.RETRYABLE_TRANSIENT
    assert reason == 'TimeoutExpired'


def test_classify_empty_output_retryable():
    cls, reason = wb_retry_mod.classify_failure(
        timed_out=False, returncode=0, stdout='', stderr=''
    )
    assert cls is wb_retry_mod.FailureClass.RETRYABLE_TRANSIENT
    assert reason == 'empty output (exit=0)'


def test_classify_placeholder_gateway_retryable_closure002():
    """CLOSURE-002 真实形态：exit=0 + 空 stdout + gateway placeholder-only stderr。"""
    stderr = (
        'Empty stream: upstream gateway sent only placeholder chunks '
        'without any model output (chunks=1, bytes=748)'
    )
    cls, reason = wb_retry_mod.classify_failure(
        timed_out=False, returncode=0, stdout='', stderr=stderr
    )
    assert cls is wb_retry_mod.FailureClass.RETRYABLE_TRANSIENT
    assert 'placeholder' in reason


def test_classify_nonzero_exit_permanent():
    """非零退出且无 transient evidence（auth/config/CLI fatal 等）→ 不重试。"""
    cls, reason = wb_retry_mod.classify_failure(
        timed_out=False, returncode=5, stdout='', stderr='configuration error: invalid API key'
    )
    assert cls is wb_retry_mod.FailureClass.NON_RETRYABLE
    assert reason == 'exit=5'


def test_classify_nonzero_exit_with_placeholder_evidence_retryable():
    cls, reason = wb_retry_mod.classify_failure(
        timed_out=False, returncode=1, stdout='',
        stderr='Empty stream: upstream gateway sent only placeholder chunks',
    )
    assert cls is wb_retry_mod.FailureClass.RETRYABLE_TRANSIENT


# ---------------------------------------------------------------------------
# Policy（Requirement 4/5/6）
# ---------------------------------------------------------------------------


def test_policy_defaults(monkeypatch):
    for var in ('AAF_WORKBUDDY_MAX_ATTEMPTS', 'AAF_WORKBUDDY_TIMEOUT',
                'AAF_WORKBUDDY_BACKOFF', 'AAF_WORKBUDDY_STAGE_BUDGET', 'AAF_WORKBUDDY_RETRY'):
        monkeypatch.delenv(var, raising=False)
    p = wb_retry_mod.load_workbuddy_policy()
    assert p.max_attempts == 2
    assert p.per_attempt_timeout == 900.0
    assert p.backoff_seconds == 30.0
    # budget = max_attempts*timeout + (max_attempts-1)*backoff
    assert p.overall_stage_budget == 2 * 900.0 + 30.0


def test_policy_env_overrides(monkeypatch):
    monkeypatch.setenv('AAF_WORKBUDDY_MAX_ATTEMPTS', '4')
    monkeypatch.setenv('AAF_WORKBUDDY_TIMEOUT', '100')
    monkeypatch.setenv('AAF_WORKBUDDY_BACKOFF', '5')
    monkeypatch.setenv('AAF_WORKBUDDY_STAGE_BUDGET', '500')
    p = wb_retry_mod.load_workbuddy_policy()
    assert (p.max_attempts, p.per_attempt_timeout, p.backoff_seconds) == (4, 100.0, 5.0)
    assert p.overall_stage_budget == 500.0


def test_policy_budget_formula_with_more_attempts(monkeypatch):
    monkeypatch.setenv('AAF_WORKBUDDY_MAX_ATTEMPTS', '3')
    monkeypatch.setenv('AAF_WORKBUDDY_TIMEOUT', '100')
    monkeypatch.setenv('AAF_WORKBUDDY_BACKOFF', '10')
    monkeypatch.delenv('AAF_WORKBUDDY_STAGE_BUDGET', raising=False)
    p = wb_retry_mod.load_workbuddy_policy()
    assert p.overall_stage_budget == 3 * 100.0 + 2 * 10.0


def test_policy_disabled_no_retry(monkeypatch):
    monkeypatch.setenv('AAF_WORKBUDDY_RETRY', '0')
    monkeypatch.setenv('AAF_WORKBUDDY_MAX_ATTEMPTS', '5')
    p = wb_retry_mod.load_workbuddy_policy()
    assert p.max_attempts == 1  # 显式禁用 → 单次 attempt


def test_policy_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv('AAF_WORKBUDDY_TIMEOUT', 'abc')
    monkeypatch.setenv('AAF_WORKBUDDY_MAX_ATTEMPTS', 'xyz')
    p = wb_retry_mod.load_workbuddy_policy()
    assert p.per_attempt_timeout == 900.0
    assert p.max_attempts == 2


# ---------------------------------------------------------------------------
# 矩阵 A/B/C/D/E/F/J/K + 真实 incident regression
# ---------------------------------------------------------------------------


def test_a_empty_then_success(monkeypatch):
    """A: attempt1 empty → attempt2 success → stage success。"""
    out, telemetry, spawns = run_retry(
        monkeypatch, [('output', '', ''), ('output', 'PASS verified', '')]
    )
    assert out == 'PASS verified'
    assert telemetry['attempt_count'] == 2
    assert telemetry['retried'] is True
    assert telemetry['outcome'] == 'SUCCESS'
    assert telemetry['attempts'][0]['status'] == 'FAILED'
    assert telemetry['attempts'][0]['failure_class'] == 'retryable_transient'
    assert telemetry['attempts'][0]['retry_reason'] == 'empty output (exit=0)'
    assert telemetry['attempts'][0]['stdout_empty'] is True
    assert telemetry['attempts'][1]['status'] == 'SUCCESS'
    assert telemetry['last_failure']['retry_reason'] == 'empty output (exit=0)'


def test_b_timeout_then_success(monkeypatch):
    """B: attempt1 timeout → attempt2 success → stage success。"""
    out, telemetry, _ = run_retry(
        monkeypatch, [('timeout',), ('output', 'PASS verified', '')]
    )
    assert out == 'PASS verified'
    assert telemetry['attempt_count'] == 2
    assert telemetry['timeout_occurred'] is True
    assert telemetry['attempts'][0]['timed_out'] is True
    assert telemetry['attempts'][0]['retry_reason'] == 'TimeoutExpired'


def test_c_all_attempts_empty_fail_closed(monkeypatch):
    """C: 全部 empty → FRAMEWORK_ERROR（fail closed），不把空输出当 PASS。"""
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(monkeypatch, [('output', '', ''), ('output', '', '')])
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 2
    assert telemetry['outcome'] == 'RETRIES_EXHAUSTED'
    assert telemetry['empty_occurred'] is True
    assert telemetry['timeout_occurred'] is False
    assert telemetry['retry_reasons'] == ['empty output (exit=0)', 'empty output (exit=0)']
    msg = str(exc.value)
    assert '2 attempt(s)' in msg
    assert 'empty-output occurred: yes' in msg


def test_d_all_timeouts_bounded(monkeypatch):
    """D: 全部 timeout → 有界 FRAMEWORK_ERROR（attempt 数有界、墙钟 ≤ budget）。"""
    policy = make_policy(max_attempts=3, timeout=0.4, backoff=0.0, budget=1.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(
            monkeypatch,
            [('sleep_timeout', 60.0), ('sleep_timeout', 60.0), ('sleep_timeout', 60.0)],
            policy=policy,
        )
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 3
    assert telemetry['timeout_occurred'] is True
    assert telemetry['stage_total_elapsed_seconds'] <= 1.0 + 0.15
    assert 'timeout occurred: yes' in str(exc.value)


def test_e_permanent_failure_no_pointless_retry(monkeypatch):
    """E: 非零退出（永久性 auth/config 错误）→ 不重试，快速失败。"""
    with pytest.raises(wb_retry_mod.WorkBuddyPermanentError) as exc:
        run_retry(monkeypatch, [('exit', 5, '', 'configuration error: invalid API key')])
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 1  # 没有无意义重试
    assert telemetry['outcome'] == 'PERMANENT_FAILURE'
    assert telemetry['attempts'][0]['failure_class'] == 'non_retryable'


def test_e_spawn_failure_permanent(monkeypatch):
    """E: Popen 本身失败（missing exe / 无效 invocation）→ 永久，不重试。"""
    def broken_popen(*args, **kwargs):
        raise OSError('file not found')
    monkeypatch.setattr(wb_retry_mod, '_Popen', broken_popen)
    with pytest.raises(wb_retry_mod.WorkBuddyPermanentError) as exc:
        wb_retry_mod.run_workbuddy_with_retry(
            ['codebuddy'], {'A': '1'}, 'P', Path('.'), make_policy(max_attempts=3)
        )
    assert exc.value.telemetry['attempt_count'] == 1
    assert 'process start failed' in exc.value.telemetry['attempts'][0]['retry_reason']


def test_f_valid_fail_verdict_no_retry(monkeypatch):
    """F: WorkBuddy 有效 FAIL 输出 → 不重试，blocking 结果原样保留。"""
    out, telemetry, _ = run_retry(monkeypatch, [('output', 'FAIL: B1 broken', '')])
    assert out == 'FAIL: B1 broken'
    assert telemetry['attempt_count'] == 1
    assert telemetry['retried'] is False
    assert telemetry['outcome'] == 'SUCCESS'  # transport 成功；verdict 归 Framework


def test_g_timeout_child_killed_before_retry(monkeypatch):
    """G: timeout 的 child 在 retry 前被清理（killed + 注销），无 orphan。"""
    out, telemetry, spawns = run_retry(
        monkeypatch, [('timeout',), ('output', 'ok', '')]
    )
    assert out == 'ok'
    p1, p2 = spawns
    assert p1.killed is True          # attempt1（timeout）已被 kill
    assert p2.killed is False         # attempt2 正常结束
    assert p1.communicate_calls >= 2  # kill 后已排空管道（reap）
    assert wb_retry_mod.active_child_pids() == []


def test_h_no_concurrent_children(monkeypatch):
    """H: retry 期间任何时刻最多一个 child（spawn 时 registry 必须为空）。"""
    _, _, spawns = run_retry(
        monkeypatch,
        [('output', '', ''), ('timeout',), ('output', 'ok', '')],
        policy=make_policy(max_attempts=3),
    )
    assert len(spawns) == 3
    # install_fake_popen 的 spawn 断言已证明：每次 spawn 前无 active child；
    # 这里再显式验证：只有 timeout 的 attempt 被 kill，其余正常结束，全部注销
    assert spawns[1].killed is True    # attempt2（timeout）被 kill 后才启动 attempt3
    assert spawns[0].killed is False   # 正常结束（empty 输出不是 kill）
    assert spawns[2].killed is False
    assert wb_retry_mod.active_child_pids() == []


def test_i_stage_budget_enforced(monkeypatch):
    """I: 整体 stage budget 硬上限——budget 耗尽后不再启动新 attempt。"""
    policy = make_policy(max_attempts=3, timeout=60.0, backoff=0.0, budget=1.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(
            monkeypatch,
            [('sleep_timeout', 60.0), ('sleep_timeout', 60.0), ('sleep_timeout', 60.0)],
            policy=policy,
        )
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 1  # budget 只够第一次 attempt
    assert telemetry['stage_total_elapsed_seconds'] <= 1.0 + 0.15


def test_j_attempt_telemetry_accurate(monkeypatch):
    """J: attempt telemetry 逐条准确（状态/类别/原因/超时/空输出/总耗时）。"""
    out, telemetry, _ = run_retry(
        monkeypatch,
        [('output', '', ''), ('timeout',), ('output', 'PASS verified', '')],
        policy=make_policy(max_attempts=3),
    )
    assert out == 'PASS verified'
    assert telemetry['attempt_count'] == 3
    assert telemetry['retried'] is True
    assert telemetry['outcome'] == 'SUCCESS'
    assert telemetry['retry_reasons'] == ['empty output (exit=0)', 'TimeoutExpired']
    assert telemetry['timeout_occurred'] is True
    assert telemetry['empty_occurred'] is True
    a0, a1, a2 = telemetry['attempts']
    assert (a0['status'], a0['failure_class'], a0['stdout_empty'], a0['timed_out']) == (
        'FAILED', 'retryable_transient', True, False)
    assert (a1['status'], a1['failure_class'], a1['timed_out'], a1['stdout_empty']) == (
        'FAILED', 'retryable_transient', True, False)
    assert (a2['status'], a2['failure_class']) == ('SUCCESS', None)
    assert telemetry['last_failure']['attempt_index'] == 2
    assert telemetry['stage_total_elapsed_seconds'] >= 0
    # 机器 artifact 可序列化
    json.dumps(telemetry)


def test_k_same_invocation_across_retries(monkeypatch):
    """K: retry 复用完全相同的 invocation（same args / env / stdin），不换模型。"""
    args = ['codebuddy', '-p', '--output-format', 'text', '-y']
    env = {'CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS': '1'}
    prompt = 'SAME PROMPT'
    spawns = install_fake_popen(
        monkeypatch, [('output', '', ''), ('output', 'ok', '')]
    )
    out, telemetry = wb_retry_mod.run_workbuddy_with_retry(
        args, env, prompt, Path('.'), make_policy()
    )
    assert out == 'ok'
    assert telemetry['attempt_count'] == 2
    s0, s1 = spawns
    assert s0.spawn_args is s1.spawn_args       # 同一 args 对象（含 --model 等任何参数都不变）
    assert s0.spawn_kwargs['env'] is s1.spawn_kwargs['env']
    assert s0.inputs[0] == s1.inputs[0] == prompt
    assert '--model' not in ' '.join(s0.spawn_args)  # 无显式模型切换


def test_closure002_regression_empty_output_then_success(monkeypatch):
    """CLOSURE-002 回归：exit=0 + placeholder-only gateway stderr → retry 后成功。"""
    stderr = (
        'Empty stream: upstream gateway sent only placeholder chunks '
        'without any model output (chunks=1, bytes=748)'
    )
    out, telemetry, _ = run_retry(
        monkeypatch, [('output', '', stderr), ('output', 'PASS verified', '')]
    )
    assert out == 'PASS verified'
    assert telemetry['attempt_count'] == 2
    assert telemetry['attempts'][0]['retry_reason'] == (
        'empty output (exit=0); upstream gateway placeholder-only'
    )
    assert 'placeholder' in telemetry['attempts'][0]['stderr_tail']


def test_closure003_regression_timeout_then_success(monkeypatch):
    """CLOSURE-003 回归：WorkBuddy stage TimeoutExpired → retry 后成功。"""
    out, telemetry, _ = run_retry(
        monkeypatch, [('timeout',), ('output', 'PASS verified', '')]
    )
    assert out == 'PASS verified'
    assert telemetry['attempt_count'] == 2
    assert telemetry['attempts'][0]['retry_reason'] == 'TimeoutExpired'
    assert telemetry['attempts'][0]['timed_out'] is True


def test_stale_active_child_fails_closed(monkeypatch):
    """H/不变量：spawn 前存在遗留 active child → fail closed（绝不并发双跑）。"""
    wb_retry_mod._ACTIVE_CHILD_PIDS.add(999999)
    try:
        with pytest.raises(wb_retry_mod.WorkBuddyConcurrencyError) as exc:
            wb_retry_mod.run_workbuddy_with_retry(
                ['codebuddy'], {'A': '1'}, 'P', Path('.'), make_policy()
            )
        assert exc.value.telemetry['attempt_count'] == 0
    finally:
        wb_retry_mod._ACTIVE_CHILD_PIDS.discard(999999)


def test_backoff_included_in_stage_elapsed(monkeypatch):
    """Requirement 7：backoff 计入 stage 总墙钟（不 tight loop）。"""
    policy = make_policy(max_attempts=3, timeout=60.0, backoff=0.1, budget=3.0)
    out, telemetry, _ = run_retry(
        monkeypatch,
        [('output', '', ''), ('output', '', ''), ('output', 'ok', '')],
        policy=policy,
    )
    assert out == 'ok'
    assert telemetry['attempt_count'] == 3
    # 两次 backoff 必须真实 sleep 并计入 elapsed（不是 tight loop）。Windows 定时器
    # 合并/相位使 sleep(n) 可能提前 ~13ms 返回（实测 sleep(0.2)≈0.187s），故用
    # 明确容差 2*0.1-0.03：仍严格证明两次 sleep 都发生了（0 则必 < 0.1）。
    assert telemetry['stage_total_elapsed_seconds'] >= 2 * 0.1 - 0.03  # 两次 backoff


# ---------------------------------------------------------------------------
# adapters.run_agent 集成（telemetry 槽位 / MISSING_COMMAND 永久失败）
# ---------------------------------------------------------------------------


def test_run_agent_workbuddy_retry_sets_telemetry(tmp_path, monkeypatch):
    install_fake_popen(monkeypatch, [('output', '', ''), ('output', 'PASS ok', '')])
    monkeypatch.setenv('AAF_WORKBUDDY_BACKOFF', '0')
    monkeypatch.setattr(adapters_mod, '_require', lambda cmd: f'C:/fake/{cmd}.exe')
    out = adapters_mod.run_agent('workbuddy', 'PROMPT', tmp_path)
    assert out == 'PASS ok'
    telemetry = adapters_mod.pop_workbuddy_telemetry()
    assert telemetry['attempt_count'] == 2
    assert telemetry['outcome'] == 'SUCCESS'
    assert adapters_mod.pop_workbuddy_telemetry() is None  # 一次性 pop


def test_run_agent_workbuddy_missing_executable_no_retry(tmp_path, monkeypatch):
    def fake_require(cmd):
        raise RuntimeError('MISSING_COMMAND: codebuddy')
    monkeypatch.setattr(adapters_mod, '_require', fake_require)
    with pytest.raises(adapters_mod.WorkBuddyPermanentError) as exc:
        adapters_mod.run_agent('workbuddy', 'PROMPT', tmp_path)
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 0
    assert telemetry['outcome'] == 'PERMANENT_FAILURE'
    assert 'permanent, no retry' in str(exc.value)


def test_run_agent_hermes_codex_unaffected_by_retry(tmp_path, monkeypatch):
    """Requirement 2：Hermes / Codex 不得自动获得 retry（行为默认关闭）。"""
    captured = {}

    def fake_run(args, cwd, input, text, encoding, errors, capture_output, timeout, env, **kwargs):
        captured['args'] = args
        captured['timeout'] = timeout
        class FakeProc:
            returncode = 0
            stdout = 'ok'
            stderr = ''
        return FakeProc()

    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(adapters_mod, '_require', lambda cmd: f'C:/fake/{cmd}.exe')
    out = adapters_mod.run_agent('hermes', 'PROMPT', tmp_path, timeout=4321)
    assert out == 'ok'
    assert captured['timeout'] == 4321
    assert adapters_mod.pop_workbuddy_telemetry() is None  # hermes 无 retry telemetry


# ---------------------------------------------------------------------------
# 真实子进程清理（Requirement 9/10：Windows 行为必须测试）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != 'nt', reason='Windows taskkill 行为')
def test_windows_real_timeout_child_cleaned(tmp_path, monkeypatch):
    """G（Windows 真实）：timeout 后 child 必须被杀并移出进程表（无 orphan）。"""
    spawned = []
    real_popen = subprocess.Popen

    def spy_popen(*args, **kwargs):
        p = real_popen(*args, **kwargs)
        spawned.append(p)
        return p

    monkeypatch.setattr(wb_retry_mod, '_Popen', spy_popen)
    policy = make_policy(max_attempts=1, timeout=1.0, backoff=0.0, budget=10.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted):
        wb_retry_mod.run_workbuddy_with_retry(
            [sys.executable, '-c', 'import time; time.sleep(120)'],
            {**os.environ},
            None,
            tmp_path,
            policy,
        )
    assert len(spawned) == 1
    assert spawned[0].poll() is not None  # 已结束（reaped）
    # 移出进程表：tasklist /FI 无匹配时输出本地化提示行且不含该 PID
    # （exit code 在不同 Windows 版本不可靠，统一按 PID 是否出现在输出中判定；
    #  GBK/cp936 字节解码避免编码问题）
    r = subprocess.run(
        ['tasklist', '/FI', f'PID eq {spawned[0].pid}'],
        capture_output=True, timeout=30,
    )
    out_text = r.stdout.decode('gbk', errors='replace')
    assert str(spawned[0].pid) not in out_text, (
        f'orphan process {spawned[0].pid} still in process table: {out_text[:200]}'
    )
    assert wb_retry_mod.active_child_pids() == []


@pytest.mark.skipif(os.name == 'nt', reason='POSIX kill 行为')
def test_posix_real_timeout_child_cleaned(tmp_path, monkeypatch):
    spawned = []
    real_popen = subprocess.Popen

    def spy_popen(*args, **kwargs):
        p = real_popen(*args, **kwargs)
        spawned.append(p)
        return p

    monkeypatch.setattr(wb_retry_mod, '_Popen', spy_popen)
    policy = make_policy(max_attempts=1, timeout=1.0, backoff=0.0, budget=10.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted):
        wb_retry_mod.run_workbuddy_with_retry(
            [sys.executable, '-c', 'import time; time.sleep(120)'],
            {**os.environ},
            None,
            tmp_path,
            policy,
        )
    assert len(spawned) == 1
    assert spawned[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(spawned[0].pid, 0)
    assert wb_retry_mod.active_child_pids() == []


# ---------------------------------------------------------------------------
# Runner 集成（Requirement 14/15/18/19：Codex gating / artifact / stage result）
# ---------------------------------------------------------------------------

WB_ROUTE_TASK = """# Task ID
T-WBRETRY

# Task Name
WorkBuddy retry runner integration

# Objective
验证有界 retry 与 Codex gating

# Route
workbuddy -> codex

# Acceptance
1. 通过
"""


def install_runner(monkeypatch, behaviors):
    """runner 集成环境：workbuddy 走真实 retry 层（fake CLI），codex 假 APPROVE。"""
    real_run_agent = adapters_mod.run_agent
    calls = []
    spawns = install_fake_popen(monkeypatch, behaviors)
    monkeypatch.setattr(adapters_mod, '_require', lambda cmd: f'C:/fake/{cmd}.exe')
    monkeypatch.setattr(model_observation_mod, 'observe_stage', lambda *a, **k: None)
    monkeypatch.setenv('AAF_WORKBUDDY_BACKOFF', '0')

    def wrapper(agent, prompt, workspace):
        calls.append(agent)
        if agent == 'workbuddy':
            return real_run_agent(agent, prompt, workspace)
        return {'codex': 'APPROVE'}[agent]

    monkeypatch.setattr(runner_mod, 'run_agent', wrapper)
    return calls, spawns


def run_runner(monkeypatch, tmp_path, behaviors):
    calls, spawns = install_runner(monkeypatch, behaviors)
    task_file = tmp_path / 'TASK.md'
    task_file.write_text(WB_ROUTE_TASK, encoding='utf-8')
    ws = tmp_path / 'ws'
    ws.mkdir()
    out = tmp_path / 'out'
    report_path = runner_mod.run(task_file, ws, out)
    return calls, spawns, out, report_path


def test_runner_retry_success_then_codex_runs(tmp_path, monkeypatch):
    """A/18/14/15：empty→success → stage SUCCESS、Codex 运行、attempt 可见。"""
    calls, spawns, out, _ = run_runner(
        monkeypatch, tmp_path, [('output', '', ''), ('output', '**Result: PASS**\nverified', '')]
    )
    assert calls == ['workbuddy', 'codex']  # retry 成功 → 正常进入 Codex
    report = (out / 'REPORT.md').read_text(encoding='utf-8')
    assert '## Current Status\nSUCCESS' in report
    # 机器 artifact（Requirement 14：详细 attempt evidence）
    artifact = json.loads((out / 'workbuddy_attempts.json').read_text(encoding='utf-8'))
    assert artifact['attempt_count'] == 2
    assert artifact['outcome'] == 'SUCCESS'
    # stage result 摘要（Requirement 14/15）
    stage = json.loads((out / 'workbuddy_result.json').read_text(encoding='utf-8'))
    assert stage['execution_retries']['attempt_count'] == 2
    assert stage['execution_retries']['artifact_path'].endswith('workbuddy_attempts.json')
    assert stage['stage_timing']['stage_elapsed_seconds'] is not None  # 整 stage 墙钟
    # REPORT 紧凑显示 attempts（Requirement 14/15）
    assert 'attempts=2' in report
    # 单一 canonical 结果（Requirement 19）：result.md 只有最终输出
    assert (out / 'workbuddy_result.md').read_text(encoding='utf-8') == '**Result: PASS**\nverified'


def test_runner_retry_timeout_then_codex_runs(tmp_path, monkeypatch):
    """B/18：timeout→success → stage SUCCESS、Codex 运行。"""
    calls, _, out, report_path = run_runner(
        monkeypatch, tmp_path, [('timeout',), ('output', '**Result: PASS**\nverified', '')]
    )
    assert calls == ['workbuddy', 'codex']
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nSUCCESS' in report
    artifact = json.loads((out / 'workbuddy_attempts.json').read_text(encoding='utf-8'))
    assert artifact['attempt_count'] == 2
    assert artifact['timeout_occurred'] is True


def test_runner_all_empty_exhausted_codex_not_run(tmp_path, monkeypatch):
    """C/17/18：retries 用尽 → FRAMEWORK_ERROR 带完整历史、Codex 不运行、WAITING。"""
    calls, _, out, report_path = run_runner(
        monkeypatch, tmp_path, [('output', '', ''), ('output', '', '')]
    )
    assert calls == ['workbuddy']  # Codex 不运行（Requirement 18）
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nWAITING' in report
    result_md = (out / 'workbuddy_result.md').read_text(encoding='utf-8')
    assert result_md.startswith('FRAMEWORK_ERROR')
    assert 'WorkBuddyRetriesExhausted' in result_md
    # Requirement 17：不得只给 FRAMEWORK_ERROR 丢历史
    assert '2 attempt(s)' in result_md
    assert 'empty-output occurred: yes' in result_md
    assert 'last failure' in result_md
    artifact = json.loads((out / 'workbuddy_attempts.json').read_text(encoding='utf-8'))
    assert artifact['outcome'] == 'RETRIES_EXHAUSTED'
    assert artifact['attempt_count'] == 2


def test_runner_valid_fail_verdict_no_retry_blocking_preserved(tmp_path, monkeypatch):
    """F/12/13：有效 FAIL verdict → 不 retry、blocking 结果保留、终态 WAITING。"""
    calls, _, out, report_path = run_runner(
        monkeypatch, tmp_path, [('output', 'FAIL: B1 broken', '')]
    )
    artifact = json.loads((out / 'workbuddy_attempts.json').read_text(encoding='utf-8'))
    assert artifact['attempt_count'] == 1
    assert artifact['retried'] is False
    assert (out / 'workbuddy_result.md').read_text(encoding='utf-8') == 'FAIL: B1 broken'
    report = report_path.read_text(encoding='utf-8')
    assert '## Current Status\nWAITING' in report
    # 既有执行链语义：FAIL verdict 不触发 transport retry，也不伪装 SUCCESS
    assert calls == ['workbuddy', 'codex']
    assert 'SUCCESS' not in report.split('## Route')[0]


def test_runner_retry_disabled_single_attempt(tmp_path, monkeypatch):
    """Requirement 2/4：AAF_WORKBUDDY_RETRY=0 → 单次 attempt，empty 不重试。"""
    monkeypatch.setenv('AAF_WORKBUDDY_RETRY', '0')
    calls, spawns, out, report_path = run_runner(
        monkeypatch, tmp_path, [('output', '', ''), ('output', '**Result: PASS**\nverified', '')]
    )
    assert len(spawns) == 1  # 只跑了一次，没有 retry（即便后续行为会给成功）
    assert calls == ['workbuddy']  # 失败 → Codex 不运行
    result_md = (out / 'workbuddy_result.md').read_text(encoding='utf-8')
    assert result_md.startswith('FRAMEWORK_ERROR')
    assert '1 attempt(s)' in result_md
    assert '## Current Status\nWAITING' in report_path.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# FIX-001 Requirement 22 — Cleanup Failure（confirmed-dead-before-retry）
# ---------------------------------------------------------------------------


def test_22a_cleanup_unconfirmed_no_retry_fail_closed(monkeypatch):
    """22A: attempt1 timeout → taskkill 失败 → kill 失败 → 进程仍存活 → cleanup 未确认。

    Expected（Requirement 3/7/15）：无 attempt 2、child 不被静默注销（registry
    保留 PID）、stage fail closed（WorkBuddyCleanupError + CLEANUP_FAILURE）、
    诊断说明 cleanup 未确认。
    """
    spawned = []
    counter = itertools.count(2000)
    behavior_iter = iter([('timeout',), ('output', 'ok', '')])

    def fake_popen(*args, **kwargs):
        proc = FakeProc(next(counter), behavior_iter,
                        alive_after_kill=True, kill_raises=OSError('kill failed'))
        spawned.append(proc)
        return proc

    monkeypatch.setattr(wb_retry_mod, '_Popen', fake_popen)
    monkeypatch.setattr(wb_retry_mod, '_taskkill', lambda pid, timeout=None: False)
    # budget=1.0 → attempt timeout=min(60,1.0)=1.0；('timeout',) 立即抛 → 清理有 ~1s
    policy = make_policy(max_attempts=2, timeout=60.0, budget=1.0, reserve=0.0)
    with pytest.raises(wb_retry_mod.WorkBuddyCleanupError) as exc:
        wb_retry_mod.run_workbuddy_with_retry(
            ['codebuddy'], {'A': '1'}, 'P', Path('.'), policy
        )
    telemetry = exc.value.telemetry
    try:
        assert len(spawned) == 1  # 无 attempt 2
        assert telemetry['attempt_count'] == 1
        assert telemetry['outcome'] == 'CLEANUP_FAILURE'
        assert telemetry['cleanup_failure_occurred'] is True
        assert telemetry['retry_suppressed_reason'] == (
            'previous child process termination unconfirmed '
            '(child remains registered; no retry)'
        )
        a0 = telemetry['attempts'][0]
        assert a0['cleanup_failure'] is True
        assert a0['cleanup_confirmed'] is False
        assert a0['cleanup_method'] == 'none'
        assert a0['failure_class'] == 'non_retryable'
        assert 'cleanup could not be confirmed' in a0['retry_reason']
        assert spawned[0].pid in wb_retry_mod.active_child_pids()  # 未静默注销
        msg = str(exc.value)
        assert 'cleanup could not be confirmed' in msg  # 显式诊断
        assert 'no retry' in msg
    finally:
        wb_retry_mod._ACTIVE_CHILD_PIDS.discard(spawned[0].pid)  # terminal handling


def test_22b_taskkill_fails_kill_confirms_retry_allowed(monkeypatch):
    """22B: taskkill 返回失败但 fallback kill 确认退出 → cleanup confirmed，retry 可进行。"""
    out, telemetry, spawns = run_retry(
        monkeypatch, [('timeout',), ('output', 'ok', '')], taskkill_result=False
    )
    assert out == 'ok'
    assert telemetry['attempt_count'] == 2
    assert telemetry['outcome'] == 'SUCCESS'
    a0 = telemetry['attempts'][0]
    assert a0['cleanup_failure'] is False
    assert a0['cleanup_confirmed'] is True
    assert a0['cleanup_method'] == 'kill'  # taskkill 失败 → kill 确认
    assert a0['failure_class'] == 'retryable_transient'
    assert spawns[0].killed is True
    assert wb_retry_mod.active_child_pids() == []


def test_22c_reap_failure_after_confirmed_termination_retryable(monkeypatch):
    """22C: 确认终止后 communicate/reap 失败 → 按真实资源安全语义分类。

    进程已确认死亡 → 无并发 child 风险 → retry 允许（retryable_transient）；
    但 cleanup_confirmed=False 如实记录 reap 未确认（evidence，不伪装成功）。
    """
    spawned = []
    counter = itertools.count(3000)
    behavior_iter = iter([('timeout',), ('output', 'ok', '')])

    def fake_popen(*args, **kwargs):
        proc = FakeProc(next(counter), behavior_iter, reap_raises=True)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(wb_retry_mod, '_Popen', fake_popen)
    monkeypatch.setattr(wb_retry_mod, '_taskkill', lambda pid, timeout=None: True)
    out, telemetry = wb_retry_mod.run_workbuddy_with_retry(
        ['codebuddy'], {'A': '1'}, 'P', Path('.'), make_policy()
    )
    assert out == 'ok'
    assert telemetry['attempt_count'] == 2
    assert telemetry['outcome'] == 'SUCCESS'
    a0 = telemetry['attempts'][0]
    assert a0['timed_out'] is True
    assert a0['cleanup_failure'] is False    # 终止已确认 → 非安全失败
    assert a0['cleanup_confirmed'] is False  # reap 未确认 → 如实记录
    assert 'reap unconfirmed' in (a0['cleanup_reason'] or '')
    assert a0['failure_class'] == 'retryable_transient'
    assert spawned[0].returncode == -9  # 已确认死亡
    assert wb_retry_mod.active_child_pids() == []  # 死亡 → 注销合法（无并发风险）


def test_22de_registry_retains_unsafe_child_blocks_next_run(monkeypatch):
    """22D+22E: registry 保留 unsafe child 直到 terminal handling；下一个 run /
    attempt 不能与可能存活的 child 重叠（spawn 前 fail closed）。"""
    spawned = []
    counter = itertools.count(4000)
    behavior_iter = iter([('timeout',), ('output', 'ok', '')])

    def fake_popen(*args, **kwargs):
        proc = FakeProc(next(counter), behavior_iter,
                        alive_after_kill=True, kill_raises=OSError('kill failed'))
        spawned.append(proc)
        return proc

    monkeypatch.setattr(wb_retry_mod, '_Popen', fake_popen)
    monkeypatch.setattr(wb_retry_mod, '_taskkill', lambda pid, timeout=None: False)
    policy = make_policy(max_attempts=2, timeout=60.0, budget=1.0, reserve=0.0)
    with pytest.raises(wb_retry_mod.WorkBuddyCleanupError):
        wb_retry_mod.run_workbuddy_with_retry(
            ['codebuddy'], {'A': '1'}, 'P', Path('.'), policy
        )
    unsafe_pid = spawned[0].pid
    try:
        assert unsafe_pid in wb_retry_mod.active_child_pids()  # 22D：保留 ownership
        # 22E：下一次 run 在 spawn 前被 Registry Gate 拦截（绝不与 unsafe child 并发）
        with pytest.raises(wb_retry_mod.WorkBuddyConcurrencyError):
            wb_retry_mod.run_workbuddy_with_retry(
                ['codebuddy'], {'A': '1'}, 'P', Path('.'), make_policy()
            )
        assert unsafe_pid in wb_retry_mod.active_child_pids()  # 仍然保留
    finally:
        wb_retry_mod._ACTIVE_CHILD_PIDS.discard(unsafe_pid)


# ---------------------------------------------------------------------------
# FIX-001 Requirement 23 — Hard Budget（single absolute stage deadline）
# ---------------------------------------------------------------------------


def test_23a_attempt_cleanup_backoff_share_same_deadline(monkeypatch):
    """23A: attempt timeout + cleanup + backoff 全部消费同一绝对 deadline。

    attempt1 立即 timeout + 清理 + backoff 后，attempt2 的 timeout 从同一
    deadline 派生（被大幅裁剪），attempt3 不再启动（deadline 已到）。
    """
    policy = make_policy(max_attempts=3, timeout=60.0, backoff=0.2, budget=1.0, reserve=0.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(
            monkeypatch,
            [('timeout',), ('sleep_timeout', 60.0), ('timeout',)],
            policy=policy,
        )
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 2  # attempt3 未启动（deadline 已到）
    assert telemetry['outcome'] == 'RETRIES_EXHAUSTED'
    a0, a1 = telemetry['attempts']
    assert a0['timeout_used'] == pytest.approx(1.0, abs=0.05)  # 首次吃满剩余
    assert a1['timeout_used'] < 0.9  # 清理+backoff 消费后，attempt2 timeout 被裁剪
    assert a0['cleanup_confirmed'] is True
    # attempt2 的清理发生在 deadline 恰好耗尽时：终止仍被确认（kill），但 reap
    # 等待被裁剪到 0 剩余（Requirement 12/13）→ cleanup_confirmed=False 如实记录，
    # cleanup_failure=False（进程已死，无并发风险）
    assert a1['cleanup_failure'] is False
    assert a1['cleanup_confirmed'] is False
    assert 'reap unconfirmed' in (a1['cleanup_reason'] or '')
    assert telemetry['retry_suppressed_reason'] is not None
    assert 'deadline' in telemetry['retry_suppressed_reason']
    assert telemetry['stage_total_elapsed_seconds'] <= 1.0 + 0.3  # 硬上限 + 小容差


def test_23b_cleanup_waits_clipped_to_remaining_deadline(monkeypatch):
    """23B: taskkill / grace / reap 等待全部被剩余 deadline 裁剪——绝不使用
    独立全尺寸等待（30s taskkill 不得在 deadline 后继续）。"""
    taskkill_calls = []

    def spy_taskkill(pid, timeout=None):
        taskkill_calls.append((pid, timeout))
        return True

    policy = make_policy(max_attempts=2, timeout=0.3, budget=0.9, reserve=0.0)
    out, telemetry, _ = run_retry(
        monkeypatch, [('timeout',), ('output', 'ok', '')],
        policy=policy, taskkill_result=spy_taskkill,
    )
    assert out == 'ok'
    assert telemetry['attempt_count'] == 2
    assert len(taskkill_calls) >= 1
    t0 = taskkill_calls[0][1]
    assert t0 is not None and 0 < t0 < 30.0  # 被裁剪（< 全尺寸 30s）
    a0 = telemetry['attempts'][0]
    assert a0['cleanup_confirmed'] is True
    assert a0['cleanup_failure'] is False
    assert telemetry['stage_total_elapsed_seconds'] <= 0.9 + 0.25


def test_23c_second_attempt_not_started_insufficient_safe_budget(monkeypatch):
    """23C: 剩余 budget 不足以安全跑完 attempt + 清理 → 不启动第二次 attempt
    （fail closed，retry suppressed 诊断）。"""
    # attempt1 用掉 0.4s（timeout=0.4），剩余 ~0.55 < cleanup_reserve 0.6
    policy = make_policy(max_attempts=2, timeout=60.0, budget=1.0, reserve=0.6)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(monkeypatch, [('sleep_timeout', 60.0), ('output', 'ok', '')], policy=policy)
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 1  # attempt2 未启动
    assert telemetry['outcome'] == 'RETRIES_EXHAUSTED'
    assert 'insufficient safe budget' in telemetry['retry_suppressed_reason']
    assert telemetry['stage_total_elapsed_seconds'] <= 1.0 + 0.25
    # attempt1 timeout 受 reserve 限制：min(60, 1.0-0.6) = 0.4
    assert telemetry['attempts'][0]['timeout_used'] == pytest.approx(0.4, abs=0.05)


def test_23d_stage_elapsed_respects_budget(monkeypatch):
    """23D: reported stage elapsed 尊重配置的 budget（确定性容差内）。"""
    policy = make_policy(max_attempts=3, timeout=60.0, backoff=0.0, budget=0.9, reserve=0.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(
            monkeypatch,
            [('timeout',), ('sleep_timeout', 60.0), ('timeout',)],
            policy=policy,
        )
    telemetry = exc.value.telemetry
    assert telemetry['stage_total_elapsed_seconds'] <= 0.9 + 0.3
    # 成功路径同样有界（budget 足够时正常完成）
    policy_ok = make_policy(max_attempts=2, timeout=60.0, backoff=0.0, budget=3.0)
    out, telemetry_ok, _ = run_retry(
        monkeypatch, [('timeout',), ('output', 'ok', '')], policy=policy_ok
    )
    assert out == 'ok'
    assert telemetry_ok['stage_total_elapsed_seconds'] <= 3.0 + 0.2


def test_23e_cleanup_reserve_limits_first_attempt(monkeypatch):
    """23E: cleanup reserve 防止首次 attempt 吃掉全部 stage budget——
    attempt timeout <= remaining - cleanup_reserve（不因 attempt 耗尽 budget 而
    无安全清理时间）。"""
    # budget=100, reserve=30 → 首次 attempt timeout = min(90, 70) = 70（< 90）
    policy = make_policy(max_attempts=2, timeout=90.0, budget=100.0, reserve=30.0)
    with pytest.raises(wb_retry_mod.WorkBuddyRetriesExhausted) as exc:
        run_retry(monkeypatch, [('timeout',), ('timeout',)], policy=policy)
    telemetry = exc.value.telemetry
    assert telemetry['attempt_count'] == 2
    a0, a1 = telemetry['attempts']
    assert a0['timeout_used'] == pytest.approx(70.0, abs=0.5)
    assert a1['timeout_used'] == pytest.approx(70.0, abs=0.5)
    assert a0['cleanup_confirmed'] is True
    assert a1['cleanup_confirmed'] is True
    # 预留窗口确实存在：timeout + reserve <= budget
    assert a0['timeout_used'] + 30.0 <= 100.0 + 0.5


def test_policy_cleanup_reserve_default_and_env(monkeypatch):
    """FIX-001 Requirement 10/19: cleanup_reserve 默认 60s，env 可覆盖；budget 下限
    至少容纳一次完整 attempt + reserve。"""
    for var in ('AAF_WORKBUDDY_MAX_ATTEMPTS', 'AAF_WORKBUDDY_TIMEOUT',
                'AAF_WORKBUDDY_BACKOFF', 'AAF_WORKBUDDY_STAGE_BUDGET',
                'AAF_WORKBUDDY_CLEANUP_RESERVE'):
        monkeypatch.delenv(var, raising=False)
    p = wb_retry_mod.load_workbuddy_policy()
    assert p.cleanup_reserve == 60.0
    assert p.overall_stage_budget == 2 * 900.0 + 30.0  # 公式不变
    monkeypatch.setenv('AAF_WORKBUDDY_CLEANUP_RESERVE', '15')
    monkeypatch.setenv('AAF_WORKBUDDY_TIMEOUT', '100')
    monkeypatch.setenv('AAF_WORKBUDDY_STAGE_BUDGET', '50')
    p2 = wb_retry_mod.load_workbuddy_policy()
    assert p2.cleanup_reserve == 15.0
    assert p2.overall_stage_budget == 115.0  # max(50, 100+15)


# ---------------------------------------------------------------------------
# FIX-001 Requirement 24 — telemetry extension（cleanup / deadline evidence）
# ---------------------------------------------------------------------------


def test_24_telemetry_cleanup_and_budget_fields(monkeypatch):
    """Requirement 19/24: attempt telemetry 暴露 cleanup_confirmed / cleanup_failure /
    cleanup_method / deadline / budget / actual elapsed / attempt timeout used。"""
    out, telemetry, _ = run_retry(monkeypatch, [('timeout',), ('output', 'ok', '')])
    assert out == 'ok'
    assert telemetry['stage_deadline_monotonic'] is not None
    assert telemetry['stage_total_elapsed_seconds'] >= 0
    assert telemetry['policy']['cleanup_reserve'] == 0.0
    a0 = telemetry['attempts'][0]
    assert a0['cleanup_confirmed'] is True
    assert a0['cleanup_failure'] is False
    assert a0['cleanup_method'] in ('taskkill-tree', 'kill', 'already-exited')
    assert a0['timeout_used'] > 0
    # 成功 attempt（natural-exit）也带 cleanup evidence
    a1 = telemetry['attempts'][1]
    assert a1['cleanup_confirmed'] is True
    assert a1['cleanup_method'] == 'natural-exit'
    assert a1['cleanup_failure'] is False
    json.dumps(telemetry)  # 可序列化（machine artifact）


def test_24_fail_verdict_never_retries_with_cleanup_fields(monkeypatch):
    """Requirement 16/24: 有效业务 FAIL verdict → 不 retry（transport 与业务 authority
    分离）；record 的 cleanup evidence 如实（natural-exit）。"""
    out, telemetry, _ = run_retry(monkeypatch, [('output', 'FAIL: B1 broken', '')])
    assert out == 'FAIL: B1 broken'
    assert telemetry['attempt_count'] == 1
    assert telemetry['retried'] is False
    assert telemetry['cleanup_failure_occurred'] is False
    assert telemetry['attempts'][0]['cleanup_confirmed'] is True
    assert telemetry['attempts'][0]['cleanup_method'] == 'natural-exit'
