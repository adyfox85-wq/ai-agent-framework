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
    - base_url：候选 provider 的已知端点（None = 未验证/未知；本地端点证据
      是 A0 cost_guard 判定 LOCAL_FREE 的事实来源——A3 active routing 把已
      选 LOCAL_FREE 候选的 base_url 事实透传给 guard，绝不虚构）
    - applicable_agents：适用的 agent/stage（空 = 未知/通用）
    - capability_tier：能力层级（None = UNKNOWN；不代表价格）
    - cost_class：成本分类（复用 model_observation.COST_CLASSES）
    - locality：local / remote / unknown
    - qualification：运行时 qualification（独立于成本）
    - evidence：非 UNKNOWN 事实的证据引用（repository/runtime 出处）
    """

    model: str | None
    provider: str | None
    base_url: str | None = None
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
        if self.base_url is not None and not (isinstance(self.base_url, str) and self.base_url.strip()):
            raise ValueError("base_url must be a non-empty string or None")
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
        "base_url": entry.base_url,
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
        base_url=data.get("base_url"),
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

    schema_version 校验（fail closed，严格类型）：
    - 缺失（``None``）→ ValueError（不承诺未声明版本的 registry 文档）。
    - 类型不是真实 ``int``（bool / float / str / list / dict 等，即使值相等
      如 ``True``、``1.0``）→ ValueError，绝不静默强转。
    - 值不等于 ``SCHEMA_VERSION``（含 999 等未来/未知版本）→ ValueError。
    """
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise ValueError("registry dict must contain an 'entries' mapping")
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported registry schema_version: {schema_version!r} "
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
# 已接受的 AAF 执行/审查证据（TASK: AAF-v0.5-A2-SHADOW-ROUTING-004）：
# AAF-v0.5-A2-SHADOW-ROUTING-003-FIX-001 显式声明 Risk: HIGH，其 Hermes executor
# 真实以 deepseek-v4-flash@deepseek 运行、完整成功（SUCCESS）、WorkBuddy
# PASS_WITH_WARNING、Codex APPROVE（commit 5911d39）。风险契约要求 HIGH executor
# 至少 T2（risk_contract.RISK_FLOORS[HIGH].executor == "T2"），因此该证据只证明
# 最低已证能力 = T2；不推断 T1/T0、不推断永久健康、不改变 cost_class=UNKNOWN
# （成本元数据仍未暴露，独立维度）。observed_at = 证据被接受的运行时时间戳
# （run.json terminal SUCCESS + codex_result.json generated_at APPROVE）。
_EVID_A2_004_HERMES_T2 = (
    ".aaf/AAF-v0.5-A2-SHADOW-ROUTING-003-FIX-001/ (accepted AAF execution/review "
    "artifacts, commit 5911d39): TASK.snapshot.md declares Risk: HIGH; "
    "model_observation.json actual_model=deepseek-v4-flash / provider=deepseek "
    "(model_source=config); shadow_observation.json risk_class=HIGH with same "
    "actual model/provider; workbuddy_result.json verdict=PASS_WITH_WARNING; "
    "codex_result.json verdict=APPROVE; run.json status=SUCCESS — Hermes actually "
    "executed this HIGH task as deepseek-v4-flash@deepseek to acceptance, proving "
    "at least risk_contract T2 (HIGH executor floor); no T1/T0 inference"
)
# 上述证据被接受的时间戳（真实运行时证据，非本次构造的时间）：
# run.json timestamp == codex_result.json generated_at（Codex APPROVE 完成时刻）。
_EVID_A2_004_OBSERVED_AT = "2026-08-31T08:16:23"

