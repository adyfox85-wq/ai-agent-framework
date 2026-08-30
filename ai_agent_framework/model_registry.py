"""AAF v0.5 A1 — Model Registry Contract（foundation only）。

与 ``model_observation.py``（v0.4 TASK-010 事实层）的分工：
- ``model_observation`` = 只读运行时发现（per-run discovery artifact：
  ``model_observation.json`` 记录「本次运行观测到的模型事实」）。
- ``model_registry``（本模块）= 候选模型 registry **契约**：A2/A3 路由
  消费的 schema、纯逻辑判定与**有证据支持的基线事实**。本模块不产生
  运行时 artifact、不发起任何进程 / 网络调用。

本任务范围边界（A1 foundation only）：
- 不激活任何自动模型选择 / 路由 / 切换 / fallback。
- 不做健康轮询 / 后台监控 / 动态隔离 / 自动降级。
- 不把 FREE 当作 available / stable / healthy / qualified / sufficient 的证据。
- 不发明未经证据验证的 capability tier / price / health / quota / stability /
  availability——未验证一律显式 UNKNOWN。

运行时约束（2026-08-30 用户观察，backlog RW-030）：
真实 Hermes v0.20.5 安装/使用中观察到——部分标记 FREE 的模型实际无法使用，
部分可用的 FREE 模型可能不稳定。因此 **FREE 只是价格/成本属性**：
本 registry 把 cost_class 与 runtime_qualification 严格分离，且
``is_usable_candidate`` 绝不从 FREE 推导（fail closed）。

术语复用：成本分类直接复用 ``model_observation.COST_CLASSES``
（LOCAL_FREE / FREE / FREE_PROMO / PAID / UNKNOWN），不另造词汇。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model_observation import (
    COST_CLASS_FREE,
    COST_CLASS_FREE_PROMO,
    COST_CLASS_LOCAL_FREE,
    COST_CLASS_UNKNOWN,
    COST_CLASSES,
)

# ---------------------------------------------------------------------------
# Schema 常量
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

# 能力层级（已决定的 v0.5 设计）：T0 最强 / 最高能力，T4 最轻 / 本地级。
# tier 表示能力，不代表价格。
CAP_TIER_T0 = "T0"
CAP_TIER_T1 = "T1"
CAP_TIER_T2 = "T2"
CAP_TIER_T3 = "T3"
CAP_TIER_T4 = "T4"
CAPABILITY_TIERS = (CAP_TIER_T0, CAP_TIER_T1, CAP_TIER_T2, CAP_TIER_T3, CAP_TIER_T4)

# T0 最强 → 数值最小；数值越小 = 能力越强（tier_satisfies 用）
TIER_STRENGTH_ORDER = {tier: i for i, tier in enumerate(CAPABILITY_TIERS)}

# 本地 / 远程 / 未知（执行类别；无证据 → unknown）
LOCALITY_LOCAL = "local"
LOCALITY_REMOTE = "remote"
LOCALITY_UNKNOWN = "unknown"
LOCALITIES = (LOCALITY_LOCAL, LOCALITY_REMOTE, LOCALITY_UNKNOWN)

# 运行时 qualification 词汇（最小且确定性；未来运行时观测填充，
# 本任务不实现轮询 / 监控 / 隔离）。
QUAL_STATUS_QUALIFIED = "qualified"
QUAL_STATUS_NOT_QUALIFIED = "not_qualified"
QUAL_STATUS_UNKNOWN = "unknown"
QUAL_STATUSES = (QUAL_STATUS_QUALIFIED, QUAL_STATUS_NOT_QUALIFIED, QUAL_STATUS_UNKNOWN)

# FREE 是一个价格/成本属性集合（成本维度）；绝不等于 qualification。
FREE_OF_COST_CLASSES = frozenset(
    (COST_CLASS_LOCAL_FREE, COST_CLASS_FREE, COST_CLASS_FREE_PROMO)
)

_KEY_SEPARATOR = "@"
AGENT_KEY_PREFIX = "agent:"


# ---------------------------------------------------------------------------
# 纯逻辑（确定性；无 I/O、无网络、无 LLM）
# ---------------------------------------------------------------------------


def canonical_key(model: str | None, provider: str | None) -> str:
    """条目唯一身份 key：``model@provider``；模型未知 → ``agent:<agent>``
    （由调用方用 applicable_agents[0] 构造，见 ``RegistryEntry.key``）。"""
    if model:
        if provider:
            return f"{model}{_KEY_SEPARATOR}{provider}"
        return model
    return AGENT_KEY_PREFIX + "unknown"


def free_of_cost(cost_class: str) -> bool:
    """成本维度判定：该 cost_class 是否属于 FREE 集合。与可用性无关。

    校验失败（未知 cost_class）→ ValueError（fail closed，未知不得视为免费）。
    """
    if cost_class not in COST_CLASSES:
        raise ValueError(f"invalid cost_class: {cost_class!r}")
    return cost_class in FREE_OF_COST_CLASSES


def tier_satisfies(candidate_tier: str | None, required_floor: str | None) -> bool:
    """能力充分性判定（纯函数；T0 最强）。

    - candidate 与 floor 都必须是已知 tier 才可能满足；
    - 任一为 None / 未知 → False（fail closed，未验证能力不得视为充分）。
    """
    if candidate_tier not in TIER_STRENGTH_ORDER:
        return False
    if required_floor not in TIER_STRENGTH_ORDER:
        return False
    return TIER_STRENGTH_ORDER[candidate_tier] <= TIER_STRENGTH_ORDER[required_floor]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeQualification:
    """运行时 qualification（独立于成本）。

    status 只允许 QUAL_STATUSES 三值；未观测 = unknown（显式）。
    evidence / observed_at 供未来运行时观测填充；本任务不产生观测。
    """

    status: str = QUAL_STATUS_UNKNOWN
    evidence: tuple[str, ...] = ()
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in QUAL_STATUSES:
            raise ValueError(f"invalid qualification status: {self.status!r}")
        for item in self.evidence:
            if not isinstance(item, str):
                raise ValueError(f"qualification evidence must be str, got {type(item).__name__}")


@dataclass(frozen=True)
class RegistryEntry:
    """模型 registry 条目。

    维度严格分离（互不推导）：
    - model/provider：身份
    - applicable_agents：适用的 agent/stage（空 = 未知/通用）
    - capability_tier：能力层级（None = UNKNOWN；不代表价格）
    - cost_class：成本分类（复用 model_observation.COST_CLASSES）
    - locality：local / remote / unknown
    - qualification：运行时 qualification（独立于成本）
    - evidence：非 UNKNOWN 事实的证据引用（repository/runtime 出处）
    """

    model: str | None
    provider: str | None
    applicable_agents: tuple[str, ...] = ()
    capability_tier: str | None = None
    cost_class: str = COST_CLASS_UNKNOWN
    locality: str = LOCALITY_UNKNOWN
    qualification: RuntimeQualification = field(default_factory=RuntimeQualification)
    evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.model is not None and not (isinstance(self.model, str) and self.model.strip()):
            raise ValueError("model must be a non-empty string or None")
        if self.provider is not None and not (isinstance(self.provider, str) and self.provider.strip()):
            raise ValueError("provider must be a non-empty string or None")
        if self.capability_tier is not None and self.capability_tier not in CAPABILITY_TIERS:
            raise ValueError(
                f"invalid capability_tier: {self.capability_tier!r} "
                f"(allowed: {CAPABILITY_TIERS} or None=UNKNOWN)"
            )
        if self.cost_class not in COST_CLASSES:
            raise ValueError(f"invalid cost_class: {self.cost_class!r}")
        if self.locality not in LOCALITIES:
            raise ValueError(f"invalid locality: {self.locality!r}")
        if not isinstance(self.qualification, RuntimeQualification):
            raise ValueError("qualification must be a RuntimeQualification")
        for name in ("applicable_agents", "evidence", "notes"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"{name} must be a tuple of str")

    def key(self) -> str:
        """条目唯一 key：``model@provider``；模型未知 → ``agent:<agent>``。"""
        if self.model:
            if self.provider:
                return f"{self.model}{_KEY_SEPARATOR}{self.provider}"
            return self.model
        if self.applicable_agents:
            return AGENT_KEY_PREFIX + self.applicable_agents[0]
        return AGENT_KEY_PREFIX + "unknown"


def is_usable_candidate(entry: RegistryEntry) -> bool:
    """候选可用性判定（确定性，fail closed）。

    仅当**同时**满足时才为可用候选：
      - capability_tier 已知（非 None），且
      - qualification.status == QUALIFIED。

    成本分类绝不参与：FREE 不隐含 qualified；UNKNOWN 成本不是 FREE；
    未验证的元数据（tier / qualification 未知）绝不静默变成可用候选。
    """
    return entry.capability_tier is not None and (
        entry.qualification.status == QUAL_STATUS_QUALIFIED
    )


# ---------------------------------------------------------------------------
# 序列化（纯；校验未知枚举 → ValueError，fail closed）
# ---------------------------------------------------------------------------


def entry_to_dict(entry: RegistryEntry) -> dict[str, Any]:
    return {
        "model": entry.model,
        "provider": entry.provider,
        "applicable_agents": list(entry.applicable_agents),
        "capability_tier": entry.capability_tier,
        "cost_class": entry.cost_class,
        "locality": entry.locality,
        "qualification": {
            "status": entry.qualification.status,
            "evidence": list(entry.qualification.evidence),
            "observed_at": entry.qualification.observed_at,
        },
        "evidence": list(entry.evidence),
        "notes": list(entry.notes),
    }


def entry_from_dict(data: dict[str, Any]) -> RegistryEntry:
    """从 dict 构造条目；缺失字段 → 默认 UNKNOWN；未知枚举 → ValueError。"""
    qual = data.get("qualification") or {}
    qualification = RuntimeQualification(
        status=qual.get("status", QUAL_STATUS_UNKNOWN),
        evidence=tuple(qual.get("evidence", [])),
        observed_at=qual.get("observed_at"),
    )
    return RegistryEntry(
        model=data.get("model"),
        provider=data.get("provider"),
        applicable_agents=tuple(data.get("applicable_agents", [])),
        capability_tier=data.get("capability_tier"),
        cost_class=data.get("cost_class", COST_CLASS_UNKNOWN),
        locality=data.get("locality", LOCALITY_UNKNOWN),
        qualification=qualification,
        evidence=tuple(data.get("evidence", [])),
        notes=tuple(data.get("notes", [])),
    )


def registry_to_dict(entries: dict[str, RegistryEntry]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": (
            "model_registry.py contract (A1); baseline facts are evidence-backed; "
            "unverified dimensions are UNKNOWN. cost_class and runtime_qualification "
            "are independent dimensions; FREE never implies qualified."
        ),
        "entries": {key: entry_to_dict(e) for key, e in entries.items()},
    }


def registry_from_dict(data: dict[str, Any]) -> dict[str, RegistryEntry]:
    """从 dict 重建 registry；schema 版本缺失/不支持 / key 与条目 key 不一致 → ValueError。

    schema_version 校验（fail closed）：
    - 缺失（``None``）→ ValueError（不承诺未声明版本的 registry 文档）。
    - 不等于 ``SCHEMA_VERSION`` 的值（含 999 等未来/未知版本、非 int 类型）→ ValueError。
    """
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise ValueError("registry dict must contain an 'entries' mapping")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported registry schema_version: {data.get('schema_version')!r} "
            f"(supported: {SCHEMA_VERSION})"
        )
    entries: dict[str, RegistryEntry] = {}
    for key, raw in data["entries"].items():
        entry = entry_from_dict(raw)
        if entry.key() != key:
            raise ValueError(f"entry key mismatch: dict key {key!r} != entry.key() {entry.key()!r}")
        entries[key] = entry
    return entries


# ---------------------------------------------------------------------------
# 基线事实（只填入 repository/runtime 证据支持的字段；其余 UNKNOWN）
# ---------------------------------------------------------------------------

# 证据引用锚点（本仓库 living docs / 真实 probe 记录）
_EVID_CAP002_PROBE = (
    "docs/internal/AAF_MASTER_BACKLOG.md CAP-002 — 2026-08-29 真实只读 probe "
    "（`hermes config get model` / `hermes config get auxiliary` / codebuddy / codex）"
)
_EVID_A0_REPORT = (
    "docs/internal/AAF-v0.5-A0-PAID-GUARD-001-REPORT.md §5/§10 — A0 resolution "
    "事实：Hermes 默认模型 deepseek-v4-flash 为 remote API；cost 元数据未暴露"
)


def baseline_entries() -> tuple[RegistryEntry, ...]:
    """A1 基线 registry 条目。

    规则：只填有证据的字段；capability tier / health / quota / stability /
    availability 未验证 → 一律 UNKNOWN（tier=None、qualification 默认 unknown）。
    """
    return (
        # Hermes 主模型（remote API；cost 未暴露）
        RegistryEntry(
            model="deepseek-v4-flash",
            provider="deepseek",
            applicable_agents=("hermes",),
            capability_tier=None,
            cost_class=COST_CLASS_UNKNOWN,
            locality=LOCALITY_REMOTE,
            evidence=(_EVID_CAP002_PROBE, _EVID_A0_REPORT),
            notes=(
                "remote API（base_url 空）→ locality=remote（A0 resolution 事实）",
                "cost_class=UNKNOWN（EXTERNAL_DYNAMIC_METADATA_REQUIRED）；A0 guard "
                "分类 PAID_OR_UNKNOWN = 未证明 FREE 的远程模型，不等于已核验 PAID",
                "capability tier 未验证 → UNKNOWN；FREE=healthy 不成立（RW-030）",
            ),
        ),
        # Hermes auxiliary.vision（本地 Ollama 端点）
        RegistryEntry(
            model="qwen2.5vl:3b",
            provider="custom",
            applicable_agents=("hermes",),
            capability_tier=None,
            cost_class=COST_CLASS_LOCAL_FREE,
            locality=LOCALITY_LOCAL,
            evidence=(_EVID_CAP002_PROBE,),
            notes=(
                "auxiliary.vision slot：provider=custom，base_url="
                "http://127.0.0.1:11434/v1 → local endpoint（LOCAL_FREE 证据）",
                "tier / qualification 未验证 → UNKNOWN",
            ),
        ),
        # Hermes auxiliary 文本槽位（本地 Ollama 端点）
        RegistryEntry(
            model="qwen3:4b",
            provider="custom",
            applicable_agents=("hermes",),
            capability_tier=None,
            cost_class=COST_CLASS_LOCAL_FREE,
            locality=LOCALITY_LOCAL,
            evidence=(_EVID_CAP002_PROBE,),
            notes=(
                "auxiliary compression/web_extract/title_generation/summarization "
                "slots：本地 Ollama 端点 → LOCAL_FREE",
                "tier / qualification 未验证 → UNKNOWN",
            ),
        ),
        # WorkBuddy/CodeBuddy：当前模型不由用户 config 暴露（身份本身 UNKNOWN）
        RegistryEntry(
            model=None,
            provider=None,
            applicable_agents=("workbuddy",),
            capability_tier=None,
            cost_class=COST_CLASS_UNKNOWN,
            locality=LOCALITY_UNKNOWN,
            evidence=(_EVID_CAP002_PROBE,),
            notes=(
                "`codebuddy config get model` 为空 → 当前模型由 CLI default / "
                "last-used 决定（runtime observation required）；不得推断填充",
                "cost / tier / qualification 均 UNKNOWN",
            ),
        ),
        # Codex：默认模型 server-side 决定，本地不可枚举
        RegistryEntry(
            model=None,
            provider=None,
            applicable_agents=("codex",),
            capability_tier=None,
            cost_class=COST_CLASS_UNKNOWN,
            locality=LOCALITY_UNKNOWN,
            evidence=(_EVID_CAP002_PROBE,),
            notes=(
                "~/.codex/config.toml 无 model key → 默认模型 server-side 决定、"
                "本地不可枚举（documented discoverability limitation）",
                "model catalog 不可由当前 CLI 枚举；cost / tier / qualification 均 UNKNOWN",
            ),
        ),
    )


def baseline_registry() -> dict[str, RegistryEntry]:
    """基线 registry（key → entry；key 唯一性由 dict 构造保证）。"""
    return {entry.key(): entry for entry in baseline_entries()}
