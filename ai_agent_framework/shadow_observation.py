"""AAF v0.5 A2 — Shadow observation for the Hermes stage（observation-only bypass wiring）。

TASK: AAF-v0.5-A2-SHADOW-ROUTING-002。本模块把 A2-001 的 pure shadow
selector 接入 Hermes stage 的旁路观察流程：每次 Hermes 执行时计算并保存
「如果 Shadow Routing 有执行权，会选择谁」的可审计记录，**绝不改变真实
Hermes model / provider / command**。

消费的既有契约（复用，不复制、不发明）：
- ``shadow_routing.select_shadow_candidate`` / ``decision_to_dict``（A2-001 纯选择引擎）。
- ``model_registry.baseline_registry``（A1 有证据基线 registry；未验证维度
  一律 UNKNOWN——绝不虚构真实模型资格 / 健康 / capability）。
- ``risk_contract``（RISK_CLASSES / ROLE_EXECUTOR）。
- ``model_observation``：actual model/provider 的现有单一 authority
  （``model_observation.json`` 观测记录；本模块只消费调用方传入的观测 dict，
  自身零 discovery、零 CLI、零网络、零 LLM 调用）。
- ``cost_guard.ENV_MODEL / ENV_PROVIDER``：只读取（facts）——若 AAF_HERMES_MODEL
  / AAF_HERMES_PROVIDER 显式覆盖存在，它才是实际 invocation 的模型/provider
  （adapters.run_agent 透传 -m / --provider），观测如实记录覆盖值并注明来源。

Risk 来源纪律（Requirement 3）：
- 优先复用当前已有的 authoritative risk source。**当前 runtime 没有已接入的
  authoritative risk source**（risk_contract 是 foundation-only，live 执行路径
  零调用——A1 声明「本任务不把分类接入 live 执行」）。
- 因此生产 resolution 明确返回 ``RISK_UNAVAILABLE`` + 理由，**不发明 heuristic、
  不额外调用 LLM**；artifact 记录 risk=null + risk_source=RISK_UNAVAILABLE +
  no-decision reason（fail-safe）。
- 调用方（未来权威 wiring / 测试）可显式传入 ``risk_class`` / ``risk_source``，
  此时本模块按 A1/A2 契约计算完整 shadow decision——功能完整，但生产路径在
  risk 不可证明时保持 no-decision。

Registry 纪律（Requirement 4）：registry 缺省 = A1 ``baseline_registry()``
（有证据的契约事实，未验证 = UNKNOWN）；绝不为了产生结果而虚构资格 /
健康 / capability。对基线 registry，选择器如实返回 NO_SHADOW_CANDIDATE。

执行纪律（Requirement 5/6/9）：
- 本模块不修改 Hermes ``-m``、provider override、Paid Guard、runner 命令、
  fallback 或任何 live invocation；唯一副作用是写入 audit artifact。
- 不实现 A3 自动路由 / fallback / health / quarantine。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import cost_guard as cost_guard_mod
from . import model_registry as model_registry_mod
from .risk_contract import RISK_CLASSES, ROLE_EXECUTOR
from .shadow_routing import decision_to_dict, select_shadow_candidate

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "shadow_observation.json"

# 本任务只接入 Hermes stage（Requirement 1；WorkBuddy / Codex 不产生 shadow artifact）
STAGE_AGENT_HERMES = "hermes"

# risk 可用性 token（Requirement 3：RISK_UNAVAILABLE / 等效 no-decision）
RISK_UNAVAILABLE = "RISK_UNAVAILABLE"

# AAF-v0.5-A2-SHADOW-ROUTING-003：TASK Risk 字段的固定 provenance 描述（Planner
# 显式声明的结构化 risk；runner 解析 immutable TASK.snapshot.md 的顶层 Risk 字段
# 后以此作为 risk_source——绝不从 TASK prose / Task Name / Route / 路径推断）。
TASK_RISK_SOURCE = (
    "TASK.Risk field — planner-declared explicit risk in the immutable "
    "TASK.snapshot.md (validated against risk_contract.RISK_CLASSES; no "
    "inference from prose/name/route/path)"
)

# actual vs shadow 一致性 token（Requirement 2：actual vs shadow 是否一致）
MATCH_SAME = "SAME"
MATCH_DIFFERENT = "DIFFERENT"
MATCH_NO_SHADOW_DECISION = "NO_SHADOW_DECISION"
MATCH_ACTUAL_UNKNOWN = "ACTUAL_UNKNOWN"

# 固定语义标记（Requirement 2：authoritative=false / execution_affected=false）
AUTHORITATIVE = False
EXECUTION_AFFECTED = False

AUTHORITY_STATEMENT = (
    "shadow_observation.json is a non-authoritative observation artifact: it "
    "records what Shadow Routing WOULD select if it had execution authority. "
    "It never alters the real Hermes model/provider/command, never triggers "
    "extra model/provider invocations, never modifies the Paid Guard, and "
    "never falls back to another model."
)

# 默认 registry 来源描述（A1 契约；有证据事实；未验证维度 = UNKNOWN）
_DEFAULT_REGISTRY_SOURCE = (
    "model_registry.baseline_registry() (A1 contract; evidence-backed facts; "
    "unverified dimensions are UNKNOWN — no fabricated qualification/health/capability)"
)

# 生产 risk resolution 的固定理由（Requirement 3）
_RISK_UNAVAILABLE_REASON = (
    "no authoritative runtime risk source is wired for this stage "
    "(risk_contract is foundation-only; live execution paths call it zero times). "
    "Shadow observation does not invent heuristics and does not invoke an LLM "
    "for risk classification — fail-safe no-decision."
)

_REQUIRED_KEYS = (
    "schema_version",
    "stage_agent",
    "role",
    "authoritative",
    "execution_affected",
    "generated_at",
    "actual_model",
    "actual_provider",
    "risk_class",
    "risk_source",
    "registry_source",
    "registry_entry_count",
    "decision",
    "selected_candidate",
    "no_decision_reason",
    "actual_vs_shadow",
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_stage_risk(agent: str) -> tuple[None, str, str]:
    """解析 stage 的 authoritative risk 来源。

    当前 runtime 没有已接入的 authoritative risk source → 固定返回
    ``(None, RISK_UNAVAILABLE, reason)``（fail-safe；不发明、不调用 LLM）。
    未来权威 wiring 存在时，此函数是唯一需要更新的 resolution 点。
    """
    return None, RISK_UNAVAILABLE, (
        f"{_RISK_UNAVAILABLE_REASON} (stage_agent={agent!r})"
    )


def _actual_identity(
    observation: dict | None,
    agent: str,
) -> tuple[str | None, str | None, str | None, list[str]]:
    """actual model/provider 解析（事实优先：显式 invocation 覆盖 > 观测）。

    - ``AAF_HERMES_MODEL`` / ``AAF_HERMES_PROVIDER`` 存在 → 它们才是实际
      invocation 的模型/provider（adapters.run_agent 透传 -m / --provider），
      如实记录并注明来源（读取 env 是 observation，不是 mutation）。
    - 否则使用 model observation（model_observation.json 单一 authority）。
    - 观测缺失 / 失败 → (None, None) + note（UNKNOWN 就是 UNKNOWN，不虚构）。
    """
    notes: list[str] = []
    ov_model = os.environ.get(cost_guard_mod.ENV_MODEL, "").strip() or None
    ov_provider = os.environ.get(cost_guard_mod.ENV_PROVIDER, "").strip() or None
    if ov_model:
        notes.append(
            f"actual model/provider from invocation override "
            f"{cost_guard_mod.ENV_MODEL}={ov_model!r}"
            f"{f' / {cost_guard_mod.ENV_PROVIDER}={ov_provider!r}' if ov_provider else ''}"
            " (adapters.run_agent passes -m/--provider verbatim)"
        )
        return ov_model, ov_provider, "invocation_env_override", notes
    if observation is None:
        notes.append(
            "model observation unavailable — actual model/provider UNKNOWN "
            "(UNKNOWN is recorded honestly; nothing is invented)"
        )
        return None, None, None, notes
    model = observation.get("model")
    provider = observation.get("provider")
    if not model:
        notes.append(
            "model observation reported no model — actual model/provider "
            "UNKNOWN (discovery_status="
            f"{observation.get('discovery_status') or 'UNKNOWN'})"
        )
    return model or None, provider or None, observation.get("model_source"), notes


def _compare_actual_vs_shadow(
    actual_model: str | None,
    actual_provider: str | None,
    selected: str | None,
) -> str:
    """actual vs shadow 一致性 token（确定性）。

    - 无 shadow decision / 无 selected candidate → NO_SHADOW_DECISION。
    - actual model 未知 → ACTUAL_UNKNOWN（无法比较，诚实标注）。
    - actual key（``model@provider`` 或 ``model``）== selected → SAME；否则 DIFFERENT。
    """
    if selected is None:
        return MATCH_NO_SHADOW_DECISION
    if actual_model is None:
        return MATCH_ACTUAL_UNKNOWN
    actual_key = (
        f"{actual_model}@{actual_provider}" if actual_provider else actual_model
    )
    return MATCH_SAME if actual_key == selected else MATCH_DIFFERENT


def build_shadow_observation(
    agent: str,
    output_dir: Path | str,
    *,
    observation: dict | None = None,
    risk_class: str | None = None,
    risk_source: str | None = None,
    registry: dict[str, model_registry_mod.RegistryEntry] | None = None,
    registry_source: str | None = None,
) -> dict:
    """构造 Hermes shadow observation 记录（纯构造；唯一 I/O = 由 save 写盘）。

    参数：
    - ``agent``：stage agent（本任务只接 hermes；其他 agent 由调用方过滤）。
    - ``observation``：model observation 记录（model_observation.observe_stage
      的返回；actual model/provider 的事实来源）。
    - ``risk_class``：显式 authoritative risk（RISK_CLASSES 成员）。None →
      risk 不可用 → 明确 no-decision（RISK_UNAVAILABLE），不调用选择器。
    - ``risk_source``：risk_class 的来源描述（risk_class 提供时必须提供）。
    - ``registry``：候选 registry（A1 ``RegistryEntry`` dict）。缺省 =
      ``baseline_registry()``（有证据契约；未验证 = UNKNOWN）。
    - ``registry_source``：registry 来源描述（缺省 = 默认 A1 契约描述）。

    校验 fail closed（与 A2-001 一致）：未知 risk_class / 空 agent → ValueError；
    registry 内值不是 RegistryEntry 由选择器按 UNSUPPORTED 可审计排除。
    """
    if not (isinstance(agent, str) and agent.strip()):
        raise ValueError("agent must be a non-empty string")
    if risk_class is not None and risk_class not in RISK_CLASSES:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (allowed: {RISK_CLASSES})"
        )
    if risk_class is not None and risk_source is None:
        raise ValueError(
            "risk_source must be provided when an explicit risk_class is supplied"
        )

    if registry is None:
        registry = model_registry_mod.baseline_registry()
    if registry_source is None:
        registry_source = _DEFAULT_REGISTRY_SOURCE

    actual_model, actual_provider, actual_source, notes = _actual_identity(
        observation, agent
    )

    if risk_class is None:
        _, risk_status, risk_detail = resolve_stage_risk(agent)
        decision = None
        selected = None
        no_decision_reason = f"{risk_status}: {risk_detail}"
        notes.append(
            "no shadow decision computed: risk unavailable (fail-safe no-decision)"
        )
    else:
        risk_status = risk_source or "explicit caller-supplied risk"
        decision_obj = select_shadow_candidate(
            risk_class, ROLE_EXECUTOR, agent, registry
        )
        decision = decision_to_dict(decision_obj)
        selected = decision.get("selected")
        no_decision_reason = decision.get("no_candidate_reason")
        if selected is None:
            notes.append(
                "shadow decision computed but no eligible candidate — "
                "explicit NO_SHADOW_CANDIDATE (no forced choice, no fallback)"
            )

    record = {
        "schema_version": SCHEMA_VERSION,
        "authority": AUTHORITY_STATEMENT,
        "stage_agent": agent,
        "role": ROLE_EXECUTOR,
        "authoritative": AUTHORITATIVE,
        "execution_affected": EXECUTION_AFFECTED,
        "generated_at": _now_iso(),
        "observation_ref": str(Path(output_dir) / "model_observation.json"),
        "actual_model": actual_model,
        "actual_provider": actual_provider,
        "actual_model_source": actual_source,
        "risk_class": risk_class,
        "risk_source": risk_status,
        "risk_source_detail": None if risk_class is not None else _RISK_UNAVAILABLE_REASON,
        "registry_source": registry_source,
        "registry_entry_count": len(registry),
        "decision": decision,
        "selected_candidate": selected,
        "no_decision_reason": no_decision_reason,
        "actual_vs_shadow": _compare_actual_vs_shadow(
            actual_model, actual_provider, selected
        ),
        "notes": notes,
    }
    validate_shadow_observation(record)
    return record


def validate_shadow_observation(record: dict) -> None:
    """Schema 契约校验（fail closed）：必需字段存在且语义标记固定为 False。

    authoritative / execution_affected 必须是 False（非权威、零执行影响是
    本 artifact 的固定语义；任何 True 都是契约违规）。
    """
    if not isinstance(record, dict):
        raise ValueError("shadow observation record must be a mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in record]
    if missing:
        raise ValueError(f"shadow observation missing required keys: {missing}")
    if record["authoritative"] is not False:
        raise ValueError("authoritative must be False (observation-only artifact)")
    if record["execution_affected"] is not False:
        raise ValueError("execution_affected must be False (zero execution effect)")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported shadow observation schema_version: "
            f"{record.get('schema_version')!r}"
        )


def save_shadow_observation(output_dir: Path | str, record: dict) -> Path:
    """原子写 artifact（同目录 tmp + os.replace，与 model_observation 约定一致）。"""
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


def load_shadow_observation(output_dir: Path | str) -> dict | None:
    """读取 artifact；缺失 / 损坏 → None（不抛出；辅助审计/测试读取）。"""
    path = Path(output_dir) / ARTIFACT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def observe_shadow_stage(
    output_dir: Path | str,
    agent: str,
    *,
    observation: dict | None = None,
    risk_class: str | None = None,
    risk_source: str | None = None,
    registry: dict[str, model_registry_mod.RegistryEntry] | None = None,
    registry_source: str | None = None,
) -> dict | None:
    """Runner 用的单入口：build + save（非阻塞；任何失败 → None）。

    与 ``model_observation.observe_stage`` 同一双保险模式：telemetry 失败
    绝不影响 Agent 执行。shadow path 自身不发起任何 CLI / provider / LLM
    调用——只消费传入的 observation 并写一个 JSON 文件。
    """
    try:
        record = build_shadow_observation(
            agent,
            output_dir,
            observation=observation,
            risk_class=risk_class,
            risk_source=risk_source,
            registry=registry,
            registry_source=registry_source,
        )
        save_shadow_observation(output_dir, record)
        return record
    except Exception:  # noqa: BLE001 — 观测失败不得影响执行
        return None
