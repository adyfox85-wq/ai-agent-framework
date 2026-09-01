"""AAF v0.5 A4 prereq — WorkBuddy economic metadata 事实层（fact layer only）。

TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001（语义收紧 = FIX-001：
AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001）
目的：为 A4 建立 WorkBuddy/CodeBuddy 经济性元数据（multiplier / promotion /
free-like / validFrom / validUntil / source / observed_at / freshness）的
**可审计证据事实表示**。本模块是纯数据 + 纯逻辑契约：

- 不发起进程 / 网络调用；不产生运行时 artifact（artifact 由 .aaf probe 生成）。
- 事实层本身不是路由权威；A4（TASK: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001）
  起，唯一路由消费方 = ``workbuddy_routing``（WorkBuddy validator stage 的 active
  economic routing authority）：经济事实永远低于 capability/qualification gate
  （Requirement 6）——即使某候选有 FRESH 免费促销，其 capability_tier=None /
  qualification=unknown 仍不 eligible（is_usable_candidate 与 selector 不消费
  本模块；workbuddy_routing 只对 selector 已 eligible 的候选做经济排序）。
  生产 WorkBuddy invocation 仅在 A4 routing 生效时精确追加
  ``--model <经济 winner>``（[-p --output-format text -y --model <m>]），
  其余情况保持 CodeBuddy Auto（[-p --output-format text -y]）；无 --effort /
  无 provider override / 无 fallback。
- adapters / shadow_routing / active_routing / model_registry / cost_guard
  仍不 import 本模块（A2/A3 权威 source-level 零消费契约保持）。
- 新鲜度显式且 fail-closed（Requirement 4/5）：
  - FRESH  = 有 validFrom+validUntil 且窗口覆盖参考时间；
  - STALE  = 已过期或尚未生效（validUntil < now 或 now < validFrom）；
  - UNKNOWN = 时间戳/有效性证据不足（缺失、不可解析、只有单边边界）。
  任何 STALE / UNKNOWN 经济事实绝不作为 "便宜/免费" 权威
  （is_authoritative_cheap 需要 FRESH + 显式 zero-factor 限时免费促销 +
  multiplier==0.0 + promotion_factor==0.0 四者同时成立）。
- 经济字段完整 + 一致 gate（FIX-001，Codex REQUEST_CHANGE 两个 blocking
  findings 收口）：缺失或自相矛盾的经济元数据**永远不能**被当作
  authoritative cheap/free——multiplier=None / promotion_factor=None /
  free+nonzero factor / free+nonzero multiplier / discount 内部矛盾 /
  raw 证据无法解释 parsed 值 → 一律 fail closed：
  - is_authoritative_cheap 要求 FRESH + free + multiplier==0.0 +
    promotion_factor==0.0 四者同时成立（Requirement 3）；
  - cheapness_rank 的已知新鲜折扣 rank（RANK_FRESH_DISCOUNT）要求经济字段
    完整且一致（economic_fields_consistent）；字段缺失/矛盾的 FRESH discount
    落入 RANK_UNKNOWN_OR_STALE，绝不进入已知经济排序（Requirement 1/2）；
  - EconomicFact.__post_init__ 校验 multiplier_raw 必须能解析回 multiplier
    （无法解释的 raw 不得背书数值，fail closed）。

证据来源（真实只读 runtime probe，observed_at=2026-09-02T02:10:30+08:00，
codebuddy 2.141.0）：
- 主源：WorkBuddy RemoteConfig 缓存 ~/.workbuddy/cache/acc-product-config-v3.json
  （ACC_PRODUCT_CONFIG_V3，genieVersion 5.4.5，date=2026-08-29T17:16:22.337Z，
  commit=fa1d65ec13f3c977ec439ecc969279ed03cb09a1）—— models[].credits（乘数）、
  modelPromotions[]（免费/折扣促销 + schedule.validFrom/validUntil）。
- 佐证：CodeBuddy CLI 运行时 catalog 缓存
  ~/.codebuddy/local_storage/entry_d43e96994f944cfb77961c2ea7d04605.info
  （ts=2026-09-02T02:01:14+08:00）—— models[].credits（乘数，与主源一致，
  minimax-m2.7 例外：主源 x0.26 vs CLI catalog x0.19，见 notes）。

保守纪律（镜像 DISCOVERY-001）：
- 只收录 15 个当前 CLI 文档化候选（_WORKBUDDY_CLI_DOCUMENTED_MODEL_IDS）的经济
  事实；product config 中出现的其他 model id（fast-model / deepseek-v3-2-volc /
  hy4-preview-x / deepseek-v4-flash-ioa 等）不是 CLI 候选 → 只在 probe artifact
  中记录为源事实，不进入 baseline 事实（当前 runtime 不支持即不发明）。
- 只有显式促销条目才产生 promotion_status；credits=x0.00 而无促销条目 → 不推断
  免费（promotion_status=None）。
- 只有显式 validFrom/validUntil 才产生有效性窗口；daily 循环时段促销
  （如夜间折扣）无日期窗口 → freshness=UNKNOWN（fail closed）。
- 数值/枚举校验失败一律 ValueError（fail closed，绝不静默强转）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

ECONOMIC_SCHEMA_VERSION = 1

# 新鲜度（Requirement 4：显式三态，fail-closed）
ECON_FRESH = "FRESH"
ECON_STALE = "STALE"
ECON_UNKNOWN = "UNKNOWN"
ECON_FRESHNESSES = (ECON_FRESH, ECON_STALE, ECON_UNKNOWN)

# promotion/free-like status（只来自显式促销证据）
PROMO_STATUS_FREE = "free"       # 显式 zero-factor 限时免费（0x / factor 0）
PROMO_STATUS_DISCOUNT = "discount"  # 显式折扣（0 < factor < 1）
PROMO_STATUSES = (PROMO_STATUS_FREE, PROMO_STATUS_DISCOUNT)

# cheapness 权威排序（数值越小越便宜；STALE/UNKNOWN 永不小于已知 FRESH；
# 字段缺失/矛盾的经济事实永不进入已知排序——FIX-001）
RANK_AUTHORITATIVE_CHEAP = 0   # FRESH + 显式免费 + multiplier 0.0 + promotion_factor 0.0
RANK_FRESH_DISCOUNT = 1        # FRESH + 显式折扣 + 经济字段完整且一致
RANK_UNKNOWN_OR_STALE = 2      # STALE / UNKNOWN / 无促销 / 全价 / 字段缺失或矛盾

# 15 个当前 CLI 文档化 WorkBuddy 候选（与 model_registry._WORKBUDDY_CLI_*
# 同一证据链；刷新 = 重新 `codebuddy --help`，不是永久事实）。
WORKBUDDY_CANDIDATE_IDS = (
    "hy4-preview", "hy3", "hy3-x", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "minimax-m2.7",
    "kimi-k3-1", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
    "deepseek-v4-flash",
)

# probe 证据被接受的真实运行时时间戳（probe 完成时刻；artifact 与 registry 同值）。
_ECON_OBSERVED_AT = "2026-09-02T02:10:30+08:00"

# TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001（A4 prerequisite slice）：
# WorkBuddy/CodeBuddy 经济性元数据的真实只读 runtime probe 证据。
# 证据 = .aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe/
# （observed_at=2026-09-02T02:10:30+08:00，codebuddy 2.141.0）：
#   - 主源 WorkBuddy RemoteConfig 缓存 ~/.workbuddy/cache/acc-product-config-v3.json
#     （ACC_PRODUCT_CONFIG_V3 / genieVersion 5.4.5 / date=2026-08-29T17:16:22.337Z /
#     commit=fa1d65ec13f3c977ec439ecc969279ed03cb09a1；product_config_economic_
#     snapshot.json 全量经济字段快照）→ models[].credits（乘数）+ modelPromotions[]
#     （kind=discount、discount.factor、schedule.validFrom/validUntil、daily 时段）。
#   - 佐证 CodeBuddy CLI 运行时 catalog 缓存
#     ~/.codebuddy/local_storage/entry_d43e96994f944cfb77961c2ea7d04605.info
#     （ts=2026-09-02T02:01:14+08:00；catalog_economic_snapshot.json）→ 逐模型
#     credits 乘数，与主源一致（minimax-m2.7 例外 x0.26 vs x0.19，记录在案）。
#   - `codebuddy --version`=2.141.0；`codebuddy config get model` 空
#     （CodeBuddy Auto 保持；probe 零配置修改）；`codebuddy config list` 无
#     经济 key（settings 层零经济配置）。
#   - 限制（Requirement 10 记录）：无 validFrom/validUntil 的候选（无日期窗口或
#     仅 daily 循环促销）→ 新鲜度 UNKNOWN；只把显式促销/窗口写成事实。
# 经济事实只存储、绝不进入路由权威（Requirement 8）：本模块无任何消费方，
# 生产 invocation 保持 [-p --output-format text -y]（CodeBuddy Auto）。
_EVID_A4_WORKBUDDY_ECONOMICS_001 = (
    ".aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001/economic_probe/ (TASK: "
    "AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001, observed_at=2026-09-02T02:10:30+08:00, "
    "codebuddy 2.141.0): read-only runtime probe of the CURRENT WorkBuddy economic "
    "metadata — primary source: WorkBuddy RemoteConfig cache "
    "~/.workbuddy/cache/acc-product-config-v3.json (ACC_PRODUCT_CONFIG_V3, "
    "genieVersion 5.4.5, date=2026-08-29T17:16:22.337Z, commit=fa1d65ec13f3c977ec439ecc969279ed03cb09a1; "
    "product_config_economic_snapshot.json) -> models[].credits multipliers + "
    "modelPromotions[] (kind=discount, discount.factor, schedule.validFrom/"
    "validUntil, daily windows); corroborating source: CodeBuddy CLI runtime "
    "catalog cache ~/.codebuddy/local_storage/entry_d43e96994f944cfb77961c2ea7d04605.info "
    "(ts=2026-09-02T02:01:14+08:00; catalog_economic_snapshot.json) -> per-model "
    "credits (agree with primary except minimax-m2.7: x0.26 vs x0.19, documented). "
    "`codebuddy --version`=2.141.0; `codebuddy config get model` empty (CodeBuddy "
    "Auto preserved, zero config change); `codebuddy config list` has no economic "
    "keys. Only the 15 current CLI-documented candidates get baseline facts; other "
    "catalog ids (fast-model/deepseek-v3-2-volc/hy4-preview-x/deepseek-v4-flash-ioa "
    "etc.) are source facts only (NOT CLI candidates; no invention). Explicit "
    "promotion entries only -> promotion_status; credits x0.00 without promo -> no "
    "free inference; date-window promotions -> valid_from/valid_until; daily-only "
    "schedules -> no window -> freshness UNKNOWN (fail closed). Economic facts are "
    "stored ONLY; NOT consumed by any routing authority; production WorkBuddy "
    "invocation unchanged (exact [-p --output-format text -y], CodeBuddy Auto)"
)

_SOURCE_VERSION = (
    "WorkBuddy RemoteConfig cache acc-product-config-v3.json "
    "(ACC_PRODUCT_CONFIG_V3, genieVersion 5.4.5, date=2026-08-29T17:16:22.337Z, "
    "commit=fa1d65ec13f3c977ec439ecc969279ed03cb09a1; cache mtime "
    "2026-09-01T07:36:58+08:00)"
)

# 主源 multiplier（product config models[].credits；15 个 CLI 候选全部有值）。
_CANDIDATE_MULTIPLIERS: dict[str, str] = {
    "hy4-preview": "x0.00",
    "hy3": "x0.00",
    "hy3-x": "x0.05",
    "glm-5.3": "x0.79",
    "glm-5.3-flash": "x0.06",
    "glm-5.2": "x0.79",
    "glm-5.1": "x0.79",
    "glm-5v-turbo": "x0.71",
    "minimax-m3": "x0.25",
    "minimax-m2.7": "x0.26",
    "kimi-k3-1": "x1.62",
    "kimi-k2.7": "x0.57",
    "kimi-k2.6": "x0.52",
    "deepseek-v4-pro": "x0.51",
    "deepseek-v4-flash": "x0.17",
}

# 显式促销事实（只来自 product config modelPromotions[]；daily-only 时段 → 无窗口）。
# (model_id, status, factor, valid_from, valid_until, detail...)
_PROMOTIONS: tuple[tuple[str, str, float, str | None, str | None, tuple[str, ...]], ...] = (
    (
        "hy3",
        PROMO_STATUS_FREE,
        0.0,
        "2026-07-06T00:00:00+08:00",
        "2026-10-01T00:00:00+08:00",
        ("限时免费 hy3-free-trial-202608: 7月6日–9月30日每日赠送免费额度 (0x, displayMode=replace, factor 0, priority 200, Asia/Shanghai)",),
    ),
    (
        "hy4-preview",
        PROMO_STATUS_FREE,
        0.0,
        "2026-08-28T00:00:00+08:00",
        "2026-09-11T00:00:00+08:00",
        ("限时免费 hy4-free-trial-202608: 8月28日–9月10日每日赠送免费额度 (0x, displayMode=replace, factor 0, priority 200, Asia/Shanghai)",),
    ),
    (
        "glm-5.2",
        PROMO_STATUS_DISCOUNT,
        0.5,
        None,
        None,
        ("夜间折扣 glm-52-night-discount-202607: daily 23:00–7:50 Asia/Shanghai, factor 0.5 (0.50x strikethrough, priority 100) — daily-only schedule, NO date window -> freshness UNKNOWN",),
    ),
    (
        "deepseek-v4-flash",
        PROMO_STATUS_DISCOUNT,
        0.5,
        None,
        None,
        ("夜间折扣 ds-discount-daytime-badge-202608: off-peak 5折 (Mon–Fri 09:00–12:00 / 14:00–18:00 peak full price), daily 0:00–23:59 Asia/Shanghai, factor 0.5, priority 50 — daily-only schedule, NO date window -> freshness UNKNOWN; NOT a free promotion",),
    ),
    (
        "deepseek-v4-pro",
        PROMO_STATUS_DISCOUNT,
        0.5,
        None,
        None,
        ("夜间折扣 ds-discount-daytime-badge-202608: off-peak 5折 (Mon–Fri 09:00–12:00 / 14:00–18:00 peak full price), daily 0:00–23:59 Asia/Shanghai, factor 0.5, priority 50 — daily-only schedule, NO date window -> freshness UNKNOWN; NOT a free promotion",),
    ),
)


# ---------------------------------------------------------------------------
# 纯逻辑（确定性；无 I/O、无网络）
# ---------------------------------------------------------------------------


def parse_multiplier(raw: str | None) -> float | None:
    """从 observed credits 字符串解析乘数：``x0.17`` / ``x0.17 credits`` → 0.17。

    解析失败（含 None / 空 / 无法识别格式）→ None（fail closed，绝不发明数值）。
    """
    if not raw:
        return None
    m = re.fullmatch(r"x\s*(\d+(?:\.\d+)?)(?:\s*credits)?", raw.strip(), flags=re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _parse_ts(value: str | None) -> datetime | None:
    """严格解析 ISO 8601 时间戳（含时区偏移）。不可解析 → None（视为无证据）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None  # 无时区信息的时间戳不用于与带时区参考时间比较（fail closed）
    return parsed