# TASK: AAF-v0.5-A2PLUS-RW030-001（RW-030 最小 prerequisite slice）：
# qwen3:4b@custom 的隔离、非权威、真实 runtime qualification probe 证据。
# probe 只与真实本地 Ollama 端点（http://127.0.0.1:11434）通信（零外部/付费
# provider 调用），不改任何 Hermes config/model/provider（`hermes config get
# auxiliary` 只读确认身份 + `hermes config get model` 记录主模型仍为
# deepseek-v4-flash@deepseek）；受控 Risk: LOW executor-like task 经
# /v1/chat/completions 完成并产生预期结构化结果（HTTP 200 / finish_reason=stop /
# response model=qwen3:4b / 无超时无协议错误）。LOW probe 成功按风险契约只证明
# 最低 T4（RISK_FLOORS[LOW].executor == "T4"）；不推断 T3/T2/T1/T0。证据
# artifact 位于 .aaf（与 003-FIX-001 已接受证据同一存放约定，untracked）。
_EVID_RW030_001_PROBE = (
    ".aaf/AAF-v0.5-A2PLUS-RW030-001/probe/ (TASK: AAF-v0.5-A2PLUS-RW030-001, "
    "observed_at=2026-08-31T23:19:13+08:00): isolated non-authoritative runtime "
    "qualification probe against the REAL local Ollama endpoint "
    "http://127.0.0.1:11434 (zero external/paid provider calls) — /api/tags lists "
    "qwen3:4b (digest 359d7dd4..., 4.0B, Q4_K_M, capabilities "
    "completion/tools/thinking); `hermes config get auxiliary` confirms identity "
    "(compression/title_generation/web_extract/summarization = qwen3:4b, "
    "provider=custom, base_url=http://127.0.0.1:11434/v1) while `hermes config get "
    "model` records main model still deepseek-v4-flash@deepseek (probe changed "
    "nothing); controlled Risk: LOW executor-like task completed via "
    "/v1/chat/completions with the expected structured result "
    "(status=SUCCESS, commit=null, changed_files=[probe-ok], warnings=[]) — "
    "HTTP 200, finish_reason=stop, response model=qwen3:4b, no timeout / protocol "
    "error / execution failure. LOW probe success proves minimum T4 (LOW executor "
    "floor = T4); T3/T2/T1/T0 NOT inferred"
)
# 上述 probe 证据被接受的真实运行时时间戳（probe 完成时刻，来自 probe artifact）：
# qwen3_qualification_probe.json observed_at（terminated step4 + evidence write）。
_EVID_RW030_001_OBSERVED_AT = "2026-08-31T23:19:13+08:00"

# TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001（A4 prerequisite slice）：
# WorkBuddy/CodeBuddy 当前运行时支持的 model ID 列表（只读 CLI 事实）。
# 证据 = 真实只读 probe（.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/discovery/，
# observed_at=2026-09-02T01:23:05+08:00）：
#   - `codebuddy --version` → 2.141.0（codebuddy_version.txt）
#   - `codebuddy --help` → --model 帮助行 "Currently supported: (...)"
#     （codebuddy_help.txt 全文；discovery_facts.json models_documented_by_cli）
#   - `codebuddy config get model` → 空（当前模型仍由 CLI default/last-used 决定，
#     CodeBuddy Auto；config 不暴露）
#   - ~/.codebuddy/settings.json → 无 model/effort/remote/promo/multiplier key
# 该列表是 CLI 自身帮助文本（版本级静态元数据；刷新 = 重新 `codebuddy --help`），
# 不是 AAF 硬编码永久事实。hy4-preview-x 曾出现在 2026-08-29 帮助快照中，但
# 当前 runtime（2.141.0，2026-09-02 probe）帮助文本已不列出 → 不收录（当前
# runtime 不支持即不发明；Requirement 2）。
# RemoteConfig 源事实（Requirement 7）：当前 runtime 不可观测（--help 无
# remote economic-config 命令/flag；settings.json 无相关 key）→ 只登记
# "不可观测"源事实，不解析 multiplier/promotion，不进入任何路由权威。
_EVID_A4_WORKBUDDY_MODEL_LIST = (
    ".aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001/discovery/ (TASK: "
    "AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001, observed_at=2026-09-02T01:23:05+08:00): "
    "read-only probe of the CURRENT CodeBuddy runtime — `codebuddy --version` = 2.141.0 "
    "(codebuddy_version.txt); `codebuddy --help` --model line documents the currently "
    "supported model IDs (codebuddy_help.txt, discovery_facts.json "
    "models_documented_by_cli); `codebuddy config get model` empty (CodeBuddy Auto, "
    "config NOT authoritative); ~/.codebuddy/settings.json has no model/effort/remote/"
    "promo/multiplier keys. Identity-only facts: provider NOT exposed by CLI; NO "
    "capability / qualification / cost / locality / promo inference (all UNKNOWN); "
    "hy4-preview-x absent from current help text → NOT recorded (current runtime does "
    "not support it). RemoteConfig economic metadata NOT observable via current CLI → "
    "recorded as source fact only, never parsed into routing authority"
)
# 当前运行时（codebuddy 2.141.0）CLI --model 帮助行文档化的 model IDs（identity facts；
# 刷新 = 重新 --help，本常量只是当前证据快照，不是永久事实）。
_WORKBUDDY_CLI_DOCUMENTED_MODEL_IDS = (
    "hy4-preview",
    "hy3",
    "hy3-x",
    "glm-5.3",
    "glm-5.3-flash",
    "glm-5.2",
    "glm-5.1",
    "glm-5v-turbo",
    "minimax-m3",
    "minimax-m2.7",
    "kimi-k3-1",
    "kimi-k2.7",
    "kimi-k2.6",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
)

# TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001（A4 prerequisite slice）：
# WorkBuddy 候选 deepseek-v4-flash 的真实、隔离、可审计 per-run runtime
# qualification probe 证据（**仅此一个候选**；其余 14 个 WorkBuddy candidates
# 保持 tier=None + qualification=unknown，Requirement 8）。
# 证据 = .aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/probe/
# （deepseek_v4_flash_qualification_probe.json + _transcript.txt，
# observed_at=2026-09-02T01:45:31+08:00，codebuddy 2.141.0）：
#   - `codebuddy --version` → 2.141.0（当前 runtime 身份，exit 0）
#   - `codebuddy --help` → --model 帮助行仍文档化 deepseek-v4-flash（CLI 级接受
#     该 model ID；parsed_model_ids 含之）
#   - `codebuddy config get model`（invocation 前后各一次只读）→ 均空
#     （CodeBuddy Auto 保持；probe 零配置修改）
#   - 真实 invocation `codebuddy -p --output-format text -y --model
#     deepseek-v4-flash --no-session-persistence`（stdin 受控 Risk: LOW
#     validator-like task；--no-session-persistence = probe-only 隔离，production
#     adapter invocation 零修改）→ exit 0 / stderr 空 / 无 error signals / 预期
#     AAF_STRUCTURED_RESULT_BEGIN verdict 块 JSON 精确匹配 / 无超时无协议错误
#     无模型不可用无 runtime failure（elapsed 5.3s）
# 受控 LOW probe 成功按风险契约只证明最低 T4（RISK_FLOORS[LOW].executor == "T4"
# 且 validator == "T4"）；T3/T2/T1/T0 不推断（Requirement 4）。cost_class 保持
# UNKNOWN（Requirement 9：不解析 multiplier/promotion/RemoteConfig economic
# metadata）；locality 保持 UNKNOWN（runtime 不暴露执行位置）；provider=None
# 保持（CLI 不暴露）。Hermes 侧同名模型（deepseek-v4-flash@deepseek，A2-004 T2
# accepted evidence）**不是**本条目 qualification authority——WorkBuddy 资格
# 只来自本 probe 的独立 runtime evidence（Requirement 6）。
_EVID_A4_WORKBUDDY_QUALIFICATION_001_PROBE = (
    ".aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001/probe/ (TASK: "
    "AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001, observed_at=2026-09-02T01:45:31+08:00): "
    "isolated non-authoritative per-run qualification probe of the REAL CodeBuddy "
    "runtime (codebuddy 2.141.0) for WorkBuddy candidate deepseek-v4-flash "
    "(artifacts: deepseek_v4_flash_qualification_probe.json + "
    "deepseek_v4_flash_probe_transcript.txt) — "
    "`codebuddy --version`=2.141.0; `codebuddy --help` --model line still documents "
    "deepseek-v4-flash (CLI-level acceptance of the model ID); `codebuddy config "
    "get model` empty BEFORE and AFTER the probe invocation (CodeBuddy Auto "
    "preserved, probe changed no config); REAL invocation `codebuddy -p "
    "--output-format text -y --model deepseek-v4-flash --no-session-persistence` "
    "(probe-only isolation flag; production adapter invocation untouched) with a "
    "controlled Risk: LOW validator-like task via stdin completed with the expected "
    "AAF_STRUCTURED_RESULT_BEGIN verdict block (JSON exact match), exit 0, empty "
    "stderr, no timeout / protocol error / model unavailability / runtime failure. "
    "LOW probe success proves minimum capability tier T4 (RISK_FLOORS[LOW] "
    "executor/validator == T4) ONLY; T3/T2/T1/T0 NOT inferred. cost_class stays "
    "UNKNOWN (no multiplier/promotion/RemoteConfig economic parsing); locality "
    "stays UNKNOWN; provider stays None (CLI does not expose it). Hermes-side "
    "evidence for the same-named model (deepseek-v4-flash@deepseek, A2-004 T2) is "
    "NOT the qualification authority here — WorkBuddy qualification rests ONLY on "
    "this independent runtime probe"
)
# 上述 probe 证据被接受的真实运行时时间戳（probe 完成时刻，来自 probe artifact
# qualification.observed_at）：2026-09-02T01:45:31+08:00。
_EVID_A4_WORKBUDDY_QUALIFICATION_001_OBSERVED_AT = "2026-09-02T01:45:31+08:00"


