# AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001 — Implementation Report

> Task: Tighten WorkBuddy economic fail-closed semantics（修复 A4 economic prerequisite
> 的两个已知 blocker，确保缺失或自相矛盾的经济元数据永远不能被当作 authoritative
> cheap/free）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Parent: AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001（commit 3aeb5a91c01dfb9f9c97c8ce2752e41b3a2e9e08，WAITING）
> Codex = REQUEST_CHANGE（两个 blocking findings）；parent 尚未 push
> Status: **IMPLEMENTED**（FIX 只修 economic fact layer 的 gate；A4 保持 **NOT STARTED**）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件）

## 1. 结论（先给结论）

1. ✅ **blocking finding #1 已关闭**（multiplier=None + FRESH discount 不再获得已知
   便宜 rank）：`cheapness_rank` 的 RANK_FRESH_DISCOUNT（已知新鲜折扣）现在要求
   `economic_fields_consistent(fact)`——multiplier 已知且有效 + promotion_factor
   已知且有效 + promotion status 与二者不矛盾。缺失/矛盾 → RANK_UNKNOWN_OR_STALE，
   该 fact 绝不进入已知经济排序（Requirement 1/2/4）。
2. ✅ **blocking finding #2 已关闭**（authoritative free 未要求 promotion_factor==0.0）：
   `is_authoritative_cheap` 现为四条件同立：freshness==FRESH + promotion_status==free
   + multiplier 已知==0.0 + **promotion_factor 已知==0.0**（Requirement 3）。
3. ✅ **全部 fail-closed 场景收口**（Requirement 4）：multiplier=None /
   promotion_factor=None / stale / unknown freshness / free+nonzero promotion_factor /
   free+nonzero multiplier / discount 内部矛盾（factor=0.0、factor=1.0、
   multiplier=0.0）→ 一律不是 authoritative cheap/free，rank=RANK_UNKNOWN_OR_STALE。
4. ✅ **不扩大经济策略**（Requirement 5）：改动只限 `ai_agent_framework/workbuddy_economics.py`
   的「事实是否足够完整、可信」gate（新增 `economic_fields_consistent` + 收紧
   `is_authoritative_cheap` / `cheapness_rank` / `__post_init__` raw↔parsed 校验）；
   baseline 事实、rank 常量语义、序列化 schema（v1）不变。
5. ✅ **capability/qualification gate 先于 economics 保持**（Requirement 6）：FRESH FREE
   的 hy3/hy4-preview 仍 tier=None + qualification=unknown → ineligible；deepseek-v4-flash
   T4 + QUALIFIED 不变；其余 14 候选 UNKNOWN 不变；selector LOW workbuddy 仍只选
   deepseek-v4-flash（Requirement 8 零 qualification 修改）。
6. ✅ **production WorkBuddy invocation 零修改**（Requirement 7）：CodeBuddy Auto
   `[-p --output-format text -y]`，无 --model/--effort，无 active routing；经济模块
   仍零消费方（routing 代码源码级零 import）。
7. ✅ **测试 + 回归全过**（§5）：27 项新增 adversarial 聚焦测试
   （tests/test_a4_workbuddy_economics_fix001.py）+ 全量 non-GUI 4-file-deselect =
   **1726 passed / 1 skipped / 38 deselected**（HEAD 3aeb5a9 基线 1699 + 27 精确
   零回归）。
8. ✅ **fresh-runner N+1 通过**（§6）：4/4 —— N1 LOW 全生命周期 SUCCESS（fake codebuddy
   argv 精确 Auto 无 --model/--effort）；N2 fresh-process artifact 可读 + 路由权威零
   变化；N3 fresh-process artifact 重新生成+再读；N4 fresh-process malformed /
   incomplete / contradictory facts fail closed。
9. ✅ **artifact 事实不变**：economic_facts.json 以收紧后模块重新生成，15 候选事实
   （multiplier/promotion/validity/freshness）逐项不变；hy3/hy4-preview 仍 FRESH +
   authoritative cheap @ observed_at。
10. ✅ **状态更新最小化**：PROJECT_STATE.md / backlog 只记录本 FIX；**A4 未标 STARTED**。

## 2. Scope Boundary

本任务 = 只修 economic fact layer 的 fail-closed gate（Codex REQUEST_CHANGE 收口）。