def classify_freshness(fact: "EconomicFact", now: datetime) -> str:
    """新鲜度分类（确定性，fail closed）。

    - STALE: 有 validUntil 且 now > validUntil（已过期）；或有 validFrom 且
      now < validFrom（尚未生效）。
    - FRESH: validFrom + validUntil 都存在且窗口覆盖 now。
    - UNKNOWN: 时间戳缺失 / 不可解析 / 只有单边边界（不足以证明"当前有效"）。

    ``now`` 必须带时区（tz-aware）；否则 ValueError（参考时间契约必须显式）。
    """
    if now.tzinfo is None:
        raise ValueError("now must be tz-aware (freshness reference time contract)")
    vf = _parse_ts(fact.valid_from)
    vu = _parse_ts(fact.valid_until)
    if vf is None and vu is None:
        return ECON_UNKNOWN
    if vu is not None and now > vu:
        return ECON_STALE
    if vf is not None and now < vf:
        return ECON_STALE
    if vf is not None and vu is not None and vf <= now <= vu:
        return ECON_FRESH
    return ECON_UNKNOWN


def economic_fields_consistent(fact: "EconomicFact") -> bool:
    """经济字段是否**完整且相互一致**（FIX-001 Requirement 1/2，fail closed）。

    只有以下情况返回 True：
    - promotion_status == free：multiplier 已知 == 0.0 **且** promotion_factor
      已知 == 0.0（zero-factor 限时免费；任一字段缺失或非零 → False）；
    - promotion_status == discount：multiplier 已知 > 0.0 且 promotion_factor
      已知且 0.0 < factor < 1.0（factor==0.0 意味着免费、factor==1.0 意味着无
      折扣，均与 discount 状态矛盾；multiplier==0.0 意味着免费，也与 discount
      矛盾）；
    - 其余（无促销状态 / multiplier=None / promotion_factor=None）→ False。

    返回 False 的事实**永远不进入已知经济排序**（cheapness_rank 只对完整且
    一致的经济字段给出已知 rank；缺失/矛盾一律 RANK_UNKNOWN_OR_STALE）。
    """
    if fact.multiplier is None or fact.promotion_factor is None:
        return False
    if fact.promotion_status == PROMO_STATUS_FREE:
        return fact.multiplier == 0.0 and fact.promotion_factor == 0.0
    if fact.promotion_status == PROMO_STATUS_DISCOUNT:
        return (
            fact.multiplier > 0.0
            and 0.0 < fact.promotion_factor < 1.0
        )
    return False


