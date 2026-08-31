"""AAF v0.5 A3 — Active routing for the Hermes stage (minimal LOW-risk free slice)。

TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001
启动 A3 的最小 active-routing slice：仅当 Hermes executor task 显式声明
Risk: LOW，且现有 selector 选出已 QUALIFIED 的 LOCAL_FREE/FREE candidate 时，
该 shadow decision 升级为**真实** Hermes model/provider 选择。

本模块与 A2 shadow observation 的分工（Requirement 6/7）：
- ``shadow_observation``（A2）= hypothetical / 非权威（authoritative=false /
  execution_affected=false）：只记录「如果 shadow 有执行权会选谁」，永不改变执行。
- ``active_routing``（A3，本模块）= **authoritative** routing decision：
  runner 的 Hermes stage 在 Paid Guard 求值与真实 invocation 之前消费本模块，
  routing_applied=true 时通过 ``AAF_HERMES_MODEL`` / ``AAF_HERMES_PROVIDER`` /
  ``AAF_HERMES_BASE_URL`` 显式覆盖把真实 invocation 指到所选候选（adapters
  run_agent 透传 ``-m`` / ``--provider``；base_url 是 registry evidence 端点事实，
  供 A0 guard 以既有 loopback 判定识别 LOCAL_FREE）。

复用纪律（Requirement 1）：**不创建第二套路由判断**——
- 候选筛选 = 现有 ``shadow_routing.select_shadow_candidate``（A2-001 引擎原样调用）。
- Risk 词汇 = ``risk_contract.RISK_CLASSES``（唯一 authority；缺失 =
  RISK_UNAVAILABLE，missing ≠ LOW）。
- Registry = ``model_registry.baseline_registry()``（A1 有证据基线；未验证维度
  一律 UNKNOWN）。
- Paid Guard（A0）= 不变；本模块只提供 endpoint 事实（base_url），分类逻辑零改动。

Activation gates（Requirement 2/4，全部必须满足才 routing_applied=true）：
- stage_agent == "hermes"
- role == "executor"
- 显式 Risk == LOW（None / MEDIUM / HIGH / CRITICAL → 不生效）
- selector 返回 eligible candidate（selected 非 None）
- selected candidate cost_class ∈ FREE_OF_COST_CLASSES（LOCAL_FREE/FREE/FREE_PROMO）
- selected candidate qualification.status == QUALIFIED（防御性复核；
  selector 经 is_usable_candidate 已保证）

No silent fallback（Requirement 5）：本模块**不存在** fallback 分支；
fallback_attempted 恒为 False（fixed semantic，validate fail-closed）。
若 routing_applied 后真实 invocation 失败，runner 如实产生 FRAMEWORK_ERROR
（链中断 → WAITING），绝不自动改用 deepseek 或其他模型。

范围边界（Requirement 9，显式 anti-pullback）：
不实现 WorkBuddy/Codex routing、MEDIUM/HIGH 自动模型选择、automatic fallback、
health polling / quarantine、automatic qualification promotion、A4-A6。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import cost_guard as cost_guard_mod
from . import model_registry as model_registry_mod
from .risk_contract import RISK_CLASSES, RISK_LOW, ROLE_EXECUTOR
from .shadow_routing import select_shadow_candidate

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "active_routing.json"

# 本模块只接入 Hermes stage（Requirement 2：agent = hermes）
STAGE_AGENT_HERMES = "hermes"

# 语义标记：与 A2 shadow（authoritative=false）明确区分（Requirement 7）——
# 本 artifact 是真实 routing authority 的决策记录（authoritative=true）；
# routing_applied 表达「本次执行是否真的被本决策改变」。
AUTHORITATIVE = True

DECISION_KIND = "active_routing"

AUTHORITY_STATEMENT = (
    "active_routing.json is the AUTHORITATIVE routing decision record for the "
    "Hermes stage (A3, TASK: AAF-v0.5-A3-HERMES-FREE-ROUTING-001): when "
    "routing_applied=true it DIRECTLY selects the real Hermes model/provider "
    "for this execution (via AAF_HERMES_MODEL / AAF_HERMES_PROVIDER / "
    "AAF_HERMES_BASE_URL invocation overrides consumed by adapters.run_agent and "
    "cost_guard). It reuses the existing A2 selector (shadow_routing) and A1 "
    "Registry/Risk contracts — no second routing judgment system. "
    "fallback_attempted is always false: no fallback mechanism exists. "
    "Contrast with shadow_observation.json (hypothetical, authoritative=false)."
)

# risk 可用性 token（与 shadow_observation 同一词汇；missing ≠ LOW）
RISK_UNAVAILABLE = "RISK_UNAVAILABLE"

_DEFAULT_REGISTRY_SOURCE = (
    "model_registry.baseline_registry() (A1 contract; evidence-backed facts; "
    "unverified dimensions are UNKNOWN — no fabricated qualification/health/capability)"
)

# ---------------------------------------------------------------------------
# 决策 reason token（确定性；可审计）
# ---------------------------------------------------------------------------

REASON_APPLIED = "active_route_applied_low_free_qualified"
REASON_RISK_UNAVAILABLE = "RISK_UNAVAILABLE"
REASON_RISK_NOT_LOW = "RISK_NOT_LOW"
REASON_ROLE_NOT_EXECUTOR = "ROLE_NOT_EXECUTOR"
REASON_AGENT_NOT_HERMES = "AGENT_NOT_HERMES"
REASON_NO_ELIGIBLE = "NO_SHADOW_CANDIDATE"
REASON_SELECTED_NOT_FREE = "SELECTED_NOT_FREE"
REASON_SELECTED_NOT_QUALIFIED = "SELECTED_NOT_QUALIFIED"

_REQUIRED_KEYS = (
    "schema_version",
    "decision_kind",
    "authority",
    "authoritative",
    "stage_agent",
    "role",
    "risk_class",
    "risk_source",
    "registry_source",
    "candidates_considered",
    "excluded",
    "eligible",
    "selected",
    "routing_applied",
    "routed_model",
    "routed_provider",
    "routed_base_url",
    "configured_model",
    "configured_provider",
    "reason",
    "fallback_attempted",
    "generated_at",
)

_FALLBACK_ATTEMPTED = False  # fixed semantic（Requirement 5）：本模块无 fallback


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _env_notes(record: dict) -> list[str]:
    """env 覆盖说明（仅当 applied 时非空）。"""
    notes = []
    if record["routing_applied"]:
        parts = [f"{cost_guard_mod.ENV_MODEL}={record['routed_model']!r}"]
        if record.get("routed_provider"):
            parts.append(f"{cost_guard_mod.ENV_PROVIDER}={record['routed_provider']!r}")
        if record.get("routed_base_url"):
            parts.append(f"{cost_guard_mod.ENV_BASE_URL}={record['routed_base_url']!r}")
        notes.append(
            "active routing applied: invocation override set "
            + " / ".join(parts)
            + " (adapters.run_agent passes -m/--provider verbatim; "
            "cost_guard.classify_cost recognizes LOCAL_FREE via the existing "
            "loopback check on the evidence-backed base_url)"
        )
    return notes


def decide_active_route(
    risk_class: str | None,
    role: str,
    stage_agent: str,
    registry: dict[str, model_registry_mod.RegistryEntry],
    *,
    risk_source: str | None = None,
    registry_source: str | None = None,
    configured_model: str | None = None,
    configured_provider: str | None = None,
) -> dict:
    """A3 active-routing 决策（复用现有 selector；不创建第二套路由判断）。

    参数：
    - ``risk_class``：TASK 显式声明的 Risk（RISK_CLASSES 成员）；None =
      RISK_UNAVAILABLE（missing ≠ LOW → 不生效）。
    - ``role``：stage 角色（必须 executor 才可能生效）。
    - ``stage_agent``：stage agent（必须 hermes 才可能生效）。
    - ``registry``：候选 registry（A1 RegistryEntry dict；缺省建议
      ``baseline_registry()``——本函数要求显式传入，与 shadow_observation
      的默认值语义保持一致由调用方决定）。
    - ``risk_source``：risk_class 的来源描述（显式 risk 时应提供）。
    - ``configured_model`` / ``configured_provider``：未 routing 时的既有
      configured Hermes model/provider（runner 从 cost_guard resolution 传入；
      供审计记录「actual selected model/provider」；缺失 → None 如实记录）。

    返回 machine-readable record（可直接 ``save_active_routing`` 落盘）。
    校验 fail closed：未知 risk_class / 非法 role / 空 agent → ValueError。
    registry 内值不是 RegistryEntry 由 selector 按 UNSUPPORTED 可审计排除。
    """
    if not (isinstance(role, str) and role.strip()):
        raise ValueError("role must be a non-empty string")
    if not (isinstance(stage_agent, str) and stage_agent.strip()):
        raise ValueError("stage_agent must be a non-empty string")
    if risk_class is not None and risk_class not in RISK_CLASSES:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})"
        )
    if risk_class is not None and risk_source is None:
        raise ValueError(
            "risk_source must be provided when an explicit risk_class is supplied"
        )
    if not isinstance(registry, dict):
        raise ValueError(f"registry must be a dict, got {type(registry).__name__}")
    if registry_source is None:
        registry_source = _DEFAULT_REGISTRY_SOURCE

    # --- 复用现有 selector（A2-001 引擎；同一套候选筛选，不另起炉灶） ---
    decision = None
    selected = None
    excluded: list[dict[str, str]] = []
    considered: list[str] = []
    eligible: list[str] = []
    if risk_class is not None:
        decision_obj = select_shadow_candidate(
            risk_class, role, stage_agent, registry
        )
        selected = decision_obj.selected
        considered = list(decision_obj.candidates_considered)
        excluded = [
            {"candidate": r.candidate, "reason": r.reason}
            for r in sorted(decision_obj.excluded, key=lambda r: (r.candidate, r.reason))
        ]
        eligible = list(decision_obj.eligible)

    # --- Activation gates（顺序确定性；第一个失败的 gate 决定 reason） ---
    routing_applied = False
    routed_model: str | None = None
    routed_provider: str | None = None
    routed_base_url: str | None = None
    reason: str | None = None

    if stage_agent != STAGE_AGENT_HERMES:
        reason = f"{REASON_AGENT_NOT_HERMES}: active routing applies only to agent={STAGE_AGENT_HERMES!r}"
    elif role != ROLE_EXECUTOR:
        reason = f"{REASON_ROLE_NOT_EXECUTOR}: active routing applies only to role={ROLE_EXECUTOR!r}"
    elif risk_class is None:
        reason = (
            f"{REASON_RISK_UNAVAILABLE}: no explicit Risk declared in TASK — "
            "missing != LOW (fail-safe no routing)"
        )
    elif risk_class != RISK_LOW:
        reason = (
            f"{REASON_RISK_NOT_LOW}: explicit Risk={risk_class!r} — active routing "
            "applies only to explicit LOW (MEDIUM/HIGH/CRITICAL keep the "
            "configured Hermes model/provider)"
        )
    elif selected is None:
        reason = (
            f"{REASON_NO_ELIGIBLE}: selector produced no eligible candidate — "
            "no forced choice, no routing"
        )
    else:
        entry = registry[selected]
        if entry.cost_class not in model_registry_mod.FREE_OF_COST_CLASSES:
            reason = (
                f"{REASON_SELECTED_NOT_FREE}: selected candidate {selected!r} "
                f"cost_class={entry.cost_class!r} not in "
                f"FREE_OF_COST_CLASSES={sorted(model_registry_mod.FREE_OF_COST_CLASSES)} "
                "— free routing never applies to a non-free candidate"
            )
        elif entry.qualification.status != model_registry_mod.QUAL_STATUS_QUALIFIED:
            # 防御性 gate：selector（is_usable_candidate）已保证 qualified；
            # 此处双保险，绝不在 qualification 不满足时 routing。
            reason = (
                f"{REASON_SELECTED_NOT_QUALIFIED}: selected candidate {selected!r} "
                f"qualification.status={entry.qualification.status!r} != "
                f"{model_registry_mod.QUAL_STATUS_QUALIFIED!r} — no routing"
            )
        else:
            routing_applied = True
            routed_model = entry.model
            routed_provider = entry.provider
            routed_base_url = entry.base_url
            reason = (
                f"{REASON_APPLIED}: explicit Risk=LOW + selector eligible + "
                f"selected {selected!r} cost_class={entry.cost_class!r} "
                f"(LOCAL_FREE/FREE) + qualification=QUALIFIED → active route "
                f"to {selected!r}"
            )

    record = {
        "schema_version": SCHEMA_VERSION,
        "decision_kind": DECISION_KIND,
        "authority": AUTHORITY_STATEMENT,
        "authoritative": AUTHORITATIVE,
        "stage_agent": stage_agent,
        "role": role,
        "risk_class": risk_class,
        "risk_source": (
            risk_source if risk_class is not None else RISK_UNAVAILABLE
        ),
        "registry_source": registry_source,
        "candidates_considered": considered,
        "excluded": excluded,
        "eligible": eligible,
        "selected": selected,
        "routing_applied": routing_applied,
        "routed_model": routed_model,
        "routed_provider": routed_provider,
        "routed_base_url": routed_base_url,
        "configured_model": configured_model,
        "configured_provider": configured_provider,
        "reason": reason,
        "fallback_attempted": _FALLBACK_ATTEMPTED,
        "generated_at": _now_iso(),
        "notes": _env_notes(
            {
                "routing_applied": routing_applied,
                "routed_model": routed_model,
                "routed_provider": routed_provider,
                "routed_base_url": routed_base_url,
            }
        ),
    }
    validate_active_routing(record)
    return record


# ---------------------------------------------------------------------------
# Schema 校验（fail closed）
# ---------------------------------------------------------------------------


def validate_active_routing(record: dict) -> None:
    """Schema 契约校验（fail closed）。

    - 必需字段齐全；schema_version == SCHEMA_VERSION。
    - authoritative 必须是 True（本 artifact = authoritative routing decision；
      与 shadow 的 False 固定语义区分——任何 False 都是契约违规）。
    - fallback_attempted 必须是 False（本模块无 fallback；任何 True 都是违规）。
    - routing_applied=True → routed_model 必须非空（不能声明生效却无模型）。
    """
    if not isinstance(record, dict):
        raise ValueError("active routing record must be a mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in record]
    if missing:
        raise ValueError(f"active routing record missing required keys: {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported active routing schema_version: "
            f"{record.get('schema_version')!r}"
        )
    if record["authoritative"] is not True:
        raise ValueError("authoritative must be True (authoritative routing decision)")
    if record["fallback_attempted"] is not False:
        raise ValueError(
            "fallback_attempted must be False (no fallback mechanism exists — "
            "requirement: no silent fallback)"
        )
    if record["routing_applied"] is True and not (
        isinstance(record.get("routed_model"), str)
        and record["routed_model"].strip()
    ):
        raise ValueError(
            "routing_applied=True requires a non-empty routed_model "
            "(cannot claim an applied route without an actual model)"
        )
    if record.get("risk_class") is not None and not record.get("risk_source"):
        raise ValueError(
            "risk_source must be provided when risk_class is explicitly set"
        )


# ---------------------------------------------------------------------------
# 持久化（原子写；与 shadow_observation / model_observation 同一约定）
# ---------------------------------------------------------------------------


def save_active_routing(output_dir: Path | str, record: dict) -> Path:
    """原子写 artifact（同目录 tmp + os.replace）。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ARTIFACT_FILENAME
    tmp = output_dir / f"{ARTIFACT_FILENAME}.tmp-{os.getpid()}"
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def load_active_routing(output_dir: Path | str) -> dict | None:
    """读取 artifact；缺失 / 损坏 → None（不抛出；辅助审计/测试读取）。"""
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Env 覆盖 apply / restore（runner Hermes stage 使用）
# ---------------------------------------------------------------------------


