"""AAF Bridge — Cost / Model 可见性（display-only 归一化层）。

TASK: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001（基于只读审计
AAF-v0.5-UX-COST-VISIBILITY-AUDIT-001 的结论）+ FIX-001（truth semantics：
planned/authorized ≠ actual invocation）。本模块 = 概念流中间层：

    既有 authoritative runtime artifacts（task output_dir 内）
    -> display-only 归一化 cost/model view（本模块，纯函数只读）
    -> 既有 Bridge 状态窗口（bridge/status_window.py 渲染）

权威与显示边界（本模块不改任何 authority）：
- 零模型选择 / 零路由 / 零资格化 / 零 fallback 资格 / 零 Paid Guard /
  零 Cost Guard / 零付费授权变化（不 import 任何决策执行路径；只按 artifact
  token 值做 whitelist 归一化显示）。
- 绝不从模型名推断 FREE/PAID（Requirement 2）。
- 零新建经济权威。显示词汇全部来自既有 artifact token。
- 缺失 / 损坏的 optional artifact -> 相应字段 UNKNOWN / NOT_USED，绝不抛异常
  （Requirement 14/15，fail-soft per row）。

*** FIX-001 truth model（planned/authorized ≠ actual invocation）***

证据按语义显式分类，只有「actual invocation 证据」能填充 actual 字段：

1) planned / authorized 证据（可能描述 selected candidate / authorization /
   routing intent，但**绝不等于 actual invocation**）：
   - cost_guard.json decision（ALLOWED_AUTHORIZED_PAID / ALLOWED_FREE）+
     guard model/provider（pre-invocation 准入镜像）
   - active_routing.json routing_applied=true + routed_model（A3 候选）
   - workbuddy_active_routing.json routing_applied=true + routed_model（A4 候选）
   这些证据单独存在时：Actual Model/Provider/Cost Class 一律 UNKNOWN，
   计划/授权信息以显式标签（"Planned: ..." / AUTHORIZED token）呈现，
   与 Actual 列视觉区分（Requirement 6/7/8/9）。

2) actual invocation 证据（证明一次 invocation 真实发生后才可填充）：
   - <agent>_result.md = valid（存在、非空、不以 FRAMEWORK_ERROR 开头）——
     与 runner `_result_is_valid` 同一语义：run_agent 真实返回输出。
   - A5 paid_fallback_runtime.json（paid fallback invocation 真实发生后才持久化，
     attempted=true 恒真）——fallback 分支的 actual invocation 证据。
   - A5 fallback_runtime.json fallback_used=true（free fallback invocation
     真实发生并被接受）。
   只有这些证据存在时 Actual Model / Provider / FREE / LOCAL_FREE / PAID /
   USED_FREE / USED_PAID 才允许出现；否则 Actual = UNKNOWN（Requirement 11-14、
   C.）。

3) final / fallback outcome：
   - USED_FREE：free fallback invocation 真实发生且被接受。
   - USED_PAID：paid fallback invocation 真实发生（attempted=true 恒真）。
   - AUTHORIZED（paid_escalation_gate）无执行 -> 绝不 USED_PAID。
   - BLOCKED 仅当权威 guard/gate 证明 execution 被阻断（Requirement 15）。

显示词汇（Requirement/audit 定义；技术 token 保留英文）：
Cost Class: FREE / LOCAL_FREE / PAID / UNKNOWN / BLOCKED
Fallback:   NOT_USED / USED_FREE / USED_PAID / FAILED / UNKNOWN
模型 / provider 缺失显示 "—"（既有状态窗口约定）。
Planned（可选，仅 actual 不可证时出现）：
  e.g. "deepseek-v4-flash / PAID / AUTHORIZED"、"qwen3:4b / LOCAL_FREE / ALLOWED_FREE"
  -> 显式 "Planned:" 前缀标签呈现（Requirement 9/10）。

每字段权威源（全部 read-only join，只读 output_dir）：
- role/stage：route.json agents（调用方传入 route_agents）
- Hermes actual model/provider：A5 final-actual（paid/free fallback 真实执行）
  > model_observation.json observations.hermes（post-hoc actual；仅 invocation
  已证时可用；缺失 -> UNKNOWN，绝不回退 guard/routing 作为 actual）。
- Hermes cost class：paid_fallback_runtime.json（真实 paid-class invocation）
  > guard BLOCKED_COST_APPROVAL -> BLOCKED > free fallback used=true
  （最终 actual = 免费兜底）> <agent>_result.md valid（original invocation 已证）
  时 guard ALLOWED_AUTHORIZED_PAID -> PAID / ALLOWED_FREE -> LOCAL_FREE >
  observation cost_class 端点证据 > UNKNOWN。
- Hermes fallback：A5 三件套语义（见上）；无 A5 artifact -> NOT_USED。
- WorkBuddy model/cost：仅 workbuddy_result.md valid（invocation 已证）时
  routed_model / obs / A4 free-promo 才作为 actual；否则 UNKNOWN + Planned。
- Codex model：仅 codex_result.md valid（invocation 已证）时回显 observation；
  cost 恒 UNKNOWN。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# 本模块允许的路由 stage agents（既有 status_window 六阶段条中的三个 agent 阶段）
ROUTE_AGENTS = ("hermes", "workbuddy", "codex")

# ---- 显示词汇（技术 token；authority = artifact 既有 token，不另造） ----
COST_FREE = "FREE"
COST_LOCAL_FREE = "LOCAL_FREE"
COST_PAID = "PAID"
COST_UNKNOWN = "UNKNOWN"
COST_BLOCKED = "BLOCKED"
COST_CLASSES_DISPLAY = (COST_FREE, COST_LOCAL_FREE, COST_PAID, COST_UNKNOWN, COST_BLOCKED)

FALLBACK_NOT_USED = "NOT_USED"
FALLBACK_USED_FREE = "USED_FREE"
FALLBACK_USED_PAID = "USED_PAID"
FALLBACK_FAILED = "FAILED"
FALLBACK_UNKNOWN = "UNKNOWN"
FALLBACK_DISPLAY_VALUES = (
    FALLBACK_NOT_USED,
    FALLBACK_USED_FREE,
    FALLBACK_USED_PAID,
    FALLBACK_FAILED,
    FALLBACK_UNKNOWN,
)

# 模型 / provider 缺失显示（既有状态窗口 UNKNOWN 常量 "—"）
DISPLAY_UNKNOWN = "—"

# ---- A0 guard artifact token（cost_guard.json；值域 = 既有权威词汇） ----
_GUARD_DECISION_ALLOWED_FREE = "ALLOWED_FREE"
_GUARD_DECISION_ALLOWED_AUTHORIZED_PAID = "ALLOWED_AUTHORIZED_PAID"
_GUARD_DECISION_BLOCKED = "BLOCKED_COST_APPROVAL"

# A5 paid escalation gate token（paid_escalation_gate.json）
_GATE_AUTHORIZED = "AUTHORIZED"
_GATE_BLOCKED = "BLOCKED"
_GATE_FAIL_CLOSED = "FAIL_CLOSED"

# runner `_result_is_valid` 判定的 framework-invalid 前缀
_RESULT_INVALID_PREFIX = "FRAMEWORK_ERROR"

# artifact 文件名（与 ai_agent_framework 各 authority 模块常量一致；只读引用）
ARTIFACT_MODEL_OBSERVATION = "model_observation.json"
ARTIFACT_COST_GUARD = "cost_guard.json"
ARTIFACT_ACTIVE_ROUTING = "active_routing.json"
ARTIFACT_WORKBUDDY_ROUTING = "workbuddy_active_routing.json"
ARTIFACT_FALLBACK_RUNTIME = "fallback_runtime.json"
ARTIFACT_PAID_GATE = "paid_escalation_gate.json"
ARTIFACT_PAID_RUNTIME = "paid_fallback_runtime.json"


@dataclass(frozen=True)
class CostRow:
    """单个 route agent 的 display-only Cost / Model 行（全部为展示就绪事实）。

    - agent: 'hermes' | 'workbuddy' | 'codex'（原始 token；显示名由渲染层映射）
    - model / provider: **actual** 显示文本（仅 actual invocation 证据可填充；
      缺失 -> DISPLAY_UNKNOWN "—"；guard/routing model 绝不进入 actual）
    - cost_class: **actual** 显示词汇（仅 actual invocation 证据可填充；
      不可证 -> UNKNOWN；guard BLOCKED -> BLOCKED = 权威阻断）
    - fallback: FALLBACK_* 显示词汇（默认 NOT_USED）
    - planned: 可选 compact planned/authorized 文本（仅 actual 不可证且存在
      guard/routing 证据时出现；渲染层以 "Planned:" 前缀 + 灰字呈现，
      与 actual 列区分——Requirement 9/10）
    - detail: 可选一行短 detail（fallback 上下文 / 短 reason；无则空串）
    """

    agent: str
    model: str = DISPLAY_UNKNOWN
    provider: str = DISPLAY_UNKNOWN
    cost_class: str = COST_UNKNOWN
    fallback: str = FALLBACK_NOT_USED
    planned: str = ""
    detail: str = ""


def read_json(output_dir: Path | str | None, filename: str) -> dict | None:
    """只读 artifact JSON；缺失 / 损坏 / 非 dict -> None（绝不抛异常）。

    显示层的统一 fail-soft 读取口（Requirement 14/15/I：损坏 optional
    evidence 必须 degrade 而非崩溃 UI）。
    """
    if output_dir is None:
        return None
    path = Path(output_dir) / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def load_observation(output_dir: Path | str | None, agent: str) -> dict | None:
    """model_observation.json observations.<agent>（dict 校验后返回）。"""
    registry = read_json(output_dir, ARTIFACT_MODEL_OBSERVATION)
    if registry is None:
        return None
    entry = registry.get("observations") or {}
    obs = entry.get(agent) if isinstance(entry, dict) else None
    return obs if isinstance(obs, dict) else None


def read_result_md(output_dir: Path | str | None, agent: str) -> str | None:
    """只读 <agent>_result.md 头部（≤4KB）；缺失 / 读取失败 -> None（fail-soft）。

    FIX-001：<agent>_result.md 的 validity 是 original invocation 的实际证据
    （runner 在 run_agent 返回后写盘；guard-BLOCKED / 启动失败 / 崩溃时文本以
    FRAMEWORK_ERROR 开头 -> invalid）。只读头部足够判定前缀，避免每秒 UI
    刷新重复读取大文件。
    """
    if output_dir is None:
        return None
    try:
        with open(Path(output_dir) / f"{agent}_result.md", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except (OSError, ValueError):
        return None
    return head


def _result_md_is_valid(text: str | None) -> bool:
    """与 runner `_result_is_valid` 同语义：非空且不以 FRAMEWORK_ERROR 开头。"""
    if not text:
        return False
    body = text.strip()
    if not body:
        return False
    return not body.startswith(_RESULT_INVALID_PREFIX)


def _s(value: object) -> str:
    """非空 str -> 原值；其余 -> ''（类型安全 echo）。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _is_true(value: object) -> bool:
    return value is True