def is_authoritative_cheap(fact: "EconomicFact", now: datetime) -> bool:
    """经济事实是否构成"免费/便宜"权威（Requirement 5，fail closed）。

    四条件**同时**成立才返回 True：
      1. freshness == FRESH（有有效日期窗口覆盖 now）；
      2. promotion_status == free（显式 zero-factor 限时免费促销证据）；
      3. multiplier 已知且 == 0.0（credits 与促销一致；缺失/非零 → fail closed）；
      4. promotion_factor 已知且 == 0.0（factor 与 free 一致；缺失/非零 →
         fail closed——FIX-001 blocking finding #2）。
    STALE / UNKNOWN / 折扣 / 无促销 / 字段缺失或数据不一致 → False——未知或
    过期的经济元数据绝不按假设当作便宜/免费。
    """
    if classify_freshness(fact, now) != ECON_FRESH:
        return False
    if fact.promotion_status != PROMO_STATUS_FREE:
        return False
    return (
        fact.multiplier is not None
        and fact.multiplier == 0.0
        and fact.promotion_factor is not None
        and fact.promotion_factor == 0.0
    )


def cheapness_rank(fact: "EconomicFact", now: datetime) -> int:
    """cheapness 权威排序（数值越小越便宜；Requirement 5 可判定编码）。

    - 0 = 权威免费（FRESH + 显式免费 + multiplier 0.0 + promotion_factor 0.0）
    - 1 = 已知新鲜的显式折扣（FRESH + discount + **经济字段完整且一致**——
      FIX-001：multiplier=None / promotion_factor=None / 内部矛盾 → 不进入
      已知经济排序，fall through 到 rank 2）
    - 2 = 其余（STALE / UNKNOWN / 无促销 / 全价 / 字段缺失或矛盾）——STALE/
      UNKNOWN/不完整 永不 outrank 已知 FRESH 事实。
    """
    if is_authoritative_cheap(fact, now):
        return RANK_AUTHORITATIVE_CHEAP
    if (
        classify_freshness(fact, now) == ECON_FRESH
        and fact.promotion_status == PROMO_STATUS_DISCOUNT
        and economic_fields_consistent(fact)
    ):
        return RANK_FRESH_DISCOUNT
    return RANK_UNKNOWN_OR_STALE


# TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-SECOND-CANDIDATE-001 —— candidate probe
# priority 的 fail-closed 选择语义（Requirement 2/3/4）。本函数只回答「14 个未
# 资格化候选中**先验证谁**」，是 probe 顺序决策，**不是 routing authority**：
# 路由代码（adapters / shadow_routing / active_routing / runner / selector）仍
# 零 import 本模块；经济事实仍永远低于 capability/qualification gate。任何
# STALE / UNKNOWN / 字段缺失或矛盾的候选绝不因「猜它便宜」而被优先；没有任何
# 候选拥有足够可信的 FRESH 经济事实时返回 None（= NO_TRUSTWORTHY_SECOND_CANDIDATE），
# 调用方必须如实报告并停止，不得发明经济值、不得随意挑模型冒充 economic choice。
NO_TRUSTWORTHY_SECOND_CANDIDATE = None  # 语义哨兵：无可信第二候选（Requirement 4）


def select_probe_candidate(
    facts: dict[str, "EconomicFact"],
    now: datetime,
    exclude_ids: tuple[str, ...] = (),
) -> str | None:
    """fail-closed 候选 probe 优先级选择（纯函数；Requirement 3）。

    优先顺序：
    1. RANK_AUTHORITATIVE_CHEAP（FRESH + 显式 free + multiplier 0.0 +
       promotion_factor 0.0）：全部按 valid_until 升序（免费窗口**最早关闭**的
       最优先——在它仍 FRESH 时验证最有时效价值），valid_until 相同再按 model_id
       字典序（确定性全序 tie-break）；
    2. 否则 RANK_FRESH_DISCOUNT（FRESH + discount + economic_fields_consistent）：
       按 multiplier 升序（最低已知经济 rank/multiplier 优先），再 valid_until、
       model_id（确定性全序）；
    3. STALE / UNKNOWN / 无促销 / 全价 / 字段缺失或矛盾 → **永不优先**
       （rank 2 候选直接排除，绝不出现在任何优先级序列中）。

    返回：选中的 model_id；没有任何可信 FRESH 候选时返回
    ``NO_TRUSTWORTHY_SECOND_CANDIDATE``（None）——调用方必须如实报告
    NO_TRUSTWORTHY_SECOND_CANDIDATE 并停止（Requirement 4）。

    ``now`` 必须带时区（与 classify_freshness 同一参考时间契约）。
    ``exclude_ids``：调用方已资格化/不可考虑的候选（如已 QUALIFIED 的
    deepseek-v4-flash），不参与本轮选择。
    """
    if now.tzinfo is None:
        raise ValueError("now must be tz-aware (freshness reference time contract)")
    candidates: list[tuple[int, float, str, str]] = []  # (rank, sort_key, key, model_id)
    for mid, fact in facts.items():
        if mid in exclude_ids:
            continue
        rank = cheapness_rank(fact, now)
        if rank == RANK_UNKNOWN_OR_STALE:
            continue  # STALE/UNKNOWN/不完整 永不优先（fail closed）
        vu = _parse_ts(fact.valid_until)
        if rank == RANK_AUTHORITATIVE_CHEAP:
            # 免费窗口最早关闭者最优先（在仍 FRESH 时验证）
            sort_key = vu.timestamp() if vu is not None else float("inf")
        else:  # RANK_FRESH_DISCOUNT：最低已知 multiplier 优先
            sort_key = fact.multiplier if fact.multiplier is not None else float("inf")
        candidates.append((rank, sort_key, mid, mid))
    if not candidates:
        return NO_TRUSTWORTHY_SECOND_CANDIDATE
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return candidates[0][3]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EconomicFact:
    """单个 WorkBuddy 候选的经济性事实（证据驱动；无证据字段 = None/UNKNOWN）。

    - model_id：候选 model ID（= CLI 文档化 ID）
    - multiplier / multiplier_raw：主源 credits 乘数（``x0.17`` → 0.17）
    - promotion_status：None（无促销证据）/ free / discount（只来自显式促销条目）
    - promotion_factor：促销折扣因子（0 = 免费；0<factor<1 = 折扣）
    - promotion_detail：观察到的促销细节（raw schedule 文本等）
    - valid_from / valid_until：显式日期窗口（ISO 8601 + 时区；无 → None）
    - source / source_version：证据出处 + 配置版本
    - observed_at：probe 观测时间戳
    - freshness：不存储（由 classify_freshness(fact, now) 对显式参考时间计算，
      序列化时写入 observation 文档，保证新鲜度永远显式）
    """

    model_id: str
    multiplier: float | None = None
    multiplier_raw: str | None = None
    promotion_status: str | None = None
    promotion_factor: float | None = None
    promotion_detail: tuple[str, ...] = ()
    valid_from: str | None = None
    valid_until: str | None = None
    source: str = ""
    source_version: str | None = None
    observed_at: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (isinstance(self.model_id, str) and self.model_id.strip()):
            raise ValueError("model_id must be a non-empty string")
        if self.multiplier is not None and not isinstance(self.multiplier, float):
            raise ValueError(f"multiplier must be float or None, got {type(self.multiplier).__name__}")
        if self.multiplier is not None and self.multiplier < 0:
            raise ValueError(f"multiplier must be >= 0, got {self.multiplier!r}")
        if self.multiplier is not None and self.multiplier_raw is not None:
            # FIX-001：raw 证据必须能解释 parsed 数值——无法解析/不一致的 raw
            # 不得背书一个"发明"的 multiplier（Requirement 1 fail closed）。
            parsed = parse_multiplier(self.multiplier_raw)
            if parsed is None or parsed != self.multiplier:
                raise ValueError(
                    f"multiplier_raw {self.multiplier_raw!r} does not parse to "
                    f"multiplier {self.multiplier!r} — raw evidence must explain "
                    f"the value (fail closed, no invented multipliers)"
                )
        if self.promotion_status is not None and self.promotion_status not in PROMO_STATUSES:
            raise ValueError(
                f"invalid promotion_status: {self.promotion_status!r} "
                f"(allowed: {PROMO_STATUSES} or None=no evidence)"
            )
        if self.promotion_factor is not None and not (
            isinstance(self.promotion_factor, float) and 0.0 <= self.promotion_factor <= 1.0
        ):
            raise ValueError(f"promotion_factor must be float in [0,1] or None, got {self.promotion_factor!r}")
        for name, value in (("valid_from", self.valid_from), ("valid_until", self.valid_until)):
            if value is not None and _parse_ts(value) is None:
                raise ValueError(f"{name} must be ISO 8601 with tz offset or None, got {value!r}")
        if not (isinstance(self.source, str) and self.source.strip()):
            raise ValueError("source must be a non-empty evidence reference")
        for name in ("promotion_detail", "notes"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"{name} must be a tuple of str")