def baseline_entries() -> tuple[RegistryEntry, ...]:
    """A1 基线 registry 条目。

    规则：只填有证据的字段；capability tier / health / quota / stability /
    availability 未验证 → 一律 UNKNOWN（tier=None、qualification 默认 unknown）。
    证据支持的例外（各有独立已接受证据，互不推导）：
    - deepseek-v4-flash@deepseek（TASK: AAF-v0.5-A2-SHADOW-ROUTING-004）：已接受的
      AAF 执行/审查证据（003-FIX-001 HIGH 任务实际执行至 Codex APPROVE）→ 最低
      已证能力 T2 + accepted-evidence qualification=QUALIFIED；其余维度（cost_class
      等）无证据即保持 UNKNOWN。
    - qwen3:4b@custom（TASK: AAF-v0.5-A2PLUS-RW030-001）：隔离非权威真实 runtime
      qualification probe 证据（本地端点可达 / 身份匹配 / 受控 Risk: LOW
      executor-like task 完成并产生预期结构化结果）→ 最低已证能力 T4（LOW executor
      floor）+ accepted-evidence qualification=QUALIFIED；LOCAL_FREE 保持（本地端点
      成本证据）；绝不因 LOCAL_FREE 自动 QUALIFIED。
    - WorkBuddy 候选身份（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001）：
      15 个 identity-only 条目 = 当前 CodeBuddy CLI（--model 帮助行，v2.141.0，
      observed_at=2026-09-02T01:23:05+08:00）文档化的 model IDs——发现身份 ≠
      eligible（is_usable_candidate fail closed）。agent:workbuddy（model=None）
      仍是「当前 Auto 调用」锚点。
    - WorkBuddy 候选 deepseek-v4-flash（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-
      QUALIFICATION-001）：**唯一资格化 WorkBuddy 候选** = 真实 CodeBuddy runtime
      隔离 per-run probe 证据（显式 --model deepseek-v4-flash，production
      invocation 零修改）→ 最低已证能力 T4（受控 Risk: LOW validator-like task
      成功 = LOW executor/validator floor T4，不推断 T3/T2/T1/T0）+
      accepted-evidence qualification=QUALIFIED（accepted evidence snapshot —
      不表示永久健康、不产生动态 health/quarantine 行为）；cost_class=UNKNOWN /
      locality=UNKNOWN / provider=None 保持（Requirement 8/9）；Hermes 侧同名
      模型（deepseek-v4-flash@deepseek）的历史能力证据不是本条目 authority
      （Requirement 6：WorkBuddy 必须有独立 runtime evidence）。其余 14 个
      WorkBuddy 候选仍全 UNKNOWN。
    """
    return (
        # Hermes 主模型（remote API；cost 未暴露）。
        # TASK: AAF-v0.5-A2-SHADOW-ROUTING-004 —— 用已接受的真实运行证据
        # （003-FIX-001 HIGH 任务实际以 deepseek-v4-flash@deepseek 执行至
        # Codex APPROVE）填充最小、保守、可审计的 capability + qualification：
        # capability_tier = T2（仅证明「至少 T2」，不推断 T1/T0）；
        # qualification = QUALIFIED（accepted evidence snapshot，非永久健康、
        # 不产生动态 health/quarantine 行为）；cost_class 保持 UNKNOWN
        # （成本元数据仍未暴露，独立维度，不改）。
        RegistryEntry(
            model="deepseek-v4-flash",
            provider="deepseek",
            applicable_agents=("hermes",),
            capability_tier=CAP_TIER_T2,
            cost_class=COST_CLASS_UNKNOWN,
            locality=LOCALITY_REMOTE,
            qualification=RuntimeQualification(
                status=QUAL_STATUS_QUALIFIED,
                evidence=(_EVID_A2_004_HERMES_T2,),
                observed_at=_EVID_A2_004_OBSERVED_AT,
            ),
            evidence=(_EVID_CAP002_PROBE, _EVID_A0_REPORT, _EVID_A2_004_HERMES_T2),
            notes=(
                "remote API（base_url 空）→ locality=remote（A0 resolution 事实）",
                "cost_class=UNKNOWN（EXTERNAL_DYNAMIC_METADATA_REQUIRED）；A0 guard "
                "分类 PAID_OR_UNKNOWN = 未证明 FREE 的远程模型，不等于已核验 PAID",
                "capability_tier=T2 + qualification=QUALIFIED 仅来自 accepted "
                "execution/review evidence（003-FIX-001 HIGH 任务实际执行至 Codex "
                "APPROVE；HIGH executor floor = T2）；accepted evidence snapshot — "
                "不表示永久健康、不产生动态 health/quarantine 行为；T1/T0 未证明",
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
        # TASK: AAF-v0.5-A2PLUS-RW030-001（RW-030 最小 prerequisite slice）——
        # 用隔离、非权威、真实 runtime qualification probe 证据（真实本地 Ollama
        # 端点：可达 / 身份匹配 / 受控 Risk: LOW executor-like task 完成并产生预期
        # 结构化结果 / 无超时协议错误）填充最小保守 capability + qualification：
        # capability_tier = T4（LOW probe 成功只证明最低 T4 = LOW executor floor，
        # 不推断 T3/T2/T1/T0）；qualification = QUALIFIED（accepted evidence
        # snapshot，非永久健康、不产生动态 health/quarantine 行为）；cost_class
        # 保持 LOCAL_FREE（本地端点成本证据，独立维度）；qwen2.5vl:3b 不动。
        RegistryEntry(
            model="qwen3:4b",
            provider="custom",
            base_url="http://127.0.0.1:11434/v1",
            applicable_agents=("hermes",),
            capability_tier=CAP_TIER_T4,
            cost_class=COST_CLASS_LOCAL_FREE,
            locality=LOCALITY_LOCAL,
            qualification=RuntimeQualification(
                status=QUAL_STATUS_QUALIFIED,
                evidence=(_EVID_RW030_001_PROBE,),
                observed_at=_EVID_RW030_001_OBSERVED_AT,
            ),
            evidence=(_EVID_CAP002_PROBE, _EVID_RW030_001_PROBE),
            notes=(
                "auxiliary compression/web_extract/title_generation/summarization "
                "slots：本地 Ollama 端点 → LOCAL_FREE",
                "base_url=http://127.0.0.1:11434/v1 来自 CAP-002 / RW-030-001 证据"
                "（真实本地 Ollama 端点；A3 active routing 以此事实经 A0 cost_guard"
                " 的既有 loopback 判定识别为 LOCAL_FREE——端点事实只来自证据，绝不虚构）",
                "capability_tier=T4 + qualification=QUALIFIED 仅来自 "
                "TASK: AAF-v0.5-A2PLUS-RW030-001 的隔离非权威真实 runtime probe "
                "（.aaf/AAF-v0.5-A2PLUS-RW030-001/probe/，observed_at="
                "2026-08-31T23:19:13+08:00）：本地端点可达、qwen3:4b 身份与配置匹配、"
                "受控 Risk: LOW executor-like task 完成并产生预期结构化结果、无超时/"
                "协议错误/执行失败；LOW probe 成功只证明最低 T4（LOW executor "
                "floor），不推断 T3/T2/T1/T0；accepted evidence snapshot — 不表示"
                "永久健康、不产生动态 health/quarantine 行为",
            ),
        ),
        # WorkBuddy/CodeBuddy：当前模型不由用户 config 暴露（身份本身 UNKNOWN）。
        # 该 agent:workbuddy 条目是「当前 Auto 调用」的身份锚点（model=None）；
        # 具体候选身份（当前 CLI 支持的 model IDs）作为独立 identity-only 条目
        # 列于其后（TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001），发现身份
        # 不等于任何能力/资格/成本证据（is_usable_candidate fail closed）。
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
                "last-used 决定（CodeBuddy Auto；runtime observation required）；"
                "不得推断填充；adapters 调用不变（无 --model / --effort）",
                "cost / tier / qualification 均 UNKNOWN；具体候选身份见下方 "
                "identity-only 条目（AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001）",
                "RemoteConfig economic metadata 当前 runtime 不可观测（--help 无 "
                "remote economic-config 命令/flag；settings.json 无相关 key）→ "
                "只登记源事实，不解析 multiplier/promotion 进路由权威",
            ),
        ),
        # WorkBuddy/CodeBuddy 候选身份（identity-only；TASK:
        # AAF-v0.5-A4-PREREQ-WORKBUDDY-DISCOVERY-001）：
        # 每个条目 = 一个当前 CLI 支持的 model ID 的具体候选身份，供现有选择
        # 基础设施枚举。除 deepseek-v4-flash（已由 AAF-v0.5-A4-PREREQ-WORKBUDDY-
        # QUALIFICATION-001 资格化，见下方独立条目）外，其余候选全部维度保持
        # 保守 UNKNOWN（Requirement 5）：provider 未暴露 → None；
        # capability_tier=None；qualification=unknown；cost_class=UNKNOWN；
        # locality=UNKNOWN。候选绝不因 ID 被发现而 eligible
        # （is_usable_candidate 需要 tier + QUALIFIED 双证据）。
        *(
            RegistryEntry(
                model=mid,
                provider=None,
                applicable_agents=("workbuddy",),
                capability_tier=None,
                cost_class=COST_CLASS_UNKNOWN,
                locality=LOCALITY_UNKNOWN,
                evidence=(_EVID_A4_WORKBUDDY_MODEL_LIST,),
                notes=(
                    "identity-only fact: model ID documented by CURRENT CodeBuddy "
                    "CLI `--model` help line (v2.141.0, observed_at=2026-09-02T"
                    "01:23:05+08:00); refresh = re-run `codebuddy --help` — not a "
                    "permanent hardcoded fact",
                    "provider NOT exposed by CLI → None; capability_tier=None / "
                    "qualification=unknown / cost_class=UNKNOWN / locality=UNKNOWN "
                    "— NO capability / qualification / cost / promo / free inference",
                ),
            )
            for mid in _WORKBUDDY_CLI_DOCUMENTED_MODEL_IDS
            if mid != "deepseek-v4-flash"
        ),
        # WorkBuddy/CodeBuddy 候选 deepseek-v4-flash（唯一资格化候选；TASK:
        # AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001）：
        # 真实、隔离、可审计的 per-run CodeBuddy runtime probe 证据（显式
        # --model deepseek-v4-flash；production adapter invocation 零修改）→
        # 最低已证能力 T4（受控 Risk: LOW validator-like task 成功 = LOW
        # executor floor T4 / validator floor T4；不推断 T3/T2/T1/T0）+
        # accepted-evidence qualification=QUALIFIED（accepted evidence snapshot —
        # 不表示永久健康、不产生动态 health/quarantine 行为）。cost_class=
        # UNKNOWN 保持（本任务不解析 economic metadata；UNKNOWN 成本不反向提升
        # 能力/资格）；locality=UNKNOWN 保持（runtime 不暴露执行位置）；
        # provider=None 保持（CLI 不暴露）。Hermes 侧同名模型
        # （deepseek-v4-flash@deepseek）的历史能力证据不是本条目 qualification
        # authority——WorkBuddy 资格只来自本 probe 独立 runtime evidence
        # （Requirement 6）。
        RegistryEntry(
            model="deepseek-v4-flash",
            provider=None,
            applicable_agents=("workbuddy",),
            capability_tier=CAP_TIER_T4,
            cost_class=COST_CLASS_UNKNOWN,
            locality=LOCALITY_UNKNOWN,
            qualification=RuntimeQualification(
                status=QUAL_STATUS_QUALIFIED,
                evidence=(_EVID_A4_WORKBUDDY_QUALIFICATION_001_PROBE,),
                observed_at=_EVID_A4_WORKBUDDY_QUALIFICATION_001_OBSERVED_AT,
            ),
            evidence=(
                _EVID_A4_WORKBUDDY_MODEL_LIST,
                _EVID_A4_WORKBUDDY_QUALIFICATION_001_PROBE,
            ),
            notes=(
                "identity fact: model ID documented by CURRENT CodeBuddy CLI "
                "`--model` help line (v2.141.0, observed_at=2026-09-02T01:23:05+08:00); "
                "refresh = re-run `codebuddy --help` — not a permanent hardcoded fact",
                "capability_tier=T4 + qualification=QUALIFIED 仅来自 TASK: "
                "AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-001 的隔离非权威真实 "
                "per-run runtime probe（.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-QUALIFICATION-"
                "001/probe/，observed_at=2026-09-02T01:45:31+08:00）：真实 invocation "
                "`codebuddy -p --output-format text -y --model deepseek-v4-flash "
                "--no-session-persistence` 完成受控 Risk: LOW validator-like task 并 "
                "产生预期结构化 verdict（exit 0 / stderr 空 / 无超时协议错误）；LOW "
                "probe 成功只证明最低 T4（LOW executor/validator floor），不推断 "
                "T3/T2/T1/T0；accepted evidence snapshot — 不表示永久健康、不产生 "
                "动态 health/quarantine 行为",
                "cost_class=UNKNOWN 保持（本任务不解析 multiplier/promotion/RemoteConfig "
                "economic metadata；UNKNOWN 成本不反向提升能力或资格）；locality=UNKNOWN "
                "保持（runtime 不暴露执行位置）；provider=None 保持（CLI 不暴露）",
                "Hermes 侧同名模型（deepseek-v4-flash@deepseek，A2-004 T2 证据）不是本 "
                "条目 qualification authority——WorkBuddy 资格只来自本 probe 独立 "
                "runtime evidence（Requirement 6）",
                "production WorkBuddy invocation 零修改：adapters 仍精确 "
                "[-p --output-format text -y]（CodeBuddy Auto），无 --model/--effort；"
                "本 qualification 仅影响候选 eligibility（is_usable_candidate），"
                "不影响任何实际 routing authority",
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