def _model_provider_from_observation(obs: dict | None) -> tuple[str, str]:
    """observation 的 model/provider（仅作实际观测回显；缺失 -> "—"）。"""
    if not obs:
        return DISPLAY_UNKNOWN, DISPLAY_UNKNOWN
    model = _s(obs.get("model"))
    provider = _s(obs.get("provider"))
    return (model or DISPLAY_UNKNOWN), (provider or DISPLAY_UNKNOWN)


def _registry_cost_label(routed_model: str | None, routed_provider: str | None) -> str | None:
    """A1 baseline registry 的 cost label（A3 routing_applied=true 时的证据回显）。

    只读回显决策时同一 registry 的 cost_class；FREE_PROMO 归 FREE（附 promo
    说明由 detail 承担——audit 词汇：不另造）。无匹配 / 非 FREE 集合 -> None
    （调用方 fall back 到 UNKNOWN；绝不猜）。
    """
    from ai_agent_framework import model_registry as _mr  # 纯 dataclass 模块（零 I/O）

    if not routed_model:
        return None
    key = _mr.canonical_key(routed_model, routed_provider or None)
    entry = _mr.baseline_registry().get(key)
    if entry is None:
        return None
    label = getattr(entry, "cost_class", None)
    if label == "LOCAL_FREE":
        return COST_LOCAL_FREE
    if label == "FREE":
        return COST_FREE
    if label == "FREE_PROMO":
        return COST_FREE  # FREE_PROMO 归一 FREE（audit 词汇；promo 事实进 detail）
    return None