# ---------------------------------------------------------------------------
# 序列化（纯；未知枚举/格式 → ValueError，fail closed）
# ---------------------------------------------------------------------------


def fact_to_dict(fact: EconomicFact, now: datetime | None = None) -> dict[str, Any]:
    """事实 → dict；freshness 显式写入（对 now 或事实 observed_at 计算）。"""
    ref = now
    if ref is None:
        if fact.observed_at is None:
            raise ValueError("freshness requires an explicit reference time: pass now or set observed_at")
        ref = _parse_ts(fact.observed_at)
        if ref is None:
            raise ValueError(f"observed_at not parseable as tz-aware ISO: {fact.observed_at!r}")
    return {
        "model_id": fact.model_id,
        "multiplier": fact.multiplier,
        "multiplier_raw": fact.multiplier_raw,
        "promotion_status": fact.promotion_status,
        "promotion_factor": fact.promotion_factor,
        "promotion_detail": list(fact.promotion_detail),
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
        "source": fact.source,
        "source_version": fact.source_version,
        "observed_at": fact.observed_at,
        "freshness": classify_freshness(fact, ref),
        "freshness_reference_time": ref.isoformat(),
        "notes": list(fact.notes),
    }


def fact_from_dict(data: dict[str, Any]) -> EconomicFact:
    """dict → 事实；缺失字段 → 默认（UNKNOWN）；未知枚举/非法值 → ValueError。

    注意：``freshness`` / ``freshness_reference_time`` 是派生字段（由
    classify_freshness 对 reference time 计算），构造时忽略——事实本身只存
    证据字段，新鲜度永远对显式参考时间重新计算（不信任已存 freshness）。
    """
    return EconomicFact(
        model_id=data["model_id"],
        multiplier=data.get("multiplier"),
        multiplier_raw=data.get("multiplier_raw"),
        promotion_status=data.get("promotion_status"),
        promotion_factor=data.get("promotion_factor"),
        promotion_detail=tuple(data.get("promotion_detail", [])),
        valid_from=data.get("valid_from"),
        valid_until=data.get("valid_until"),
        source=data.get("source", ""),
        source_version=data.get("source_version"),
        observed_at=data.get("observed_at"),
        notes=tuple(data.get("notes", [])),
    )