- **In scope**：`economic_fields_consistent` 新增（完整性+一致性 gate）；
  `is_authoritative_cheap` 增加 promotion_factor==0.0 条件；`cheapness_rank`
  RANK_FRESH_DISCOUNT 增加 gate 条件；`EconomicFact.__post_init__` 增加
  multiplier_raw→multiplier 可解释性校验；模块 docstring/常量注释/authority 文本
  同步；27 项 adversarial 聚焦测试；economic_facts.json 重新生成验证；fresh-runner
  N+1（4 场景）；文档（PROJECT_STATE / backlog / 本 REPORT）。
- **Out of scope（未触碰）**：经济策略本身（ordering 规则、routing 接入、fallback、
  Cost Gate UX、health/quarantine、runtime requalification）；model_registry /
  adapters / shadow_routing / active_routing / runner / cost_guard 源码；WorkBuddy
  qualification（deepseek-v4-flash T4+QUALIFIED 等 registry 数据）；Hermes/Codex
  路由；A5/A6；parent commit（不 amend，不 push）。

## 3. Blocking Findings 与修复对照（证据）

| Codex finding | 修复前行为 | 修复后行为 | 验证 |
|---|---|---|---|
| #1 multiplier=None + FRESH discount 仍可能获得已知便宜 rank | `cheapness_rank` 只看 FRESH+discount → RANK_FRESH_DISCOUNT（1） | FRESH discount 需 `economic_fields_consistent`（multiplier+factor 均已知且 status 不矛盾）→ 缺失 → RANK_UNKNOWN_OR_STALE（2） | `test_fresh_discount_multiplier_none_not_authoritative`；N4 fresh-process check |
| #2 authoritative free 未要求 promotion_factor == 0.0 | free + multiplier=0.0 + factor=1.0 → is_authoritative_cheap=True | 四条件同立（FRESH+free+multiplier 0.0+factor 0.0）→ factor≠0 → False | `test_fresh_free_zero_multiplier_factor_1_not_authoritative`；N4 fresh-process check |

## 4. 修改的文件

| 文件 | 修改 |
|---|---|
| `ai_agent_framework/workbuddy_economics.py` | 新增 `economic_fields_consistent`；`is_authoritative_cheap` 增加 promotion_factor==0.0；`cheapness_rank` discount 分支增加一致性 gate；`__post_init__` 增加 multiplier_raw 可解释性校验（无法解析/不一致 → ValueError）；模块 docstring / rank 常量注释 / facts_to_dict authority 文本同步 |
| `tests/test_a4_workbuddy_economics_fix001.py`（新增） | 27 项 adversarial 聚焦测试（Requirement 9 全覆盖 + 附加） |
| `tests/fresh_runner_a4_wb_econ_fix001_validation.py`（新增） | FIX-001 fresh-runner N+1 驱动（N1 生命周期 / N2 artifact+authority / N3 重新生成+再读 / N4 fail-closed） |
| `tests/fresh_runner_a4_wb_econ_fix001_failclosed_check.py`（新增） | N4 fresh-process fail-closed 检查脚本 |
| `docs/internal/PROJECT_STATE.md` | Last Updated 链 + A4 Economics FIX-001 Delivered 小节 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | Last Updated 链 + CAP-002 Current Implementation 追加 FIX-001 语义收紧记录 |

未修改：model_registry.py / adapters.py / shadow_routing.py / active_routing.py /
runner.py / cost_guard.py（源码级零变化，测试锁定零 import）；parent 的
economic_probe 只读证据与 generate_facts_artifact.py 不变（artifact 以收紧后模块
重新生成，事实逐项不变）。

## 5. 测试与回归

```text
python -m pytest tests/test_a4_workbuddy_economics_fix001.py tests/test_a4_workbuddy_economics.py -q
  → 56 passed（27 新增 + 29 既有）（~0.2s）
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py \
  --deselect tests/test_phase_f_e2e.py
  → 1726 passed, 1 skipped, 38 deselected（~67s）
```

对账：HEAD（3aeb5a9）基线 = 1699 passed / 1 skipped / 38 deselected；1699 + 27 新增 =
1726 精确零回归（同一可复现排除约定：4 个真实桌面 E2E 文件 --deselect）。