def _guard_decision(guard: dict | None) -> str:
    """guard decision token -> 显示词汇（仅作为已证 invocation 的 cost 分类）。

    FIX-001：guard 单独出现**不构成** actual 证据；只有在 <agent>_result.md
    valid（actual invocation 已证）时才允许把 decision 映射为 actual cost
    （Requirement 6/7：ALLOWED_* MUST NOT by itself render actual cost）。
    """
    if not guard:
        return ""
    return _s(guard.get("decision"))


def _normalize_agent_token(value: object) -> str:
    """artifact token -> 显示词汇；未知 / 非 str -> UNKNOWN（不猜）。"""
    token = _s(value)
    if token in COST_CLASSES_DISPLAY:
        return token
    return COST_UNKNOWN


def _normalize_fallback_token(value: object, default: str = FALLBACK_NOT_USED) -> str:
    """artifact token -> fallback 显示词汇；未知 -> 默认（不猜）。"""
    token = _s(value)
    if token in FALLBACK_DISPLAY_VALUES:
        return token
    return default


# ---------------------------------------------------------------------------
# Hermes（executor）—— evidence classification helpers
# ---------------------------------------------------------------------------


def _hermes_actual_model_provider(
    result_valid: bool,
    obs: dict | None,
    fb_free: dict | None,
    fb_paid: dict | None,
) -> tuple[str, str]:
    """Hermes **actual** model/provider（仅 actual invocation 证据可填充）。

    FIX-001 优先序（全部为 post-invocation / invocation-grounded 证据）：
    1) A5 paid fallback runtime（paid invocation 真实发生后才持久化；
       attempted=true 恒真）-> paid candidate / final actual model。
    2) A5 free fallback used=true（free fallback invocation 真实发生并被接受）
       -> final actual model。
    3) <agent>_result.md valid（original invocation 已证）-> observation
       （post-hoc actual）。observation 缺失 -> UNKNOWN——**绝不**回退 guard /
       routing model 作为 actual（guard = pre-invocation 准入镜像，
       Requirement 5/12；routing = candidate 证据，Requirement 8）。
    """
    if fb_paid is not None:
        m = _s(fb_paid.get("paid_candidate_model") or fb_paid.get("final_actual_model"))
        p = _s(fb_paid.get("paid_candidate_provider") or fb_paid.get("final_actual_provider"))
        if m:
            return m, (p or DISPLAY_UNKNOWN)
    if fb_free is not None and _is_true(fb_free.get("fallback_used")):
        m = _s(fb_free.get("final_actual_model"))
        p = _s(fb_free.get("final_actual_provider"))
        if m:
            return m, (p or DISPLAY_UNKNOWN)
    if result_valid:
        obs_model, obs_provider = _model_provider_from_observation(obs)
        return obs_model, obs_provider
    return DISPLAY_UNKNOWN, DISPLAY_UNKNOWN