def facts_to_dict(
    facts: dict[str, EconomicFact], now: datetime | None = None
) -> dict[str, Any]:
    return {
        "schema_version": ECONOMIC_SCHEMA_VERSION,
        "authority": (
            "workbuddy_economics.py fact layer (TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-"
            "ECONOMICS-001; tightened by FIX-001); evidence-backed facts only — NOT "
            "routing authority; freshness is computed per reference time; STALE/"
            "UNKNOWN/incomplete/contradictory never cheap"
        ),
        "facts": {mid: fact_to_dict(f, now) for mid, f in sorted(facts.items())},
    }


def facts_from_dict(data: dict[str, Any]) -> dict[str, EconomicFact]:
    if not isinstance(data, dict) or not isinstance(data.get("facts"), dict):
        raise ValueError("facts dict must contain a 'facts' mapping")
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != ECONOMIC_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported economic schema_version: {schema_version!r} "
            f"(supported: {ECONOMIC_SCHEMA_VERSION})"
        )
    facts: dict[str, EconomicFact] = {}
    for mid, raw in data["facts"].items():
        fact = fact_from_dict(raw)
        if fact.model_id != mid:
            raise ValueError(
                f"fact key mismatch: dict key {mid!r} != fact.model_id {fact.model_id!r}"
            )
        facts[mid] = fact
    return facts


