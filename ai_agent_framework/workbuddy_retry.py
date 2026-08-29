"""AAF — WorkBuddy Stage Reliability / Bounded Transient Retry（AAF-v0.4-TASK-011）。

Scope（严格执行，不扩大）：
- 只处理 WorkBuddy / CodeBuddy stage 的 **transport execution 层** transient recovery。
- Hermes / Codex stage 默认不重试（本模块只被 WorkBuddy 调用；无通用 orchestration
  redesign）。
- retry 永远复用同一次 invocation（same agent / same current CodeBuddy model &
  default config / same prompt / same workspace / same execution role）——绝不换模型、
  不换 provider、不升级付费层级、不修改用户配置。
- 业务 verdict（WorkBuddy 返回的 PASS / PASS_WITH_WARNING / FAIL）**不是** transport
  failure：一旦获得非空、可用的输出立即停止 retry，verdict 交给 Framework authority
  处理（structured result contract / blocking provenance / verdict parsing 不变）。
- 有界：max_attempts、per-attempt timeout、bounded backoff、overall stage budget。
- fail-closed：retries 用尽 → ``WorkBuddyRetriesExhausted``（runner → FRAMEWORK_ERROR；
  Codex 不运行；任务 WAITING）。
- 进程卫生：timeout → 整棵进程树 kill（Windows taskkill /PID /T /F）+ 有界等待 +
  管道排空（无 orphan / 无 zombie / 无 pipe leak / 无并发 child）。
- **confirmed-dead-before-retry（AAF-v0.4-TASK-011-FIX-001）**：timeout 的 attempt
  只有在 child 终止被**确认**（观察到 poll() 非 None / taskkill 树杀成功）且注册表
  ownership 释放后才允许 retry；终止无法确认 → cleanup failure / fail closed、
  绝不重试、child PID 保持注册（Registry Gate 防任何后续 spawn）。
- **single absolute stage deadline（AAF-v0.4-TASK-011-FIX-001）**：
  ``stage_deadline = stage_start + overall_stage_budget`` 是唯一绝对墙钟上限；
  attempt execution / backoff / taskkill wait / kill grace / communicate reap
  全部从同一 deadline 派生并被其裁剪；attempt timeout 预留 ``cleanup_reserve``
  有界清理窗口，绝不因清理而超出 budget。

Failure classification（只基于真实 CLI evidence，不凭空造字符串规则）：
RETRYABLE_TRANSIENT：
- ``TimeoutExpired``（CLOSURE-003 真实形态：3600s 硬等待）
- exit=0 + stdout 为空（CLOSURE-002 真实形态）
- CodeBuddy 自身 stderr 的 gateway placeholder-only 证据
  （``Empty stream: upstream gateway sent only placeholder chunks without any
    model output (chunks=N, bytes=N)``——CLOSURE-002 真实 stderr）
NON_RETRYABLE（快速失败，不无意义重试）：
- missing executable（MISSING_COMMAND）
- 非零退出且无 transient gateway evidence（unauthenticated / invalid config /
  CLI fatal 等永久性证据）
- spawn / pipe 级 fatal

遥测：每次执行返回完整 attempt telemetry（machine artifact ``workbuddy_attempts.json``
由 runner 持久化；REPORT 只含紧凑摘要）。最终只有单一 canonical workbuddy_result；
attempt logs 是 supporting evidence。
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .subprocess_utils import no_console_kwargs

# ---------------------------------------------------------------------------
# 可测试别名（monkeypatch 只影响本模块引用，不影响全局 subprocess）
# ---------------------------------------------------------------------------
_Popen = subprocess.Popen
_TimeoutExpired = subprocess.TimeoutExpired

# ---------------------------------------------------------------------------
# 默认策略（安全默认值，env 可覆盖；基于本项目已记录的真实 WorkBuddy stage
# timing——成功 stage 实测 ~556s（AAF-v0.4-TASK-010-FIX-001），故 per-attempt
# timeout 默认 900s 留足余量，不再只能依赖统一 3600s 硬等待）
# ---------------------------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 2  # initial + 1 retry
DEFAULT_PER_ATTEMPT_TIMEOUT = 900.0  # 秒（实测成功 stage ~556s）
DEFAULT_BACKOFF_SECONDS = 30.0  # 有界确定性 backoff（不得 tight loop 撞 gateway）
DEFAULT_OVERALL_STAGE_BUDGET = 0.0  # 0 → 按公式计算（见 load_workbuddy_policy）
# 清理预留（TASK-011-FIX-001 Requirement 10）：attempt timeout 不得超过
# remaining - cleanup_reserve，保证 timeout 后仍有界清理窗口（taskkill ≤30s +
# kill grace ≤5s + reap 2×5s + 余量 ≈ 45~50s，默认 60s 安全覆盖）。
DEFAULT_CLEANUP_RESERVE = 60.0

ENV_MAX_ATTEMPTS = "AAF_WORKBUDDY_MAX_ATTEMPTS"
ENV_TIMEOUT = "AAF_WORKBUDDY_TIMEOUT"
ENV_BACKOFF = "AAF_WORKBUDDY_BACKOFF"
ENV_STAGE_BUDGET = "AAF_WORKBUDDY_STAGE_BUDGET"
ENV_CLEANUP_RESERVE = "AAF_WORKBUDDY_CLEANUP_RESERVE"
ENV_DISABLE = "AAF_WORKBUDDY_RETRY"  # 0/false/off → 单次 attempt（无 retry，旧语义）
_DISABLED_VALUES = frozenset({"0", "false", "off", "no", "disable", "disabled"})

# 有界清理参数（TASK-011-FIX-001 Requirement 12/14：全部被 stage deadline 裁剪，
# 无独立全尺寸等待可静默超出 budget；清理自身有界，绝不无限 wait/poll/communicate）
TASKKILL_TIMEOUT = 30.0
KILL_GRACE_SECONDS = 5.0
REAP_COMMUNICATE_TIMEOUT = 5.0
REAP_ATTEMPTS = 2
POLL_INTERVAL = 0.05
MIN_ATTEMPT_TIMEOUT = 0.05  # 低于此值不再启动 attempt（budget 不足，fail closed）

# 已知 transient gateway evidence（CodeBuddy CLI 自身输出；CLOSURE-002 真实 stderr）
_PLACEHOLDER_GATEWAY_RES = (
    re.compile(r"(?i)empty\s+stream"),
    re.compile(r"(?i)placeholder\s+chunks?"),
    re.compile(r"(?i)no\s+model\s+output"),
)

FAILURE_CLASS_RETRYABLE = "retryable_transient"
FAILURE_CLASS_NON_RETRYABLE = "non_retryable"

OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
OUTCOME_PERMANENT_FAILURE = "PERMANENT_FAILURE"
OUTCOME_CLEANUP_FAILURE = "CLEANUP_FAILURE"  # FIX-001：child 终止未确认 → 安全失败


class FailureClass(Enum):
    RETRYABLE_TRANSIENT = FAILURE_CLASS_RETRYABLE
    NON_RETRYABLE = FAILURE_CLASS_NON_RETRYABLE


@dataclass(frozen=True)
class WorkBuddyRetryPolicy:
    """有界 retry 策略（配置 / 可测试）。"""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    per_attempt_timeout: float = DEFAULT_PER_ATTEMPT_TIMEOUT
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    overall_stage_budget: float = DEFAULT_OVERALL_STAGE_BUDGET
    # FIX-001 Requirement 10：attempt timeout 从 remaining 中预留的有界清理窗口
    # （attempt_timeout <= remaining - cleanup_reserve）
    cleanup_reserve: float = DEFAULT_CLEANUP_RESERVE


@dataclass(frozen=True)
class CleanupResult:
    """进程清理的结构化结果（Requirement 4：callers 必须基于此结果行动）。

    - ``terminated_confirmed``: 进程不再存活被**观察到**（poll() 非 None）——
      不是“kill() 被调用”，而是终止被确认（Requirement 5）。
    - ``reaped_confirmed``: 管道已排空 / communicate 已返回（资源已回收）。
    - ``method``: 确认途径（already-exited / taskkill-tree / kill / none）。
    - ``failure_reason``: 未确认时的人类可读原因（否则 None）。
    """

    terminated_confirmed: bool
    reaped_confirmed: bool
    method: str
    failure_reason: str | None = None


@dataclass
class AttemptRecord:
    """单次 attempt 的完整 evidence（machine artifact 逐条记录）。"""

    attempt_index: int
    status: str  # SUCCESS / FAILED
    failure_class: str | None = None  # retryable_transient / non_retryable
    retry_reason: str | None = None
    timed_out: bool = False
    stdout_empty: bool = False
    exit_code: int | None = None
    timeout_used: float = 0.0
    elapsed_seconds: float = 0.0
    stderr_tail: str = ""
    # FIX-001 Requirement 19：清理证据（normal 退出 → cleanup_confirmed=True /
    # method=natural-exit；timeout 清理 → 按 CleanupResult 填）
    cleanup_confirmed: bool | None = None
    cleanup_failure: bool = False
    cleanup_method: str | None = None
    cleanup_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "attempt_index": self.attempt_index,
            "status": self.status,
            "failure_class": self.failure_class,
            "retry_reason": self.retry_reason,
            "timed_out": self.timed_out,
            "stdout_empty": self.stdout_empty,
            "exit_code": self.exit_code,
            "timeout_used": round(float(self.timeout_used), 3),
            "elapsed_seconds": round(float(self.elapsed_seconds), 3),
            "stderr_tail": self.stderr_tail,
            "cleanup_confirmed": self.cleanup_confirmed,
            "cleanup_failure": self.cleanup_failure,
            "cleanup_method": self.cleanup_method,
            "cleanup_reason": self.cleanup_reason,
        }


@dataclass
class AttemptOutcome:
    output: str | None
    record: AttemptRecord


class WorkBuddyStageError(RuntimeError):
    """retry 层终端错误基类；携带完整 telemetry（runner 持久化为 machine artifact）。"""

    def __init__(self, message: str, telemetry: dict | None = None):
        super().__init__(message)
        self.telemetry: dict = telemetry or {}


class WorkBuddyPermanentError(WorkBuddyStageError):
    """NON_RETRYABLE：快速失败，不无意义重试（missing exe / auth-config 永久错误等）。"""


class WorkBuddyRetriesExhausted(WorkBuddyStageError):
    """retryable failures 用尽全部有界 attempt → fail closed。"""


class WorkBuddyConcurrencyError(WorkBuddyStageError):
    """内部不变量违规：spawn 前仍有遗留 active child（fail closed）。"""


class WorkBuddyCleanupError(WorkBuddyStageError):
    """清理安全失败（FIX-001 Requirement 3）：child 终止未能确认 → fail closed、
    绝不重试、child PID 保持注册（不得降级为普通 TimeoutExpired 后重试）。"""


# ---------------------------------------------------------------------------
# 并发/孤儿防护（module-level registry；单线程 runner 内安全）
# ---------------------------------------------------------------------------
_ACTIVE_CHILD_PIDS: set[int] = set()
_CHILD_LOCK = threading.Lock()


def active_child_pids() -> list[int]:
    """当前已注册、尚未结束的 WorkBuddy child pid 列表（调试 / 测试用）。"""
    with _CHILD_LOCK:
        return sorted(_ACTIVE_CHILD_PIDS)


def _assert_no_active_children() -> None:
    """spawn 前不变量：上一 attempt 的 child 必须已结束并注销（无并发 / 无 orphan）。"""
    with _CHILD_LOCK:
        stale = sorted(_ACTIVE_CHILD_PIDS)
    if stale:
        raise WorkBuddyConcurrencyError(
            "active WorkBuddy child(ren) still registered before spawn: "
            f"{stale}（并发/遗留 child 不变量违规，fail closed）"
        )


def _register_child(pid: int) -> None:
    with _CHILD_LOCK:
        _ACTIVE_CHILD_PIDS.add(pid)


def _unregister_child(pid: int) -> None:
    with _CHILD_LOCK:
        _ACTIVE_CHILD_PIDS.discard(pid)


# ---------------------------------------------------------------------------
# Failure classification（只基于实际 CLI evidence）
# ---------------------------------------------------------------------------


def _is_placeholder_gateway(stderr: str) -> bool:
    """CodeBuddy 自身 gateway placeholder-only 证据（CLOSURE-002 真实 stderr 形态）。"""
    return bool(stderr) and any(p.search(stderr) for p in _PLACEHOLDER_GATEWAY_RES)


def classify_failure(
    *, timed_out: bool, returncode: int | None, stdout: str, stderr: str
) -> tuple[FailureClass, str]:
    """把一次失败 attempt 分类为 retryable transient / non-retryable。

    规则只基于真实 incident evidence，不得凭空造字符串规则：
    - TimeoutExpired（CLOSURE-003）→ retryable
    - exit=0 + 空 stdout（CLOSURE-002）→ retryable
    - 任何含 gateway placeholder-only evidence 的 stderr → retryable
    - 其余（非零退出且无 transient evidence：unauthenticated / invalid config /
      CLI fatal 等永久性）→ non_retryable
    """
    if timed_out:
        return FailureClass.RETRYABLE_TRANSIENT, "TimeoutExpired"
    if returncode == 0 and not (stdout or "").strip():
        if _is_placeholder_gateway(stderr):
            return (
                FailureClass.RETRYABLE_TRANSIENT,
                "empty output (exit=0); upstream gateway placeholder-only",
            )
        return FailureClass.RETRYABLE_TRANSIENT, "empty output (exit=0)"
    if _is_placeholder_gateway(stderr):
        return FailureClass.RETRYABLE_TRANSIENT, "upstream gateway placeholder-only output"
    return FailureClass.NON_RETRYABLE, f"exit={returncode}"


# ---------------------------------------------------------------------------
# 策略加载（env 可配置；非法值回退默认；绝不无限重试）
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_workbuddy_policy() -> WorkBuddyRetryPolicy:
    """读取 env 配置的 WorkBuddy retry 策略（安全默认值；可测试）。

    - ``AAF_WORKBUDDY_RETRY=0`` → max_attempts 强制为 1（无自动 retry，旧语义）。
    - ``AAF_WORKBUDDY_STAGE_BUDGET`` 未配置/<=0 → 按公式
      ``max_attempts*per_attempt_timeout + (max_attempts-1)*backoff`` 计算，
      保证默认策略下 budget 恒 >= 全部 attempts + backoff 的数学总和；
      且 budget 至少容纳一次完整 attempt + cleanup reserve（FIX-001 Req 10）。
    """
    max_attempts = max(1, _env_int(ENV_MAX_ATTEMPTS, DEFAULT_MAX_ATTEMPTS))
    per_attempt_timeout = max(1.0, _env_float(ENV_TIMEOUT, DEFAULT_PER_ATTEMPT_TIMEOUT))
    backoff = max(0.0, _env_float(ENV_BACKOFF, DEFAULT_BACKOFF_SECONDS))
    cleanup_reserve = max(0.0, _env_float(ENV_CLEANUP_RESERVE, DEFAULT_CLEANUP_RESERVE))
    budget = _env_float(ENV_STAGE_BUDGET, DEFAULT_OVERALL_STAGE_BUDGET)
    if budget <= 0:
        budget = max_attempts * per_attempt_timeout + (max_attempts - 1) * backoff
    budget = max(budget, per_attempt_timeout + cleanup_reserve)  # 至少一次完整 attempt + 清理窗口
    if os.environ.get(ENV_DISABLE, "").strip().lower() in _DISABLED_VALUES:
        max_attempts = 1
    return WorkBuddyRetryPolicy(
        max_attempts=max_attempts,
        per_attempt_timeout=per_attempt_timeout,
        backoff_seconds=backoff,
        overall_stage_budget=budget,
        cleanup_reserve=cleanup_reserve,
    )


# ---------------------------------------------------------------------------
# 进程清理（Windows 行为；有界；全部被 stage deadline 裁剪；返回结构化结果）
# ---------------------------------------------------------------------------


def _remaining_until(deadline: float | None) -> float | None:
    """从绝对 deadline 到现在的剩余秒数（None → 无 deadline 限制）。"""
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def _clipped_timeout(deadline: float | None, nominal: float) -> float:
    """把有界等待的 nominal 时长裁剪到剩余 deadline（Requirement 12）。"""
    remaining = _remaining_until(deadline)
    if remaining is None:
        return nominal
    return min(nominal, remaining)


def _taskkill(pid: int, timeout: float = TASKKILL_TIMEOUT) -> bool:
    """Windows: ``taskkill /PID <pid> /T /F``（整棵进程树）。失败 → False。

    timeout 由调用方裁剪到剩余 stage deadline（绝不独立全尺寸等待）。
    """
    try:
        r = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=timeout,
            **no_console_kwargs(),
        )
        return r.returncode == 0
    except Exception:
        return False


def _kill_process_tree(proc, deadline: float | None) -> tuple[bool, str]:
    """确保 child（Windows 下为整棵进程树）已死，并**确认**终止。

    返回 (terminated_confirmed, method)：
    - ``terminated_confirmed=True`` 仅当终止被**观察到**（final liveness check：
      ``proc.poll() is not None``），不是“kill() 被调用”就算成功（Requirement 5）。
    - Windows 优先 ``taskkill /PID /T /F`` 整树杀（Requirement 6 保留；
      树级证据 = taskkill 成功 + 顶层 poll 观察到终止），随后 kill() 兜底。
    - kill grace 轮询被剩余 deadline 裁剪（Requirement 9/12）；清理自身有界
      （Requirement 14：无无限 poll 循环）。
    """
    if proc.poll() is not None:
        return True, "already-exited"
    if os.name == "nt":
        taskkill_timeout = _clipped_timeout(deadline, TASKKILL_TIMEOUT)
        if taskkill_timeout > 0 and _taskkill(proc.pid, timeout=taskkill_timeout):
            # taskkill /T /F 树杀返回成功 + 顶层 poll 观察到终止 = 最强可用证据
            if proc.poll() is not None:
                return True, "taskkill-tree"
    if proc.poll() is not None:
        return True, "already-exited"
    try:
        proc.kill()
    except Exception:
        pass
    grace = _clipped_timeout(deadline, KILL_GRACE_SECONDS)
    poll_deadline = time.monotonic() + grace
    while time.monotonic() < poll_deadline:
        if proc.poll() is not None:
            return True, "kill"
        time.sleep(POLL_INTERVAL)
    # grace 耗尽：最后再尝试一次直接 kill，然后必须观察到终止
    try:
        proc.kill()
    except Exception:
        pass
    if proc.poll() is not None:
        return True, "kill"
    return False, "none"


def _terminate_and_reap(proc, deadline: float | None) -> tuple[str, str, CleanupResult]:
    """kill 进程树 + 确认终止 + 排空 stdin/stdout/stderr 管道 + reap。

    返回 (stdout, stderr, CleanupResult)。绝不抛出（timeout 清理路径不得掩盖
    原始失败）。语义（FIX-001 Requirement 1/3/4/12）：
    - 终止被确认 → 有界排空管道（communicate 裁剪到剩余 deadline）；reap 失败
      如实记录 ``reaped_confirmed=False``（进程已死，无并发风险，如实分类）。
    - 终止**未**确认 → ``terminated_confirmed=False`` + failure_reason；
      callers 必须 fail closed（不得降级为普通 TimeoutExpired 后重试）。
    """
    terminated, method = _kill_process_tree(proc, deadline)
    stdout, stderr = "", ""
    reaped = False
    failure_reason: str | None = None
    if terminated:
        for _ in range(REAP_ATTEMPTS):
            comm_timeout = _clipped_timeout(deadline, REAP_COMMUNICATE_TIMEOUT)
            if comm_timeout <= 0:
                break
            try:
                stdout, stderr = proc.communicate(timeout=comm_timeout)
                reaped = True
                break
            except Exception:
                time.sleep(POLL_INTERVAL)
                try:
                    proc.kill()
                except Exception:
                    pass
        if not reaped:
            failure_reason = (
                "process termination confirmed but pipes could not be drained "
                "(reap unconfirmed; no concurrency risk)"
            )
    else:
        failure_reason = (
            "process termination could not be confirmed after taskkill/kill "
            "sequence (child may still be alive; fail closed, no retry)"
        )
    return stdout, stderr, CleanupResult(
        terminated_confirmed=terminated,
        reaped_confirmed=reaped,
        method=method,
        failure_reason=failure_reason,
    )


# ---------------------------------------------------------------------------
# 单次 attempt（Popen 显式 timeout 处理，保证可清理）
# ---------------------------------------------------------------------------


def _stderr_tail(stderr: str, limit: int = 600) -> str:
    lines = (stderr or "").strip().splitlines()
    return ("\n".join(lines[-5:]))[-limit:]


def _run_single_attempt(
    args: list[str],
    env: dict,
    stdin_data: str | None,
    workspace: Path,
    timeout: float,
    deadline: float | None = None,
) -> AttemptOutcome:
    """执行一次 WorkBuddy invocation（Popen；显式 timeout + 确认式清理）。

    FIX-001（Requirement 1/2/3/5）：
    - child 一旦 spawn 即注册；**只有**终止被确认后才注销（confirmed-dead 才释放
      ownership；never ``alive child + absent registry + retry permitted``）。
    - timeout / I/O 失败路径执行确认式清理（``_terminate_and_reap`` 返回
      CleanupResult）：terminated_confirmed → 注销 + 正常分类（TimeoutExpired 等）；
      **未确认 → cleanup_failure=True、PID 保持注册**（Registry Gate 保留），
      分类为 NON_RETRYABLE 安全失败——绝不降级为普通 TimeoutExpired 后重试。
    - 清理等待（taskkill / grace / communicate）全部由 deadline 裁剪。

    返回 AttemptOutcome(output, record)：成功 → output 非空、record.status=SUCCESS；
    失败 → output=None、record 携带 failure_class / retry_reason / cleanup evidence。
    """
    start = time.monotonic()
    proc = None
    stdout = ""
    stderr = ""
    timed_out = False
    spawn_error: str | None = None
    cleanup: CleanupResult | None = None
    try:
        _assert_no_active_children()
        try:
            proc = _Popen(
                args,
                cwd=str(workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **no_console_kwargs(),
            )
        except (OSError, ValueError) as exc:
            spawn_error = f"process start failed: {type(exc).__name__}: {exc}"
            proc = None
        if proc is not None:
            _register_child(proc.pid)
            try:
                stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
            except _TimeoutExpired:
                timed_out = True
                stdout, stderr, cleanup = _terminate_and_reap(proc, deadline)
            except (OSError, ValueError) as exc:
                spawn_error = f"process I/O failed: {type(exc).__name__}: {exc}"
                stdout, stderr, cleanup = _terminate_and_reap(proc, deadline)
            # 注册表所有权（Requirement 2）：confirmed-dead 才注销；未确认 → 保持注册
            if cleanup is not None:
                if cleanup.terminated_confirmed:
                    _unregister_child(proc.pid)
                # else: 保持注册 —— 绝不能出现 alive child + 无 registry + retry
            else:
                # communicate 正常返回 → 进程已退出（returncode 非 None）且已 reap
                _unregister_child(proc.pid)
    finally:
        # 注意：这里**不**无条件注销（FIX-001 Requirement 2）——未确认终止的
        # child 必须保留在 registry，直到 terminal cleanup-failure 状态被处理。
        pass

    elapsed = round(time.monotonic() - start, 3)
    exit_code = proc.returncode if proc is not None else None
    stderr_tail = _stderr_tail(stderr)

    exited_naturally = proc is not None and cleanup is None and exit_code is not None
    if cleanup is not None:
        cleanup_confirmed = cleanup.terminated_confirmed and cleanup.reaped_confirmed
        cleanup_failure = not cleanup.terminated_confirmed
        cleanup_method = cleanup.method
        cleanup_reason = cleanup.failure_reason
    elif exited_naturally:
        cleanup_confirmed, cleanup_failure, cleanup_method, cleanup_reason = (
            True, False, "natural-exit", None,
        )
    else:
        cleanup_confirmed, cleanup_failure, cleanup_method, cleanup_reason = (
            None, False, None, None,
        )

    if spawn_error:
        cls, reason, stdout_empty_flag = (
            FailureClass.NON_RETRYABLE, spawn_error, False,
        )
    elif timed_out and cleanup_failure:
        # FIX-001 Requirement 3：清理不确定性不得降级为普通 TimeoutExpired
        cls, reason, stdout_empty_flag = (
            FailureClass.NON_RETRYABLE,
            f"cleanup could not be confirmed: {cleanup_reason}",
            False,
        )
    elif timed_out:
        cls, reason, stdout_empty_flag = (
            FailureClass.RETRYABLE_TRANSIENT, "TimeoutExpired", False,
        )
    elif exit_code != 0:
        cls, reason = classify_failure(
            timed_out=False, returncode=exit_code, stdout=stdout, stderr=stderr
        )
        stdout_empty_flag = not (stdout or "").strip()
    elif not (stdout or "").strip():
        cls, reason = classify_failure(
            timed_out=False, returncode=0, stdout="", stderr=stderr
        )
        stdout_empty_flag = True
    else:
        cls, reason, stdout_empty_flag = None, None, False

    record = AttemptRecord(
        attempt_index=0,  # orchestrator 回填
        status="FAILED" if cls is not None else "SUCCESS",
        failure_class=cls.value if cls is not None else None,
        retry_reason=reason,
        timed_out=timed_out,
        stdout_empty=stdout_empty_flag,
        exit_code=exit_code,
        timeout_used=round(float(timeout), 3),
        elapsed_seconds=elapsed,
        stderr_tail=stderr_tail,
        cleanup_confirmed=cleanup_confirmed,
        cleanup_failure=cleanup_failure,
        cleanup_method=cleanup_method,
        cleanup_reason=cleanup_reason,
    )
    return AttemptOutcome(stdout if cls is None else None, record)


# ---------------------------------------------------------------------------
# 有界 retry 编排（initial + bounded retries；绝不无限重试）
# ---------------------------------------------------------------------------


def _build_telemetry(
    policy: WorkBuddyRetryPolicy,
    attempts: list[AttemptRecord],
    outcome: str,
    last_failure: AttemptRecord | None,
    timed_out_occurred: bool,
    empty_occurred: bool,
    retry_reasons: list[str],
    stage_elapsed: float,
    stage_deadline: float | None = None,
    cleanup_failure_occurred: bool = False,
    retry_suppressed_reason: str | None = None,
) -> dict:
    return {
        "agent": "workbuddy",
        "policy": {
            "max_attempts": policy.max_attempts,
            "per_attempt_timeout": round(float(policy.per_attempt_timeout), 3),
            "backoff_seconds": round(float(policy.backoff_seconds), 3),
            "overall_stage_budget": round(float(policy.overall_stage_budget), 3),
            "cleanup_reserve": round(float(policy.cleanup_reserve), 3),
        },
        "attempt_count": len(attempts),
        "retried": len(attempts) > 1,
        "outcome": outcome,
        # FIX-001 Requirement 9/19：单一绝对 stage deadline（monotonic）+ 实际墙钟
        "stage_deadline_monotonic": (
            round(float(stage_deadline), 3) if stage_deadline is not None else None
        ),
        "stage_total_elapsed_seconds": round(float(stage_elapsed), 3),
        "timeout_occurred": timed_out_occurred,
        "empty_occurred": empty_occurred,
        "cleanup_failure_occurred": cleanup_failure_occurred,
        "retry_suppressed_reason": retry_suppressed_reason,
        "retry_reasons": retry_reasons,
        "last_failure": last_failure.to_dict() if last_failure is not None else None,
        "attempts": [a.to_dict() for a in attempts],
    }


def _render_failure_message(telemetry: dict) -> str:
    """REPORT/result 的紧凑失败历史（总 attempts / last failure / retry reasons /
    elapsed / timeout & empty-output 是否发生 / cleanup failure）——不得只给
    FRAMEWORK_ERROR 丢历史。"""
    policy = telemetry.get("policy") or {}
    lines = [
        f'WorkBuddy stage {telemetry.get("outcome", "FAILED")} after '
        f'{telemetry.get("attempt_count", 0)} attempt(s) '
        f'(stage total elapsed {telemetry.get("stage_total_elapsed_seconds", 0.0):.1f}s; '
        f'per-attempt timeout {policy.get("per_attempt_timeout", 0.0):.0f}s; '
        f'overall stage budget {policy.get("overall_stage_budget", 0.0):.0f}s)'
    ]
    for a in telemetry.get("attempts", []):
        lines.append(
            f'- attempt {a.get("attempt_index")}: {a.get("status")} '
            f'class={a.get("failure_class")} reason={a.get("retry_reason")} '
            f'timed_out={a.get("timed_out")} stdout_empty={a.get("stdout_empty")} '
            f'cleanup_confirmed={a.get("cleanup_confirmed")} '
            f'cleanup_failure={a.get("cleanup_failure")} '
            f'exit={a.get("exit_code")} elapsed={a.get("elapsed_seconds", 0.0):.1f}s'
        )
    lf = telemetry.get("last_failure")
    if lf:
        lines.append(f'last failure: {lf.get("retry_reason")}')
    lines.append(f'timeout occurred: {"yes" if telemetry.get("timeout_occurred") else "no"}')
    lines.append(f'empty-output occurred: {"yes" if telemetry.get("empty_occurred") else "no"}')
    if telemetry.get("cleanup_failure_occurred"):
        lines.append(
            "cleanup failure: previous child termination could not be confirmed "
            "(no retry; fail closed)"
        )
    if telemetry.get("retry_suppressed_reason"):
        lines.append(f'retry suppressed: {telemetry["retry_suppressed_reason"]}')
    if lf and lf.get("stderr_tail"):
        lines.append(f"last stderr tail: {lf['stderr_tail'][-300:]}")
    return "\n".join(lines)


def permanent_stage_error(message: str, retry_reason: str) -> WorkBuddyPermanentError:
    """invocation 层永久失败（如 missing executable）的带 telemetry 错误。"""
    telemetry = {
        "agent": "workbuddy",
        "policy": None,
        "attempt_count": 0,
        "retried": False,
        "outcome": OUTCOME_PERMANENT_FAILURE,
        "stage_deadline_monotonic": None,
        "stage_total_elapsed_seconds": 0.0,
        "timeout_occurred": False,
        "empty_occurred": False,
        "cleanup_failure_occurred": False,
        "retry_suppressed_reason": None,
        "retry_reasons": [],
        "last_failure": {
            "attempt_index": 0,
            "status": "FAILED",
            "failure_class": FAILURE_CLASS_NON_RETRYABLE,
            "retry_reason": retry_reason,
            "timed_out": False,
            "stdout_empty": False,
            "exit_code": None,
            "timeout_used": 0.0,
            "elapsed_seconds": 0.0,
            "stderr_tail": "",
            "cleanup_confirmed": None,
            "cleanup_failure": False,
            "cleanup_method": None,
            "cleanup_reason": None,
        },
        "attempts": [],
    }
    return WorkBuddyPermanentError(message, telemetry)


def run_workbuddy_with_retry(
    args: list[str],
    env: dict,
    stdin_data: str | None,
    workspace: Path,
    policy: WorkBuddyRetryPolicy | None = None,
) -> tuple[str, dict]:
    """WorkBuddy stage 有界 retry 执行（TASK-011 核心）。

    返回 ``(output, telemetry)``：
    - 有效输出（非空、可解析/可用）一旦出现立即返回，后续 attempt 绝不执行；
      业务 verdict（哪怕 FAIL）不是 transport failure，不触发 retry。
    - retryable failures 在 max_attempts 内自动重试（同一 invocation、有界 backoff、
      per-attempt timeout、整体 stage budget 硬上限）。
    - NON_RETRYABLE → ``WorkBuddyPermanentError``（快速失败）。
    - retries 用尽 → ``WorkBuddyRetriesExhausted``（fail closed；telemetry 完整）。
    """
    policy = policy or load_workbuddy_policy()
    stage_start = time.monotonic()
    # FIX-001 Requirement 9/11：单一绝对 stage deadline——attempt / backoff /
    # cleanup（taskkill / grace / reap）全部从同一 deadline 派生并被其裁剪。
    stage_deadline = stage_start + policy.overall_stage_budget
    attempts: list[AttemptRecord] = []
    last_failure: AttemptRecord | None = None
    timed_out_occurred = False
    empty_occurred = False
    retry_reasons: list[str] = []
    cleanup_failure_occurred = False
    retry_suppressed_reason: str | None = None

    def telemetry(outcome: str, last: AttemptRecord | None) -> dict:
        return _build_telemetry(
            policy, attempts, outcome, last,
            timed_out_occurred, empty_occurred, retry_reasons,
            time.monotonic() - stage_start, stage_deadline,
            cleanup_failure_occurred, retry_suppressed_reason,
        )

    for attempt_index in range(1, policy.max_attempts + 1):
        now = time.monotonic()
        if now >= stage_deadline:
            if not retry_suppressed_reason:
                retry_suppressed_reason = "stage deadline reached"
            break
        remaining = stage_deadline - now
        if attempt_index > 1:
            # 有界确定性 backoff（不 tight loop 撞 gateway）；sleep 不超出剩余 budget
            if policy.backoff_seconds > 0:
                backoff = min(policy.backoff_seconds, max(0.0, remaining))
                if backoff > 0:
                    time.sleep(backoff)
                remaining = max(0.0, stage_deadline - time.monotonic())
        # FIX-001 Requirement 10：attempt timeout 不得超过 remaining - cleanup_reserve，
        # 保证 timeout 后仍有有界清理窗口（绝不因清理超出 budget）。
        attempt_timeout = max(
            0.0, min(policy.per_attempt_timeout, remaining - policy.cleanup_reserve)
        )
        if attempt_timeout <= MIN_ATTEMPT_TIMEOUT:
            # Requirement 13/23C：剩余 budget 不足以安全跑完一次 attempt + 清理 → 不再启动
            if not retry_suppressed_reason:
                retry_suppressed_reason = (
                    f"insufficient safe budget for another attempt "
                    f"(remaining {remaining:.1f}s <= cleanup reserve "
                    f"{policy.cleanup_reserve:.1f}s)"
                )
            break
        try:
            outcome = _run_single_attempt(
                args, env, stdin_data, workspace, attempt_timeout,
                deadline=stage_deadline,
            )
        except WorkBuddyConcurrencyError as exc:
            raise WorkBuddyConcurrencyError(
                str(exc),
                telemetry(OUTCOME_PERMANENT_FAILURE, last_failure),
            ) from exc
        record = outcome.record
        record.attempt_index = attempt_index
        attempts.append(record)
        if record.status == "SUCCESS":
            # 有效输出停止 retry（含业务 FAIL verdict——verdict 归 Framework authority）
            return outcome.output, telemetry(OUTCOME_SUCCESS, last_failure)
        last_failure = record
        if record.cleanup_failure:
            # FIX-001 Requirement 3/7/13：清理未确认 → cleanup failure / fail closed；
            # 绝不启动下一个 attempt；child PID 保持注册（Requirement 15）。
            cleanup_failure_occurred = True
            if not retry_suppressed_reason:
                retry_suppressed_reason = (
                    "previous child process termination unconfirmed "
                    "(child remains registered; no retry)"
                )
            raise WorkBuddyCleanupError(
                _render_failure_message(telemetry(OUTCOME_CLEANUP_FAILURE, record)),
                telemetry(OUTCOME_CLEANUP_FAILURE, record),
            )
        if record.failure_class == FailureClass.RETRYABLE_TRANSIENT.value:
            if record.retry_reason:
                retry_reasons.append(record.retry_reason)
            if record.timed_out:
                timed_out_occurred = True
            if record.stdout_empty:
                empty_occurred = True
            continue
        # NON_RETRYABLE：快速失败，不无意义重试
        raise WorkBuddyPermanentError(
            _render_failure_message(telemetry(OUTCOME_PERMANENT_FAILURE, record)),
            telemetry(OUTCOME_PERMANENT_FAILURE, record),
        )

    # retryable failures 用尽（bounded）/ budget 不足 → fail closed
    raise WorkBuddyRetriesExhausted(
        _render_failure_message(telemetry(OUTCOME_RETRIES_EXHAUSTED, last_failure)),
        telemetry(OUTCOME_RETRIES_EXHAUSTED, last_failure),
    )