def _hermes_planned_text(
    result_valid: bool,
    guard: dict | None,
    obs: dict | None,
    active: dict | None,
    fb_free: dict | None,
    gate: dict | None,
    fb_paid: dict | None,
) -> str:
    """Hermes planned/authorized compact 文本（仅 actual 不可证时出现）。

    - guard ALLOWED_AUTHORIZED_PAID -> "<model> / PAID / AUTHORIZED"
    - guard ALLOWED_FREE -> "<model> / LOCAL_FREE / ALLOWED_FREE"
    - 无 guard 但有 A3 routing_applied=true -> "<routed> / <registry label>/ ROUTED"
    - actual 已证 / guard BLOCKED / 无 planned 证据 -> ""
    """
    if result_valid or fb_paid is not None:
        return ""
    if fb_free is not None or gate is not None:
        return ""  # A5 上下文存在：由 fallback/detail 语义呈现，不混入 planned
    decision = _guard_decision(guard)
    if decision == _GUARD_DECISION_ALLOWED_AUTHORIZED_PAID:
        m = _s(guard.get("model")) or DISPLAY_UNKNOWN
        return f"{m} / {COST_PAID} / AUTHORIZED"
    if decision == _GUARD_DECISION_ALLOWED_FREE:
        m = _s(guard.get("model")) or DISPLAY_UNKNOWN
        return f"{m} / {COST_LOCAL_FREE} / {_GUARD_DECISION_ALLOWED_FREE}"
    if active is not None and _is_true(active.get("routing_applied")):
        routed = _s(active.get("routed_model")) or DISPLAY_UNKNOWN
        label = _registry_cost_label(
            _s(active.get("routed_model")) or None,
            _s(active.get("routed_provider")) or None,
        )
        return f"{routed} / {label or COST_UNKNOWN} / ROUTED"
    return ""


