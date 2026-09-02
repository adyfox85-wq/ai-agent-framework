"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 fresh-runner wrapper (MEDIUM).

与 tests/fresh_runner_a4_wb_econ_fix001_wrapper.py 同一技术：在导入 runner 之前
完成模块级 patch，只影响 fresh-process 验证，生产代码零改动
（runner.py / workbuddy_routing.py / workbuddy_economics.py / model_registry.py
不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_ECON_FACTS_MODE 注入 runner 的 registry + 经济事实输入：
   - real（默认）：零注入 —— 真实 model_registry.baseline_registry() +
     真实 workbuddy_economics.baseline_economic_facts()。
   - two_trustworthy：LOW 受控 fixture（fix001 同款）—— 把 deepseek-v4-flash
     的经济事实替换为 FRESH discount（rank 1），hy4-preview 保持 FRESH free
     （rank 0）→ LOW winner = hy4-preview（rank 0 权威免费 outranks rank 1）。
   - medium_two_trustworthy：MEDIUM 受控 fixture —— 在真实 registry **基础上
     新增**两个 MEDIUM-eligible（capability_tier=T3 + QUALIFIED +
     applicable_agents=("workbuddy",)）候选 med-free（FRESH free rank 0）/
     med-discount（FRESH discount rank 1）→ MEDIUM winner = med-free
     （rank 0 outranks rank 1）。真实 WorkBuddy 候选（deepseek-v4-flash /
     hy4-preview，capability_tier=T4）不满足 MEDIUM selector floor T3 → 保持
     ineligible —— 真实数据零修改（Req 15：不为凑 MEDIUM 路由而放宽 capability
     floor / 伪造事实；MEDIUM 真实 registry 场景如实 Auto）。
   受控模式明确标注为 controlled deterministic 场景（fixture/evidence
   injection，与真实 runtime 区分；production 代码零 hook）。

用法：
    python tests/fresh_runner_a4_wb_econ_medium_wrapper.py <TASK.md> --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN           fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_ECON_FACTS_MODE    real | two_trustworthy | medium_two_trustworthy（缺省 real）
    FAKE_CODEBUDDY_MARKER       fake codebuddy chat 写入的 argv 证据 marker 路径
"""
from __future__ import annotations

import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod
from ai_agent_framework import model_registry as model_registry_mod
from ai_agent_framework import workbuddy_routing as workbuddy_routing_mod
from ai_agent_framework import workbuddy_economics as we

_real_adapters_path = adapters_mod._windows_path
_real_guard_path = cost_guard_mod._windows_path


def _prepend_fake_bin(original):
    extra = os.environ.get("AAF_TEST_FAKE_BIN", "").strip()
    if not extra:
        return original
    return extra + ";" + original


adapters_mod._windows_path = lambda: _prepend_fake_bin(_real_adapters_path())
cost_guard_mod._windows_path = lambda: _prepend_fake_bin(_real_guard_path())

_REAL_BASELINE_FACTS = we.baseline_economic_facts  # patch 前捕获（避免自递归）
_REAL_BASELINE_REGISTRY = model_registry_mod.baseline_registry


def _two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    """LOW 受控 fixture（fix001 同款）：两个 LOW-eligible 候选都有 trustworthy
    economics（deepseek-v4-flash → FRESH discount rank 1；hy4-preview → FRESH
    free rank 0；winner = hy4-preview）。"""
    base = _REAL_BASELINE_FACTS()
    base["deepseek-v4-flash"] = we.EconomicFact(
        model_id="deepseek-v4-flash",
        multiplier=0.17,
        multiplier_raw="x0.17",
        promotion_status=we.PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00",
        valid_until="2026-12-31T00:00:00+08:00",
        source="controlled fixture (ROUTING-002 fresh-runner N2b; test-only, "
        "NOT the real economic probe evidence)",
    )
    return base


def _medium_two_trustworthy_registry() -> dict[str, model_registry_mod.RegistryEntry]:
    """MEDIUM 受控 fixture：真实 registry 基础上**新增**两个 MEDIUM-eligible
    （T3 + QUALIFIED）候选。真实候选零修改。"""
    base = _REAL_BASELINE_REGISTRY()
    for mid in ("med-free", "med-discount"):
        if mid not in base:
            base[mid] = model_registry_mod.RegistryEntry(
                model=mid,
                provider=None,
                applicable_agents=("workbuddy",),
                capability_tier=model_registry_mod.CAP_TIER_T3,
                cost_class=model_registry_mod.COST_CLASS_UNKNOWN,
                locality=model_registry_mod.LOCALITY_UNKNOWN,
                qualification=model_registry_mod.RuntimeQualification(
                    status=model_registry_mod.QUAL_STATUS_QUALIFIED
                ),
            )
    return base


def _medium_two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    """MEDIUM 受控 fixture：真实 facts 基础上新增两个候选的 trustworthy
    economics（med-free rank 0 权威免费 outranks med-discount rank 1 折扣；
    winner = med-free）。真实 facts 零修改。"""
    base = _REAL_BASELINE_FACTS()
    if "med-free" not in base:
        base["med-free"] = we.EconomicFact(
            model_id="med-free",
            multiplier=0.0,
            multiplier_raw="x0.00",
            promotion_status=we.PROMO_STATUS_FREE,
            promotion_factor=0.0,
            valid_from="2026-01-01T00:00:00+08:00",
            valid_until="2026-12-31T00:00:00+08:00",
            source="controlled fixture (ROUTING-002 fresh-runner N1b; test-only, "
            "NOT the real economic probe evidence)",
        )
    if "med-discount" not in base:
        base["med-discount"] = we.EconomicFact(
            model_id="med-discount",
            multiplier=0.5,
            multiplier_raw="x0.5",
            promotion_status=we.PROMO_STATUS_DISCOUNT,
            promotion_factor=0.5,
            valid_from="2026-01-01T00:00:00+08:00",
            valid_until="2026-12-31T00:00:00+08:00",
            source="controlled fixture (ROUTING-002 fresh-runner N1b; test-only, "
            "NOT the real economic probe evidence)",
        )
    return base


def _patched_registry():
    mode = os.environ.get("AAF_TEST_ECON_FACTS_MODE", "").strip() or "real"
    if mode == "medium_two_trustworthy":
        return _medium_two_trustworthy_registry()
    return _REAL_BASELINE_REGISTRY()


def _patched_baseline_facts():
    mode = os.environ.get("AAF_TEST_ECON_FACTS_MODE", "").strip() or "real"
    if mode == "two_trustworthy":
        return _two_trustworthy_facts()
    if mode == "medium_two_trustworthy":
        return _medium_two_trustworthy_facts()
    return _REAL_BASELINE_FACTS()


# patch 必须先于 runner 使用（runner 在调用时做 module 属性查找——decide
# 内部调用 we.baseline_economic_facts()（facts=None 默认）、runner 调用
# model_registry_mod.baseline_registry()，此处替换 module 属性即可）。
model_registry_mod.baseline_registry = _patched_registry
we.baseline_economic_facts = _patched_baseline_facts

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