def apply_routing_env(record: dict) -> dict[str, str | None]:
    """把已 applied 的 routed model/provider/base_url 写入 env 覆盖。

    只设置非空值（None 字段不设置、不污染）；返回 {var: 旧值或 None} 供
    ``restore_routing_env`` 精确还原（old None = 调用前不存在 → restore 时删除）。

    调用前提：``record['routing_applied'] is True``（调用方负责；违反 →
    ValueError，fail closed —— 未生效的决策不得触碰 env）。
    """
    if not record.get("routing_applied"):
        raise ValueError(
            "apply_routing_env requires a routing_applied=True record "
            "(never touch invocation env for a non-applied decision)"
        )
    saved: dict[str, str | None] = {}
    values = {
        cost_guard_mod.ENV_MODEL: record.get("routed_model"),
        cost_guard_mod.ENV_PROVIDER: record.get("routed_provider"),
        cost_guard_mod.ENV_BASE_URL: record.get("routed_base_url"),
    }
    for var, value in values.items():
        if value is None:
            continue
        saved[var] = os.environ.get(var)
        os.environ[var] = value
    return saved


def restore_routing_env(saved: dict[str, str | None]) -> None:
    """还原 apply_routing_env 之前的 env 状态（旧值 None → 删除该变量）。"""
    for var, old in saved.items():
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old
