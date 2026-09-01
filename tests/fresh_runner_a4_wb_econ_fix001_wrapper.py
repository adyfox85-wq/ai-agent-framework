"""AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 fresh-runner wrapper.

与 tests/fresh_runner_wrapper.py / fresh_runner_a3_fix001_wrapper.py 同一技术：
在导入 runner 之前完成模块级 patch，只影响 fresh-process 验证，生产代码零改动
（runner.py / workbuddy_routing.py / workbuddy_economics.py 不含任何 test hook）。

1. fake bin 前置到 adapters / cost_guard 的 CLI discovery PATH（AAF_TEST_FAKE_BIN）：
   真实 subprocess 拉起 fake hermes.bat / codebuddy.bat / codex.bat。
2. 按 AAF_TEST_ECON_FACTS_MODE 注入 runner 的经济事实输入
   （patch workbuddy_routing 命名空间里的 we.baseline_economic_facts）：
   - real（默认）：零注入 —— runner 使用真实 baseline_economic_facts()
     （N1：LOW 任务在真实 facts 下经济过滤后只有 hy4-preview 一个可信候选 →
     routing_applied=false → CodeBuddy Auto，FIX-001 核心证明）。
   - two_trustworthy：受控 fixture —— 把 deepseek-v4-flash 的经济事实替换为
     FRESH discount（rank 1，multiplier 0.17，字段完整一致），hy4-preview 保持
     FRESH free（rank 0）。两个 eligible 候选都有 trustworthy economics →
     routing_applied=true，winner = hy4-preview（rank 0 权威免费 outranks rank 1）。
     明确标注为受控 deterministic 场景（Req 14：fixture/evidence injection 与
     真实 runtime N1 区分）；fake codebuddy marker 必须显示恰好一个
     --model hy4-preview。

用法：
    python tests/fresh_runner_a4_wb_econ_fix001_wrapper.py <TASK.md> --workspace <ws> --output <out>

env:
    AAF_TEST_FAKE_BIN         fake bin 目录（hermes.bat / codebuddy.bat / codex.bat）
    AAF_TEST_ECON_FACTS_MODE  real | two_trustworthy（缺省 real）
    FAKE_CODEBUDDY_MARKER     fake codebuddy chat 写入的 argv 证据 marker 路径
"""
from __future__ import annotations

import os

from ai_agent_framework import adapters as adapters_mod
from ai_agent_framework import cost_guard as cost_guard_mod
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


def _two_trustworthy_facts() -> dict[str, we.EconomicFact]:
    """受控 fixture（FIX-001 Req 14）：两个 eligible 候选**都有** trustworthy
    economics。

    - deepseek-v4-flash → FRESH discount（rank 1，multiplier 0.17，
      economic_fields_consistent=True）——真实事实是 freshness UNKNOWN
      （daily-only 夜间折扣无日期窗口）；本 fixture 只用于受控场景，绝不修改
      真实 baseline / economic_facts 数据。
    - hy4-preview → FRESH free（rank 0，权威免费，窗口 2026-08-28..09-11）。
    经济 winner = hy4-preview（rank 0 outranks rank 1）。
    """
    base = _REAL_BASELINE_FACTS()
    base["deepseek-v4-flash"] = we.EconomicFact(
        model_id="deepseek-v4-flash",
        multiplier=0.17,
        multiplier_raw="x0.17",
        promotion_status=we.PROMO_STATUS_DISCOUNT,
        promotion_factor=0.5,
        valid_from="2026-01-01T00:00:00+08:00",
        valid_until="2026-12-31T00:00:00+08:00",
        source="controlled fixture (FIX-001 fresh-runner N1b; test-only, "
        "NOT the real economic probe evidence)",
    )
    return base


def _patched_baseline_facts():
    mode = os.environ.get("AAF_TEST_ECON_FACTS_MODE", "").strip() or "real"
    if mode == "two_trustworthy":
        return _two_trustworthy_facts()
    return _REAL_BASELINE_FACTS()


# patch 必须先于 runner 使用（runner 在 decide_workbuddy_route 内部调用
# we.baseline_economic_facts()——module 属性查找在调用时发生，此处替换即可）。
we.baseline_economic_facts = _patched_baseline_facts

from ai_agent_framework.runner import main  # noqa: E402  (patch 必须先于 runner 使用)

if __name__ == "__main__":
    main()