def _hermes_actual_cost_class(
    result_valid: bool,
    guard: dict | None,
    obs: dict | None,
    active: dict | None,
    fb_free: dict | None,
    fb_paid: dict | None,
) -> str:
    """Hermes **actual** cost class（仅 actual invocation 证据可证时填充）。

    FIX-001 优先序：
    1) A5 paid fallback runtime 存在（真实 paid-class invocation 审计）
       -> PAID。
    2) guard BLOCKED_COST_APPROVAL -> BLOCKED（权威阻断；Hermes 未执行，
       Requirement 15）。
    3) A5 free fallback used=true（free fallback invocation 真实发生并被
       接受）-> LOCAL_FREE（最终 actual = A0 ALLOWED_FREE 端点证据）。
    4) original invocation 已证（<agent>_result.md valid）：
       - guard ALLOWED_AUTHORIZED_PAID -> PAID（已授权 paid-class model
         实际执行）
       - guard ALLOWED_FREE -> LOCAL_FREE（A0 LOCAL_FREE 端点证据已执行）
       - observation cost_class 显式 LOCAL_FREE / FREE -> 端点证据回显
       - 其余 -> UNKNOWN
    5) 其余（guard 单独 / routing 单独 / 无证据）-> UNKNOWN。
    """
    if fb_paid is not None:
        return COST_PAID
    decision = _guard_decision(guard)
    if decision == _GUARD_DECISION_BLOCKED:
        return COST_BLOCKED
    if fb_free is not None and _is_true(fb_free.get("fallback_used")):
        return COST_LOCAL_FREE
    if result_valid:
        if decision == _GUARD_DECISION_ALLOWED_AUTHORIZED_PAID:
            return COST_PAID
        if decision == _GUARD_DECISION_ALLOWED_FREE:
            return COST_LOCAL_FREE
        if obs is not None:
            obs_cost = _s(obs.get("cost_class"))
            if obs_cost == "LOCAL_FREE":
                return COST_LOCAL_FREE
            if obs_cost == "FREE" or obs_cost == "FREE_PROMO":
                return COST_FREE
        if active is not None and _is_true(active.get("routing_applied")):
            label = _registry_cost_label(
                _s(active.get("routed_model")) or None,
                _s(active.get("routed_provider")) or None,
            )
            if label:
                return label
    return COST_UNKNOWN


def _hermes_fallback(
    fb_free: dict | None,
    gate: dict | None,
    fb_paid: dict | None,
) -> str:
    """Hermes fallback 显示（audit 五节；represent at minimum 全语义覆盖）。

    FIX-001 语义（Requirement 14/18-G/H/I）：
    - fb_paid 存在 = paid fallback invocation 真实发生（attempted=true 恒真）：
      used=true -> USED_PAID；否则 FAILED（attempted-not-used）。
    - gate AUTHORIZED 但无 fb_paid -> NOT_USED（authorized != invocation，
      绝不 USED_PAID）。
    - gate BLOCKED / FAIL_CLOSED -> FAILED（gate 阻断付费兜底）。
    - fb_free used=true -> USED_FREE（free fallback invocation 真实发生且被接受）；
      attempted-not-used / no-attempt -> FAILED。
    - 无 A5 artifact -> NOT_USED。
    """
    if fb_paid is not None:
        return FALLBACK_USED_PAID if _is_true(fb_paid.get("fallback_used")) else FALLBACK_FAILED
    if gate is not None:
        decision = _s(gate.get("gate_decision"))
        if decision == _GATE_AUTHORIZED:
            return FALLBACK_NOT_USED
        if decision in (_GATE_BLOCKED, _GATE_FAIL_CLOSED):
            return FALLBACK_FAILED
        return FALLBACK_UNKNOWN
    if fb_free is not None:
        if _is_true(fb_free.get("fallback_used")):
            return FALLBACK_USED_FREE
        return FALLBACK_FAILED
    return FALLBACK_NOT_USED