新增聚焦测试覆盖（Requirement 9 逐项）：
- FRESH discount + multiplier=None → unknown/non-authoritative rank（blocking #1 反例）
- FRESH discount + promotion_factor=None → non-authoritative
- FRESH free + multiplier=0.0 + promotion_factor=0.0 → authoritative free（rank 0）
- FRESH free + multiplier=0.0 + promotion_factor=1.0 → non-authoritative（blocking #2 反例）
- FRESH free + multiplier=0.0 + promotion_factor=0.5 → non-authoritative
- FRESH free + multiplier>0（factor=0.0 与 factor>0 两态）→ non-authoritative
- STALE / UNKNOWN（完整或不完整字段）永不 authoritative cheap/free
- discount 内部矛盾（factor=0.0 / factor=1.0 / multiplier=0.0 / 双缺失）→ rank 2
- economic_fields_consistent 完整/一致性纯 gate 判定
- multiplier_raw 无法解释 multiplier（不一致 / 不可解析 / "0x"）→ 构造 ValueError
- capability/qualification precedence 不回归（hy3/hy4-preview 仍 ineligible；
  deepseek-v4-flash T4+QUALIFIED 不变；selector 零变化）
- production WorkBuddy invocation 不变（Auto，无 --model/--effort）
- 经济模块不被路由代码 import（零消费方保持）

## 6. Fresh-Runner N+1（证据：.aaf/AAF-v0.5-A4-PREREQ-WORKBUDDY-ECONOMICS-001-FIX-001/fresh-runner-validation/）

```text
[N1] LOW lifecycle + Auto invocation -> PASS (argv='-p --output-format text -y')
[N2] fresh-process artifact+authority -> PASS
[N3] fresh-process artifact regeneration+re-read -> PASS
[N4] fresh-process fail-closed -> PASS
fresh-runner A4-WB-ECONOMICS-FIX-001 N+1: failures=0
```

- N1：全新 python 进程运行真实 runner（fake hermes/codebuddy/codex .bat 真实 child
  process），显式 Risk: LOW 任务全生命周期 SUCCESS + REPORT/context_manifest 正常；
  fake codebuddy marker ARGS 精确 = `-p --output-format text -y`（零 --model/--effort）。
- N2：fresh-process 读取 economic_facts.json（facts_from_dict 解析、15 候选齐全、
  freshness 与 classify_freshness(observed_at) 一致）+ 路由权威零变化（selector LOW
  仍只选 deepseek-v4-flash）。
- N3：fresh-process 运行 generate_facts_artifact.py（子进程，exit 0）→ 重新生成的
  economic_facts.json 可再读（facts_from_dict 解析、hy3/hy4-preview 仍 FRESH +
  authoritative cheap @ observed_at）——经济 artifact 仍可正常生成/读取。
- N4：fresh-process fail-closed 检查——multiplier=None / promotion_factor=None 的
  FRESH discount 无已知便宜 rank；free+nonzero factor / free+nonzero multiplier /
  discount 内部矛盾 / STALE / UNKNOWN / raw 无法解释 parsed 值 → 一律不权威；
  基线事实（15 候选、hy3/hy4-preview authoritative cheap）与路由权威（invocation
  Auto、selector、零 import）零变化。

## 7. Unresolved Issues

- 无（本 FIX 范围内）。Codex 两个 blocking findings 均已消除；
  WorkBuddy 独立验证 + Codex APPROVE 为 route 后续阶段的接受前置条件。
- 已知记录（非本 FIX 引入，保持父任务记录）：minimax-m2.7 主源 x0.26 vs CLI
  catalog x0.19 差异（记录在案、不按假设消解）；daily-only 促销无日期窗口 →
  freshness=UNKNOWN（fail closed，设计内行为）。

## 8. 状态

- A4 = **NOT STARTED**（正式实现 scope：economic routing / active --model selection /
  multiplier ordering / RemoteConfig routing consumption 全部未开始）。
- A5/A6 未进入。Boundaries 全部保持：无 active WorkBuddy routing、无 economic
  selection wiring、无 fallback、无 Cost Gate UX、无 health/quarantine、无 runtime
  requalification、无 Hermes 变更、无 Codex routing。
- 未 push（parent 亦未 push；review 通过后同步）。