# ---------------------------------------------------------------------------
# 基线事实（只填 probe 证据支持的字段；其余 None/UNKNOWN）
# ---------------------------------------------------------------------------


def baseline_economic_facts() -> dict[str, EconomicFact]:
    """15 个 WorkBuddy CLI 候选的基线经济事实（证据快照，非永久事实）。

    - multiplier：主源 product config credits（全部 15 候选均有值）。
    - promotion_status：只来自显式 modelPromotions 条目；其余候选 None。
    - valid_from/valid_until：只来自显式日期窗口促销；daily-only 促销无窗口。
    - 刷新 = 重新读两个 runtime 缓存（probe 脚本），不是硬编码永久事实。
    """
    promo_by_model: dict[str, tuple[str, float, str | None, str | None, tuple[str, ...]]] = {}
    for mid, status, factor, vf, vu, detail in _PROMOTIONS:
        promo_by_model[mid] = (status, factor, vf, vu, detail)

    facts: dict[str, EconomicFact] = {}
    for mid in WORKBUDDY_CANDIDATE_IDS:
        raw = _CANDIDATE_MULTIPLIERS[mid]
        multiplier = parse_multiplier(raw)
        status, factor, vf, vu, detail = promo_by_model.get(
            mid, (None, None, None, None, ())
        )
        notes: list[str] = []
        if mid == "minimax-m2.7":
            notes.append(
                "sources disagree on multiplier: product config x0.26 (primary, used) "
                "vs CodeBuddy CLI catalog x0.19 (ts=2026-09-02T02:01:14+08:00) — "
                "discrepancy documented, not resolved by assumption"
            )
        notes.append(
            "fact layer only (TASK: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001; "
            "consumed by workbuddy_routing since TASK: AAF-v0.5-A4-WORKBUDDY-"
            "ECONOMIC-ROUTING-001): facts are NOT themselves routing authority; "
            "economics is subordinate to capability/qualification gates; "
            "production WorkBuddy invocation gains --model ONLY when the A4 "
            "active economic routing applies it (else CodeBuddy Auto "
            "[-p --output-format text -y], no --effort); refresh = re-run the "
            "read-only economic probe — not a permanent hardcoded fact"
        )
        if status == PROMO_STATUS_FREE:
            notes.append(
                "promotion_status=free is a FACT; it does NOT make this candidate "
                "eligible — capability/qualification gates (is_usable_candidate) "
                "never consume economic facts"
            )
        facts[mid] = EconomicFact(
            model_id=mid,
            multiplier=multiplier,
            multiplier_raw=raw,
            promotion_status=status,
            promotion_factor=factor,
            promotion_detail=detail,
            valid_from=vf,
            valid_until=vu,
            source=_EVID_A4_WORKBUDDY_ECONOMICS_001,
            source_version=_SOURCE_VERSION,
            observed_at=_ECON_OBSERVED_AT,
            notes=tuple(notes),
        )
    return facts