def _hermes_detail(
    model: str,
    provider: str,
    cost_class: str,
    fallback: str,
    guard: dict | None,
    active: dict | None,
    fb_free: dict | None,
    gate: dict | None,
    fb_paid: dict | None,
) -> str:
    """Hermes 行 detail（仅 fallback 上下文 / 已证 actual 的短 reason；一行短）。"""
    if fb_paid is not None:
        orig = _s(fb_paid.get("original_model")) or DISPLAY_UNKNOWN
        paid = _s(fb_paid.get("paid_candidate_model")) or model
        if fallback == FALLBACK_USED_PAID:
            return f"original {orig} failed → authorized paid fallback {paid} used"
        return f"original {orig} failed → authorized paid fallback {paid} attempted but not accepted"
    if gate is not None:
        decision = _s(gate.get("gate_decision"))
        orig = _s((fb_free or {}).get("original_model")) or DISPLAY_UNKNOWN
        if decision == _GATE_AUTHORIZED:
            return "paid escalation AUTHORIZED but no invocation evidence (not USED_PAID)"
        if decision in (_GATE_BLOCKED, _GATE_FAIL_CLOSED):
            base = f"original {orig} failed; free fallback unavailable"
            if fb_free is not None:
                reason = _s(fb_free.get("decision_reason"))
                if reason and len(reason) < 120:
                    base = f"{base} ({reason})"
            return f"{base}; paid fallback blocked ({decision})"
        return "paid escalation gate evaluated (unknown gate decision)"
    if fb_free is not None:
        orig = _s(fb_free.get("original_model")) or DISPLAY_UNKNOWN
        if fallback == FALLBACK_USED_FREE:
            fb_model = _s(fb_free.get("final_actual_model")) or DISPLAY_UNKNOWN
            return f"original {orig} failed → free fallback {fb_model} used"
        reason = _s(fb_free.get("decision_reason"))
        suffix = f" ({reason})" if reason and len(reason) < 140 else ""
        return f"original {orig} failed; no usable free fallback; original failure preserved{suffix}"
    if cost_class == COST_BLOCKED:
        return "blocked: cost approval required"
    if cost_class == COST_PAID:
        return "authorized paid invocation"
    if cost_class == COST_LOCAL_FREE:
        return "local free invocation"
    if cost_class == COST_FREE:
        return "free invocation"
    return ""


def derive_hermes_row(
    output_dir: Path | str | None = None,
    *,
    guard: dict | None = None,
    obs: dict | None = None,
    active: dict | None = None,
    fb_free: dict | None = None,
    gate: dict | None = None,
    fb_paid: dict | None = None,
    result_md: str | None = None,
) -> CostRow:
    """Hermes（executor）行的 display-only 归一化（纯函数；全参数可注入）。

    FIX-001：actual invocation 证据 = <agent>_result.md valid
    （`result_md` 注入时以注入为准；未注入且 output_dir 提供时只读加载；
    两者皆缺 -> 未证 -> actual UNKNOWN + Planned 呈现 guard/routing 意图）。

    未注入的 artifact 参数在 output_dir 提供时按文件名只读加载（fail-soft）；
    显式注入优先（测试确定性）。
    """
    if result_md is None and output_dir is not None:
        result_md = read_result_md(output_dir, "hermes")
    result_valid = _result_md_is_valid(result_md)
    if guard is None and output_dir is not None:
        guard = read_json(output_dir, ARTIFACT_COST_GUARD)
    if obs is None and output_dir is not None:
        obs = load_observation(output_dir, "hermes")
    if active is None and output_dir is not None:
        active = read_json(output_dir, ARTIFACT_ACTIVE_ROUTING)
    if fb_free is None and output_dir is not None:
        fb_free = read_json(output_dir, ARTIFACT_FALLBACK_RUNTIME)
    if gate is None and output_dir is not None:
        gate = read_json(output_dir, ARTIFACT_PAID_GATE)
    if fb_paid is None and output_dir is not None:
        fb_paid = read_json(output_dir, ARTIFACT_PAID_RUNTIME)
    model, provider = _hermes_actual_model_provider(result_valid, obs, fb_free, fb_paid)
    cost_class = _hermes_actual_cost_class(
        result_valid, guard, obs, active, fb_free, fb_paid
    )
    fallback = _hermes_fallback(fb_free, gate, fb_paid)
    planned = _hermes_planned_text(result_valid, guard, obs, active, fb_free, gate, fb_paid)
    detail = _hermes_detail(
        model, provider, cost_class, fallback, guard, active, fb_free, gate, fb_paid
    )
    if not detail and planned:
        detail = ""  # planned 独立字段呈现（渲染层加 "Planned:" 前缀）
    return CostRow(
        agent="hermes", model=model, provider=provider,
        cost_class=cost_class, fallback=fallback, planned=planned, detail=detail,
    )


# ---------------------------------------------------------------------------
# WorkBuddy（validator）—— same truth rule（Requirement 13）
# ---------------------------------------------------------------------------


def _workbuddy_winner_fact(wb: dict | None, routed_model: str | None) -> dict | None:
    """A4 artifact economic_facts.<winner> 摘要（可证免费促销判断只消费它）。"""
    if not wb or not routed_model:
        return None
    facts = wb.get("economic_facts")
    if not isinstance(facts, dict):
        return None
    fact = facts.get(routed_model)
    return fact if isinstance(fact, dict) else None


