"""AAF — v0.5 Cost Stop-Loss shared vocabulary & evidence helpers（AAF-v0.5-COST-STOP-LOSS-001）。

Scope（严格执行，不扩大）：
- 纯常量 / 纯函数模块（零 I/O、零 subprocess、零 framework import）——只定义
  机器可读 stop-loss 词汇、rate-limit/quota 证据识别、per-attempt timeout 策略
  解析与 terminal-reason 分类规则。执行方（adapters / workbuddy_retry / runner）
  各自消费本模块，不做任何进程/调度/看门狗编排。
- 不新增 token-budget / billing engine（无可靠 provider token telemetry 时不猜 token）。
- 不修改 FREE/PAID routing semantics；不实施 PH-2 / PH-3。
- 分类只基于真实 CLI evidence（429 / rate limit / quota / empty-stream 文案），
  不凭空造字符串规则；无证据 → 不声称（None）。

背景（Cost Reality Audit, .aaf/AAF-v0.5-COST-EFFICIENCY-ROUTING-REALITY-AUDIT-001）：
- Hermes stage 曾出现 ~3600.89s subprocess 硬等待（TimeoutExpired，无进度烧 token）。
- WorkBuddy 曾出现长等待 / retry / 429 / empty-output；429 此前仅被归类为
  "empty output (exit=0)"，非限频感知，重试未等到 reset → 徒劳烧 budget。
- 原则：能免费优先；速度慢可接受，但**不允许无进展长期烧 token**；stop-loss 后
  fail closed + 保留工作产物 + 允许 RESUME（本模块不实现 resume——那是 runner/
  lifecycle 语义）。
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import time

# ---------------------------------------------------------------------------
# Machine-readable terminal stop reasons（Requirement 7 词汇表）
# ---------------------------------------------------------------------------
STOP_REASON_ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
STOP_REASON_RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
STOP_REASON_NO_PROGRESS = "NO_PROGRESS"
STOP_REASON_RATE_LIMIT = "RATE_LIMIT"
STOP_REASON_QUOTA = "QUOTA"
STOP_REASON_PROVIDER_FAILURE = "PROVIDER_FAILURE"
STOP_REASON_TOOL_OR_TEST_STILL_ACTIVE = "TOOL_OR_TEST_STILL_ACTIVE"
# v0.5-COST-STOP-LOSS-001-FIX-001：共享 Hermes stage deadline 耗尽/低于安全
# 下限 → 不再发起任何（FREE/PAID）fallback invocation，stage fail closed。
STOP_REASON_STAGE_BUDGET_EXHAUSTED = "STAGE_BUDGET_EXHAUSTED"

TERMINAL_STOP_REASONS = (
    STOP_REASON_ATTEMPT_TIMEOUT,
    STOP_REASON_RETRIES_EXHAUSTED,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_RATE_LIMIT,
    STOP_REASON_QUOTA,
    STOP_REASON_PROVIDER_FAILURE,
    STOP_REASON_TOOL_OR_TEST_STILL_ACTIVE,
    STOP_REASON_STAGE_BUDGET_EXHAUSTED,
)

STOP_LOSS_ARTIFACT = "stop_loss.json"

# ---------------------------------------------------------------------------
# Per-attempt bounded timeout 策略（Hermes / Codex；WorkBuddy 已有 AAF_WORKBUDDY_*）
# ---------------------------------------------------------------------------
ENV_HERMES_ATTEMPT_TIMEOUT = "AAF_HERMES_ATTEMPT_TIMEOUT"
ENV_CODEX_ATTEMPT_TIMEOUT = "AAF_CODEX_ATTEMPT_TIMEOUT"

# Hermes 默认 per-attempt 上限（无 env、无 Risk 时）。evidence：recon 实测成功
# Hermes stage p90≈1164s / max≈1886s（113 个成功阶段），3600s 级别只出现在
# 无进度死 run。2400s 保留 100% 已观测成功样本并留 ~27% 余量。
DEFAULT_HERMES_ATTEMPT_TIMEOUT = 2400.0
# Codex 默认 per-attempt 上限。evidence：71 个成功 review stage max≈224s → 600s
# （2.7x 余量）。Codex review 不跑 executor 级 tool/test 长任务。
DEFAULT_CODEX_ATTEMPT_TIMEOUT = 600.0
# 无 Risk 字段任务的保守默认（evidence：29 个无 Risk 成功 stage max≈1370s）。
DEFAULT_HERMES_TIMEOUT_NO_RISK = 1800.0
# Risk 分级默认（evidence：按 Risk 分组的成功 Hermes stage 最大值——
# HIGH 1886s / MEDIUM 891s / LOW 926s / NONE 1370s；CRITICAL 无样本，取 HIGH 值）。
HERMES_RISK_TIER_TIMEOUT: dict[str | None, float] = {
    "CRITICAL": 2400.0,
    "HIGH": 2400.0,
    "MEDIUM": 1500.0,
    "LOW": 1200.0,
    None: DEFAULT_HERMES_TIMEOUT_NO_RISK,
}
# 未知/非法 risk（validation 已 fail-closed，此处防御）→ 无 Risk 保守值
UNKNOWN_RISK_TIMEOUT = DEFAULT_HERMES_TIMEOUT_NO_RISK


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def resolve_agent_attempt_timeout(agent: str, risk_class: str | None = None,
                                  env=None) -> float:
    """Hermes/Codex per-attempt timeout（秒）——env override 优先，否则分级默认。

    - hermes：AAF_HERMES_ATTEMPT_TIMEOUT（operator override）→ Risk 分级默认。
    - codex：AAF_CODEX_ATTEMPT_TIMEOUT → 600s（review 无长 tool 任务）。
    - workbuddy：返回默认上限（不消费——retry 层用 AAF_WORKBUDDY_*；此处仅供
      调用方统一接口，绝不被 subprocess.run 使用）。
    本函数从不把 timeout 调"短到会误杀合法长任务"——默认值全部 ≥ 对应 risk 档
    已观测成功 stage 的 p100（evidence 见上）；operator 显式 env 可调（有意的
    越权覆盖，保留逃生口）。
    """
    env = os.environ if env is None else env
    if agent == "hermes":
        raw = env.get(ENV_HERMES_ATTEMPT_TIMEOUT, "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        if risk_class and str(risk_class).strip().upper() in HERMES_RISK_TIER_TIMEOUT:
            return HERMES_RISK_TIER_TIMEOUT[str(risk_class).strip().upper()]
        return HERMES_RISK_TIER_TIMEOUT.get(None, DEFAULT_HERMES_TIMEOUT_NO_RISK)
    if agent == "codex":
        raw = env.get(ENV_CODEX_ATTEMPT_TIMEOUT, "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        return DEFAULT_CODEX_ATTEMPT_TIMEOUT
    # workbuddy（retry 层自管）与未知 agent：返回 Hermes 默认（不参与决策）
    return DEFAULT_HERMES_ATTEMPT_TIMEOUT


# ---------------------------------------------------------------------------
# Shared Hermes stage deadline（v0.5-COST-STOP-LOSS-001-FIX-001 —— Codex
# REQUEST_CHANGE 唯一 blocker 收口）：original invocation 与 A5 FREE/PAID
# fallback 共享**同一个**绝对 stage deadline；fallback 绝不能重启一个完整
# per-attempt timeout（HIGH/CRITICAL 理论 2400+2400=4800s 行为被消除）。
#
# 机制（runner 是 deadline 的唯一 owner，只在 Hermes stage 期间设置/还原）：
# - ``AAF_HERMES_STAGE_BUDGET``（operator 逃生口）→ 默认 3600s（原 3600s 级
#   无进度问题边界；> 全部 risk 档 per-attempt 上限 → 单次成功 invocation 语义
#   零变化，总 stage 墙钟有界）。
# - runner 在首次 invocation 前把 ``AAF_HERMES_STAGE_DEADLINE`` 设为
#   ``monotonic() + budget``（绝对值）；fallback 层绝不重算/重设该值
#   （Requirement 7：进入 fallback_runtime 不 reset deadline）。
# - ``adapters.run_agent`` 每次 subprocess 创建前：
#   effective_timeout = min(per_attempt_timeout, deadline - now)
#   （Requirement 4/8；original 与每个 fallback invocation 同一公式）。
# - ``hermes_fallback_allowed``：每次 fallback 评估前 runner 求值剩余预算；
#   耗尽/低于安全下限（Requirement 5）→ 不发起第二模型、以
#   STAGE_BUDGET_EXHAUSTED 机器原因 fail closed（FREE 与 PAID 都覆盖——
#   该 gate 位于 A5 层入口之前，两种 fallback 都不可能被发起）。
# ---------------------------------------------------------------------------
ENV_HERMES_STAGE_BUDGET = "AAF_HERMES_STAGE_BUDGET"
ENV_HERMES_STAGE_DEADLINE = "AAF_HERMES_STAGE_DEADLINE"
ENV_HERMES_STAGE_MIN_REMAINING = "AAF_HERMES_STAGE_MIN_REMAINING"

# 默认 Hermes stage 总墙钟预算（秒）。evidence：原问题边界 = ~3600s 级无进度
# 等待（adapters 历史 per-attempt 默认 3600）；成功 Hermes stage 按 risk 分组
# p100 ≤ 1886s（COST-STOP-LOSS-001 recon），故 3600s 单 stage 总预算保留 100%
# 已观测成功样本 + 至少一次有界 fallback 尝试空间，同时把
# original+free+paid 理论等待收口到 ≤3600s（2400+1200 / 1500+1500 / …）。
DEFAULT_HERMES_STAGE_BUDGET = 3600.0
# 发起另一次模型 invocation 前必须剩余的安全下限（秒）——低于该值不再启动
# 第二模型（启动即注定无法在 deadline 内产出/有界收敛；fail closed 早停，
# 不空转）。operator 可用 AAF_HERMES_STAGE_MIN_REMAINING 显式调低/归零。
DEFAULT_HERMES_STAGE_MIN_REMAINING = 60.0
# FIX-002（TASK: AAF-v0.5-COST-STOP-LOSS-001-FIX-002 —— Codex REQUEST_CHANGE
# blocker 3 收口）：浮点零边界防护。remaining = deadline - now 是浮点差，在
# deadline 边界处可算出 +1e-9 级"近零正残差"（真实预算已耗尽、仅剩浮点噪声）。
# 任何低于该阈值的 remaining（< 1µs）一律视为已耗尽——绝不因 fp 残差放行一次
# 注定无法收敛的 invocation。阈值远小于任何真实可用剩余（实际读取粒度 ≥ 毫秒
# 级），不可能误杀合法 fallback；AAF_HERMES_STAGE_MIN_REMAINING=0 只解除 60s
# 安全下限，不解除本零边界（Requirement 3：remaining <= 0 / fp near-zero 恒拒绝）。
STAGE_BUDGET_ZERO_EPSILON = 1e-6


def _monotonic() -> float:
    """测试可注入的单调时钟（模块级间接；其余全部 helper 经此取时）。"""
    return time.monotonic()


def resolve_hermes_stage_budget(env=None) -> float:
    """Hermes stage 总墙钟预算（秒）——AAF_HERMES_STAGE_BUDGET 优先，否则默认。

    非法/非正数/非有限 env → 默认（operator typo 不杀死 run；沿用 attempt-timeout
    resolver 的防御语义）。FIX-002（Codex REQUEST_CHANGE blocker 1 收口）：用
    math.isfinite 做权威有限性检查——inf / -inf / NaN 与 <=0 / malformed 一律
    拒绝（fail-safe 到有界默认），**绝不**接受会产生无限 deadline/remaining 的
    预算值（Hermes stage 必须始终有有限墙钟边界）。返回值只被 runner 用于计算
    绝对 deadline。
    """
    env = os.environ if env is None else env
    raw = env.get(ENV_HERMES_STAGE_BUDGET, "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            pass
        else:
            if math.isfinite(value) and value > 0:
                return value
    return DEFAULT_HERMES_STAGE_BUDGET


def resolve_hermes_stage_min_remaining(env=None) -> float:
    """fallback invocation 安全下限（秒）——env override，否则默认。

    允许 operator 显式设 0（禁用早停下限；remaining<=0/零边界 才停——FIX-002
    blocker 3：0 只解除 60s 安全下限，绝不解除耗尽边界）；负数/非法/非有限
    （inf/-inf/NaN）→ 默认。永不返回负值或非有限值。
    """
    env = os.environ if env is None else env
    raw = env.get(ENV_HERMES_STAGE_MIN_REMAINING, "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            pass
        else:
            if math.isfinite(value) and value >= 0:
                return value
    return DEFAULT_HERMES_STAGE_MIN_REMAINING


def hermes_stage_deadline_value(budget_seconds: float | None = None,
                                env=None) -> float:
    """绝对 stage deadline（monotonic epoch 秒）= now + budget。

    budget_seconds=None → resolve_hermes_stage_budget（env/default）。
    runner 在首次 invocation 前调用一次并把结果写入
    ENV_HERMES_STAGE_DEADLINE；**只计算一次**，进入 fallback_runtime 不重算。
    FIX-002（blocker 1 兜底）：显式传入的 budget 同样必须有限正数——非有限
    （inf/-inf/NaN）/非正 → fail-safe 默认。单调钟本身有限 → 本函数返回值恒为
    有限正数（deadline 绝不可能为 inf/nan）。
    """
    if budget_seconds is None:
        budget_seconds = resolve_hermes_stage_budget(env)
    if not (isinstance(budget_seconds, (int, float))
            and math.isfinite(budget_seconds) and budget_seconds > 0):
        budget_seconds = DEFAULT_HERMES_STAGE_BUDGET
    return _monotonic() + budget_seconds


def format_stage_deadline(deadline: float) -> str:
    """绝对 deadline 的无损序列化（FIX-002 —— Codex REQUEST_CHANGE blocker 2 收口）。

    默认 ``:g`` 只保留 6 位有效数字，可把 deadline 向未来舍入（Codex 独立复现：
    monotonic=1000001、budget=3605 → 精确 deadline=1003606 被序列化为
    1.00361e+06 → 解析后有效预算 3609s，比配置多 4s）——违反「序列化 deadline
    不得超出配置墙钟预算」。repr(float) 是 Python 的最短 round-trip 表示：
    ``float(repr(x)) == x`` 恒成立（无方向性格式化误差）→ 解析后的 deadline 与
    精确值逐位相等，剩余预算绝不可能被序列化放大（parsed_deadline <= exact
    configured deadline 恒成立，误差 = 0）。
    """
    return repr(float(deadline))


def hermes_stage_remaining_seconds(env=None) -> float | None:
    """共享 deadline 的剩余秒数。

    - 无 deadline env（非 Hermes stage / 直接调用本模块的测试）→ None（调用方
      保持既有语义，不裁剪不 gate）；
    - FIX-002（blocker 1/4 收口）：deadline env **存在但** malformed / 非有限
      （inf/-inf/NaN——runner 只写无损有限值，此类值只可能来自 operator 手写
      该内部 env）→ 返回 0.0（视为**已到期**，fail closed）。绝不再返回 None：
      None 的"无 deadline 上下文"语义会让该路径回到不裁剪、不 gate 的放行态
      （静默允许另一次 invocation）；0.0 使 adapters 在 spawn 前有界早停、
      fallback gate 拒绝，预算无效/耗尽路径以机器可读 STAGE_BUDGET_EXHAUSTED
      终止（Requirement 4）。
    """
    env = os.environ if env is None else env
    raw = env.get(ENV_HERMES_STAGE_DEADLINE, "").strip()
    if not raw:
        return None
    try:
        deadline = float(raw)
    except ValueError:
        deadline = float("nan")  # 不可解析 → 走下方 isfinite 拒绝路径（0.0）
    if not math.isfinite(deadline):
        return 0.0
    return deadline - _monotonic()


def effective_attempt_timeout(per_attempt_timeout: float, env=None) -> float:
    """Requirement 8：effective_timeout = min(per_attempt_timeout,
    remaining_stage_budget)。无共享 deadline → per_attempt_timeout 原样（既有
    语义）；remaining ≤ 0 → 返回 ≤ 0（调用方以 bounded 早停处理，不启动子进程）。"""
    remaining = hermes_stage_remaining_seconds(env)
    if remaining is None:
        return per_attempt_timeout
    return min(per_attempt_timeout, remaining)


def hermes_fallback_allowed(env=None) -> dict:
    """Requirement 3/5：每次 fallback 评估前的共享 deadline 预算 gate。

    返回 {"allowed", "remaining_seconds", "minimum_required_seconds",
    "suppressed_reason"}：
    - 无共享 deadline env → allowed=True / remaining=None（保持既有 fallback
      语义——只有 runner 的 Hermes stage 设置 deadline，live 路径恒有值）；
    - FIX-002（Requirement 3 / Codex blocker 3 收口）：**remaining <= 0 恒拒绝**
      （即便 operator 把 AAF_HERMES_STAGE_MIN_REMAINING 调到 0——0 只解除 60s
      安全下限，不解除耗尽边界）；浮点"近零"正残差（< STAGE_BUDGET_ZERO_EPSILON
      = 1µs 零边界）同样视为耗尽。放行条件 = remaining > 0 且 remaining >=
      max(minimum, 零边界)；
    - remaining < 安全下限（默认 60s）且仍 > 零边界 → allowed=False +
      suppressed_reason（机器可读；调用方不得发起第二模型，并以
      STAGE_BUDGET_EXHAUSTED 终止）；
    - 否则 allowed=True（实际 invocation 仍会被 adapters 裁剪到 remaining——
      双保险，gate 之后到 subprocess 创建之间的消耗也被同一 deadline 约束）。
    """
    remaining = hermes_stage_remaining_seconds(env)
    if remaining is None:
        return {
            "allowed": True,
            "remaining_seconds": None,
            "minimum_required_seconds": resolve_hermes_stage_min_remaining(env),
            "suppressed_reason": None,
        }
    minimum = resolve_hermes_stage_min_remaining(env)
    exhausted = remaining <= 0.0 or remaining < STAGE_BUDGET_ZERO_EPSILON
    if exhausted or remaining < minimum:
        if exhausted:
            suppressed_reason = (
                "shared Hermes stage deadline exhausted: remaining budget "
                f"{remaining:.1f}s is at or below the zero boundary — no "
                "fallback invocation may start (a strictly positive usable "
                "budget is required)"
            )
        else:
            suppressed_reason = (
                "shared Hermes stage deadline exhausted: remaining budget "
                f"{remaining:.1f}s is below the safe minimum {minimum:.1f}s "
                "required to start another model invocation"
            )
        return {
            "allowed": False,
            "remaining_seconds": remaining,
            "minimum_required_seconds": minimum,
            "suppressed_reason": suppressed_reason,
        }
    return {
        "allowed": True,
        "remaining_seconds": remaining,
        "minimum_required_seconds": minimum,
        "suppressed_reason": None,
    }


# ---------------------------------------------------------------------------
# Rate limit / quota evidence（429 / quota / throttle；只基于真实 CLI 文案）
# ---------------------------------------------------------------------------
_RATE_QUOTA_RE_QUOTA = re.compile(
    r"(?i)\bquota\b.{0,60}(?:exceeded|exhausted|insufficient|limit|depleted|用完|超限|配额)"
    r"|\b(?:exceeded|exhausted|insufficient)\b.{0,40}\bquota\b"
)
_RATE_QUOTA_RE_RATE = (
    re.compile(r"(?i)\b429\b"),
    re.compile(r"(?i)rate\s*[-_]?limit"),
    re.compile(r"(?i)too\s+many\s+requests"),
    re.compile(r"(?i)throttl"),
    re.compile(r"(?i)request\s+limit"),
    re.compile(r"(?i)retry\s+(?:after|in)"),
    re.compile(r"(?i)try\s+again\s+(?:in|later)"),
    re.compile(r"(?i)limit\s+of\s+requests"),
    re.compile(r"(?i)限流|频率限制|请求过多"),
)

_RESET_TIME_UNIT_SECONDS = {
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
}
_RESET_RE_PATTERNS = (
    # "retry after 45 seconds" / "try again in 5 minutes" / "back off 30s"
    re.compile(
        r"(?i)(?:retry|try\s+again|back\s+off|try)(?:\s+(?:after|in))?"
        r"\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])\b"
    ),
    # "rate limit ... reset(s)(in|after) 90 seconds"
    re.compile(
        r"(?i)rate\s*[-_]?limit[^\n]{0,80}?\breset(?:s|ted)?\b[^\n]{0,40}?"
        r"(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?|[smh])\b"
    ),
    # "resets in 90 seconds" / "reset after 5 minutes"
    re.compile(
        r"(?i)\breset(?:s|ted)?\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*"
        r"(seconds?|minutes?|hours?|[smh])\b"
    ),
)


def detect_rate_limit_evidence(text: str | None) -> tuple[str | None, str | None]:
    """识别 CLI 输出中的 rate-limit/quota evidence。返回 (kind, detail)。

    kind ∈ {STOP_REASON_RATE_LIMIT, STOP_REASON_QUOTA, None}。detail = 首个命中行
    （截断）。QUOTA 词证据优先于通用 RATE_LIMIT（quota 是 per-task/per-key 上限，
    reset 窗口通常远超 stage budget；429/rate limit 是瞬时限频）。无证据 → (None,
    None)（绝不把普通文本猜成限频）。
    """
    if not text:
        return None, None
    for line in text.splitlines():
        if _RATE_QUOTA_RE_QUOTA.search(line):
            return STOP_REASON_QUOTA, line.strip()[:200] or None
    for pat in _RATE_QUOTA_RE_RATE:
        m = pat.search(text)
        if m:
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            if end == -1:
                end = len(text)
            return STOP_REASON_RATE_LIMIT, text[start:end].strip()[:200] or None
    return None, None


def parse_rate_limit_reset(text: str | None) -> float | None:
    """从限频文案解析 reset 等待秒数（单位明确才解析；无单位/无文案 → None）。

    None 语义：无法证明 reset 窗口可等 → 调用方应尽早 stop（不空转到 stage
    budget）。秒数解析后由 orchestrator 与 remaining budget 比较决定等还是停。
    """
    if not text:
        return None
    for pat in _RESET_RE_PATTERNS:
        for m in pat.finditer(text):
            try:
                amount = float(m.group(1))
            except ValueError:
                continue
            unit = m.group(2).lower()
            mult = _RESET_TIME_UNIT_SECONDS.get(unit)
            if mult is None:
                continue
            return amount * mult
    return None


# ---------------------------------------------------------------------------
# Timeout 场景的 tool/test-activity evidence（TOOL_OR_TEST_STILL_ACTIVE）
# ---------------------------------------------------------------------------
# 保守启发式（只认明确的"仍在跑工具/测试"字样；absent → ATTEMPT_TIMEOUT，绝不
# 把无证据 timeout 猜成 tool 活动）。
_TOOL_ACTIVITY_MARKERS = (
    re.compile(r"(?i)\brunning\s+(?:tests?|builds?|tools?|pytest|unittest)\b"),
    re.compile(r"(?i)\b(?:pytest|unittest)\b"),
    re.compile(r"(?i)\b(?:test|build)\s+(?:session|started|starting|in\s+progress)\b"),
    re.compile(r"(?i)\bbuilding\b"),
    re.compile(r"(?i)\brunning\s+(?:npm|pip|gradle|mvn|make|go\s+test)\b"),
)


def timeout_shows_tool_activity(text: str | None) -> bool:
    """timeout 清理时排出的 partial output 是否含明确的 tool/test 活动 markers。

    这是"distinguishable"判定（Requirement 7：TOOL_OR_TEST_STILL_ACTIVE where
    distinguishable）：命中 → 停止原因是"有界 attempt 预算耗尽时 child 仍在跑
    合法工具/测试"，与 NO_PROGRESS（无任何进展证据）区分；未命中 → ATTEMPT_TIMEOUT。
    注意：本函数**不参与** attempt 执行中的任何决策——绝不打断在跑的工具/测试。
    """
    if not text:
        return False
    return any(p.search(text) for p in _TOOL_ACTIVITY_MARKERS)


# ---------------------------------------------------------------------------
# Terminal-reason 分类（runner/artifacts 用；纯判定，无 I/O）
# ---------------------------------------------------------------------------
def classify_terminal_reason(*, agent: str, exc: BaseException | None,
                             wb_telemetry: dict | None,
                             result_text: str | None) -> tuple[str | None, str | None]:
    """把一次最终失败的 stage 映射到机器可读 stop reason（无匹配 → (None, None)）。

    顺序（确定性；基于真实 evidence，不叠加猜测）：
    1. WorkBuddy retry 层 telemetry 自报 terminal_reason（rate/quota/no-progress/
       attempt-timeout 等由 orchestrator 在 raise 点显式计算）——PERMANENT_FAILURE /
       CLEANUP_FAILURE 无 vocab reason → None（outcome 本身已机器可读）。
    2. subprocess.TimeoutExpired（Hermes/Codex 单 attempt 硬等待被有界终止）→
       ATTEMPT_TIMEOUT（A5/既有语义不变：异常类型原样传递，仅分类）。
    3. 异常/结果文本中的 429 / quota evidence → RATE_LIMIT / QUOTA。
    4. 其余（普通 RuntimeError / CLI 永久错误 / verdict 型失败）→ None（非
       stop-loss 场景，保留既有 FRAMEWORK_ERROR / verdict 语义）。
    """
    if wb_telemetry:
        outcome = wb_telemetry.get("outcome")
        if outcome and outcome != "SUCCESS":
            reason = wb_telemetry.get("terminal_reason")
            if reason:
                detail = (
                    wb_telemetry.get("retry_suppressed_reason")
                    or (wb_telemetry.get("last_failure") or {}).get("retry_reason")
                )
                return reason, detail
            return None, None
    if exc is not None:
        if isinstance(exc, subprocess.TimeoutExpired):
            return (
                STOP_REASON_ATTEMPT_TIMEOUT,
                f"{agent} attempt exceeded its bounded per-attempt timeout "
                f"({getattr(exc, 'timeout', None)}s)",
            )
        exc_text = f"{type(exc).__name__}: {exc}"
        kind, detail = detect_rate_limit_evidence(exc_text)
        if kind is not None:
            return kind, detail
    if result_text:
        kind, detail = detect_rate_limit_evidence(result_text)
        if kind is not None:
            return kind, detail
    return None, None


def build_stop_loss_record(*, agent: str, task_id: str, exc: BaseException | None,
                           wb_telemetry: dict | None, result_text: str | None,
                           elapsed_seconds: float | None,
                           stage_budget_exhausted: dict | None = None) -> dict | None:
    """构造 stop_loss.json 机器记录；无已识别 stop reason → None（调用方不写文件）。

    ``stage_budget_exhausted``（FIX-001：runner 在共享 Hermes stage deadline
    耗尽、fallback 被 gate 拦截时传入的 ``hermes_fallback_allowed`` 结果）优先
    于其他分类——stage 因预算耗尽而无法发起任何 fallback 是比底层异常更精确的
    terminal reason（STAGE_BUDGET_EXHAUSTED，机器可读）；缺省 None → 既有
    classify_terminal_reason 路径不变。
    """
    if stage_budget_exhausted and not stage_budget_exhausted.get("allowed", True):
        reason = STOP_REASON_STAGE_BUDGET_EXHAUSTED
        remaining = stage_budget_exhausted.get("remaining_seconds")
        minimum = stage_budget_exhausted.get("minimum_required_seconds")
        detail = (
            f"shared Hermes stage deadline exhausted before any fallback "
            f"invocation: remaining budget "
            f"{round(float(remaining), 1) if remaining is not None else '?'}s "
            f"is insufficient to start another model invocation "
            f"(required minimum "
            f"{round(float(minimum), 1) if minimum is not None else '?'}s; "
            f"remaining <= 0 / below the zero boundary also counts as "
            f"exhausted) — no FREE or PAID fallback model was invoked (fail "
            f"closed); the original stage failure is preserved for "
            f"RESUME/recovery"
        )
        return {
            "schema_version": 1,
            "task_id": task_id,
            "agent": agent,
            "terminal_reason": reason,
            "detail": detail,
            "triggered_at": _iso_now(),
            "elapsed_seconds": round(float(elapsed_seconds), 1) if elapsed_seconds else None,
            "outcome": "stage_attempt_failed",
            "attempt_count": 1,
            "notes": [
                "shared Hermes stage deadline: the A5 fallback layer was not "
                "entered (remaining budget exhausted/insufficient before the "
                "shared deadline); stage result/attempt evidence 见本目录 "
                "*_result.md / *_result.json",
                "RESUME/recovery：保留本目录全部 artifacts；修复后以 --resume-from 重新执行本 stage",
            ],
        }
    reason, detail = classify_terminal_reason(
        agent=agent, exc=exc, wb_telemetry=wb_telemetry, result_text=result_text
    )
    if reason is None:
        return None
    record: dict = {
        "schema_version": 1,
        "task_id": task_id,
        "agent": agent,
        "terminal_reason": reason,
        "detail": detail,
        "triggered_at": _iso_now(),
        "elapsed_seconds": round(float(elapsed_seconds), 1) if elapsed_seconds else None,
    }
    if wb_telemetry:
        record["outcome"] = wb_telemetry.get("outcome")
        record["attempt_count"] = wb_telemetry.get("attempt_count")
        record["attempts_artifact"] = "workbuddy_attempts.json"
        record["notes"] = [
            "WorkBuddy retry 层已停止；详细 attempt evidence 见 workbuddy_attempts.json",
            "RESUME/recovery：保留本目录全部 artifacts；修复后以 --resume-from 重新执行本 stage",
        ]
    else:
        record["outcome"] = "stage_attempt_failed"
        record["attempt_count"] = 1
        record["notes"] = [
            f"{agent} stage 最终失败（stop-loss 有界终止）；stage result/attempt "
            "evidence 见本目录 *_result.md / *_result.json",
            "RESUME/recovery：保留本目录全部 artifacts；修复后以 --resume-from 重新执行本 stage",
        ]
    return record


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