def _workbuddy_free_promo(wb: dict | None, routed_model: str | None) -> bool:
    """WorkBuddy FREE 唯一可证路径：A4 routing_applied=true + winner 经济事实
    cheapness_rank==0（RANK_AUTHORITATIVE_CHEAP = FRESH + 显式免费 + multiplier
    0.0 + factor 0.0）且 promotion_status==\"free\"。其余一律 UNKNOWN——
    绝不因 LOW/MEDIUM economic routing 存在而标 FREE（Requirement 9）。"""
    if not (wb is not None and _is_true(wb.get("routing_applied")) and routed_model):
        return False
    fact = _workbuddy_winner_fact(wb, routed_model)
    if fact is None:
        return False
    return fact.get("cheapness_rank") == 0 and _s(fact.get("promotion_status")) == "free"


def derive_workbuddy_row(
    output_dir: Path | str | None = None,
    *,
    wb: dict | None = None,
    obs: dict | None = None,
    result_md: str | None = None,
) -> CostRow:
    """WorkBuddy（validator）行的 display-only 归一化（纯函数；全参数可注入）。

    FIX-001（Requirement 13，same truth rule）：routing_applied=true + winner
    是 planned/candidate 证据；**actual** model/FREE 只有在 workbuddy_result.md
    valid（actual invocation 已证）时才能由 routed_model / obs / free-promo
    事实填充，否则 Actual UNKNOWN + Planned 呈现候选。A4 决策（--model）真实
    应用后 invocation 已证 -> routed_model 可作为 actual（与 A4 record 的
    authoritative execution 语义一致）。
    """
    if result_md is None and output_dir is not None:
        result_md = read_result_md(output_dir, "workbuddy")
    result_valid = _result_md_is_valid(result_md)
    if wb is None and output_dir is not None:
        wb = read_json(output_dir, ARTIFACT_WORKBUDDY_ROUTING)
    if obs is None and output_dir is not None:
        obs = load_observation(output_dir, "workbuddy")

    model = DISPLAY_UNKNOWN
    provider = DISPLAY_UNKNOWN
    routed_model: str | None = None
    if wb is not None and _is_true(wb.get("routing_applied")):
        routed_model = _s(wb.get("routed_model")) or None
    free_promo = _workbuddy_free_promo(wb, routed_model)
    planned = ""
    detail = ""

    if result_valid:
        # actual invocation 已证 -> actual model/cost 可填充
        obs_model, obs_provider = _model_provider_from_observation(obs)
        if routed_model and obs_model == DISPLAY_UNKNOWN:
            # A4 --model 已真实应用且 invocation 已证：routed_model = actual
            model = routed_model
            provider = DISPLAY_UNKNOWN
        elif obs_model != DISPLAY_UNKNOWN:
            model = obs_model
            provider = obs_provider
        cost_class = COST_FREE if (free_promo and routed_model) else COST_UNKNOWN
        if cost_class == COST_FREE:
            detail = "qualified free candidate (free promo, A4 economic routing)"
        elif routed_model:
            detail = "no proven free evidence (A4 economic routing winner only)"
    else:
        # actual 不可证：cost/model UNKNOWN；routing candidate -> Planned 标签
        cost_class = COST_UNKNOWN
        if routed_model:
            if free_promo:
                planned = f"{routed_model} / {COST_FREE} / ROUTED (free promo)"
            else:
                planned = f"{routed_model} / {COST_UNKNOWN} / ROUTED (A4 economic)"
        elif wb is not None and _s(wb.get("reason")):
            planned = ""
    return CostRow(
        agent="workbuddy", model=model, provider=provider,
        cost_class=cost_class, fallback=FALLBACK_NOT_USED, planned=planned, detail=detail,
    )


def derive_codex_row(
    output_dir: Path | str | None = None,
    *,
    obs: dict | None = None,
    result_md: str | None = None,
) -> CostRow:
    """Codex（reviewer）行的 display-only 归一化（纯函数；全参数可注入）。

    模型仅在有 config 证据（observation model_source=config）**且 invocation
    已证**（codex_result.md valid）时显示；provider / cost 无运行时可证来源 ->
    UNKNOWN（Requirement 10 + FIX-001 Requirement 13 same truth rule）。
    fallback = 架构性 NOT_USED（AAF 无 Codex 模型级 fallback 机制）。
    """
    if result_md is None and output_dir is not None:
        result_md = read_result_md(output_dir, "codex")
    result_valid = _result_md_is_valid(result_md)
    if obs is None and output_dir is not None:
        obs = load_observation(output_dir, "codex")
    if result_valid:
        model, provider = _model_provider_from_observation(obs)
    else:
        model, provider = DISPLAY_UNKNOWN, DISPLAY_UNKNOWN
    return CostRow(
        agent="codex", model=model, provider=provider,
        cost_class=COST_UNKNOWN, fallback=FALLBACK_NOT_USED,
    )


_DERIVERS = {
    "hermes": derive_hermes_row,
    "workbuddy": derive_workbuddy_row,
    "codex": derive_codex_row,
}


def build_cost_rows(
    output_dir: Path | str | None,
    route_agents: Iterable[str] | None = None,
) -> list[CostRow]:
    """output_dir 内既有 artifact -> 每 route agent 一行的 display-only view。

    - route_agents 缺省 / None：按既有 evidence 判定（model_observation
      observations 键 ∩ ROUTE_AGENTS；仍无 -> 空列表——不扫描猜测）。
    - 每个 agent 行内部 fail-soft：任何异常只让该行降级为全 UNKNOWN 行，
      绝不向调用方抛错（Requirement 14/15：缺失/损坏 evidence 不崩溃 UI）。
    - 行序固定 = ROUTE_AGENTS 序（渲染层与 Stage Strip 同序）。
    - FIX-001：actual invocation 证据由各 derive 函数从 <agent>_result.md
      validity 判定；guard/routing 单独存在绝不产生 actual 显示。
    """
    if output_dir is None:
        return []
    if route_agents is None:
        registry = read_json(output_dir, ARTIFACT_MODEL_OBSERVATION)
        entries = (registry or {}).get("observations") or {}
        agents = [a for a in ROUTE_AGENTS if isinstance(entries.get(a), dict)]
    else:
        wanted = [a for a in ROUTE_AGENTS if a in set(str(a) for a in route_agents)]
        if not wanted:
            return []
        agents = wanted
    rows: list[CostRow] = []
    for agent in agents:
        try:
            row = _DERIVERS[agent](output_dir)
        except Exception:  # noqa: BLE001 —— display-only fail-soft（绝不影响 UI）
            row = CostRow(agent=agent)
        rows.append(row)
    return rows


def row_visible(output_dir: Path | str | None, row: CostRow) -> bool:
    """该行是否有任何可证 evidence（stage 未开始且零 artifact 时不显示）。

    显示过滤（调用方可选）：只依据真实 evidence（artifact 存在 / 非 UNKNOWN
    显示值 / 非默认 fallback / planned 信息）——自动生成的 UNKNOWN detail 文本
    不构成 evidence（Requirement 17：不把 unproven future selection 当 actual
    显示；planned/authorized 标签行 = guard/routing artifact 证据）。
    """
    if row.cost_class != COST_UNKNOWN:
        return True
    if row.fallback not in (FALLBACK_NOT_USED, FALLBACK_UNKNOWN):
        return True
    if row.model != DISPLAY_UNKNOWN or row.provider != DISPLAY_UNKNOWN:
        return True
    if row.planned:
        return True
    if row.agent == "hermes" and read_json(output_dir, ARTIFACT_COST_GUARD) is not None:
        return True
    if row.agent == "workbuddy" and read_json(output_dir, ARTIFACT_WORKBUDDY_ROUTING) is not None:
        return True
    if row.agent == "codex" and load_observation(output_dir, "codex") is not None:
        return True
    return False


def render_row_line(row: CostRow, agent_display: str) -> str:
    """单行紧凑文本（Requirement 16 target density；测试/终端复用处）。

    格式：<Agent>  <Cost Class>  <model> (<provider>) [Planned: <planned>]
    provider 缺失时不输出括号段；模型缺失 -> "—"。planned 仅在 actual 不可证
    且存在 planned 证据时附加（以 "Planned:" 显式标签与 actual 区分）。
    """
    model_part = row.model
    if row.provider != DISPLAY_UNKNOWN and model_part != DISPLAY_UNKNOWN:
        model_part = f"{model_part} ({row.provider})"
    line = f"{agent_display:<10} {row.cost_class:<10} {model_part}"
    if row.planned:
        line = f"{line}  | Planned: {row.planned}"
    return line


def normalize_row_for_test(row: CostRow) -> dict[str, Any]:
    """测试辅助：把 CostRow 转 dict（断言友好；非 UI 路径）。"""
    return {
        "agent": row.agent,
        "model": row.model,
        "provider": row.provider,
        "cost_class": row.cost_class,
        "fallback": row.fallback,
        "planned": row.planned,
        "detail": row.detail,
    }
