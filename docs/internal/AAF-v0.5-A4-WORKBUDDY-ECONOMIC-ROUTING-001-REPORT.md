# AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001 — Implementation Report

> Task: Activate LOW-risk WorkBuddy economic routing（正式启动 A4——WorkBuddy
> validator stage 第一条最小 active economic routing）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（第一条 active-routing slice delivered）；**A4 = STARTED**；
> broader MEDIUM/HIGH/multi-agent routing = 未来 A4 工作（NOT IMPLEMENTED）；
> A5/A6 未进入；A0-A3 = CLOSED / COMPLETE / SYNCED（不变）
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）
> Baseline HEAD: ad90d311c729d6f4ec9c814c0b5630e31af56b1b

## 1. 结论（先给结论）

1. ✅ **A4 正式启动（A4 = STARTED）**：WorkBuddy validator stage 的第一条最小
   active economic routing 已交付——新模块 `ai_agent_framework/workbuddy_routing.py`
   是 WorkBuddy 的 **authoritative** active-routing decision（artifact =
   `workbuddy_active_routing.json`，authoritative=true；env 覆盖 =
   `AAF_WORKBUDDY_MODEL`，adapters 精确追加 `--model <winner>`）。
2. ✅ **复用现有契约，不创建第二套 eligibility 系统**（Requirement 1/3）：候选筛选
   = 既有 `shadow_routing.select_shadow_candidate`（A2 引擎原样调用，role=validator；
   能力充分性 → qualification 顺序保持）；Risk 词汇 = `risk_contract.RISK_CLASSES`
   （缺失 = RISK_UNAVAILABLE，missing ≠ LOW）；经济事实 = A4 prerequisite 建立的
   `workbuddy_economics` 事实层原样消费（cheapness_rank / classify_freshness /
   EconomicFact）——本模块是经济事实层的**唯一**路由消费方。
3. ✅ **激活条件全部满足才 routing_applied=true**（Requirement 2/4/5/6/11）：
   ① stage_agent=workbuddy + role=validator；② 显式 Risk == LOW（missing /
   MEDIUM / HIGH / CRITICAL → Auto）；③ selector eligible >= 2（capability +
   qualification gate；少于两个 → `INSUFFICIENT_ELIGIBLE_CANDIDATES` → Auto）；
   ④ economic facts FRESH + 完整 + 一致（只消费 cheapness_rank ∈ {0,1}；
   STALE / UNKNOWN / incomplete / contradictory → fail closed，绝不进入经济排序）；
   ⑤ 存在确定性可信经济 winner（全部 rank 2 →
   `NO_TRUSTWORTHY_ECONOMIC_WINNER` → Auto）。
4. ✅ **真实 per-run `--model` 执行**（Requirement 9/10）：routing_applied 时
   invocation 精确 = `[<exe>, -p, --output-format, text, -y, --model, <winner>]`
   （**恰好一个 --model**；无 --effort / 无 provider override / 无 fallback model /
   无 retry escalation——transport 既有 bounded retry 复用同一 args）。
5. ✅ **当前 accepted facts 选中 hy4-preview**（Requirement 8）：selection 是
   generic 逻辑（排序键 (cheapness_rank, multiplier, model_id)）产出，**不是
   硬编码特例**——hy4-preview = RANK_AUTHORITATIVE_CHEAP（FRESH + 显式免费 +
   multiplier 0.0 + promotion_factor 0.0，窗口 2026-08-28..2026-09-11）；
   deepseek-v4-flash（freshness UNKNOWN discount）被经济排除但仍计入 eligible
   候选（≥2 gate）；selector 默认（deepseek-v4-flash）与 economic winner
   （hy4-preview）在 artifact 中明确区分（selector_selected vs selected）。
6. ✅ **经济性绝不使 ineligible 候选 eligible**（Requirement 4/15）：经济选择只
   作用于 selector 已 eligible 的候选；hy3（FRESH 免费但 tier=None +
   qualification=unknown）绝不被选中；capability/qualification 先于 economics。
7. ✅ **无 silent fallback**（Requirement 12）：`fallback_used` 恒为 false（fixed
   semantic + validate fail-closed，任何 True 违规）；routing 后 invocation 失败
   按既有异常语义如实 FRAMEWORK_ERROR（链中断 → WAITING），绝不自动退回 Auto /
   换模型；transport retry 复用同一 routed args（无隐藏 Auto 路径，fresh-process
   N3 证明）。
8. ✅ **权威 artifact 可审计且与 Auto 语义区分**（Requirement 13/14）：
   `workbuddy_active_routing.json` 记录 agent/stage、risk + risk_source、candidate
   set、eligible、economically_trustworthy / economically_excluded（含 reason）、
   economic facts used（逐候选 multiplier/promotion/freshness/cheapness_rank +
   来源）、selected、routing_applied、routed_model、fallback_used=false、
   authority reason / no-route reason、invocation 引用、freshness_reference_time；
   routing_applied=false 时 selected/routed_model 必须为 None（validate fail
   closed——Auto 保持时绝不声称模型路由）。
9. ✅ **Hermes A3 路由零修改**（Requirement 16）、**Codex 零修改**（Requirement 17）：
   变更只新增 workbuddy stage 分支（决策 + 原子写 artifact + env apply/restore +
   stage ref）；A3 active_routing.json / shadow_observation.json 语义不变。
10. ✅ **测试 + fresh-runner 全绿**：34 项新增聚焦测试（tests/test_a4_workbuddy_routing.py，
    Req 15 全矩阵）+ 既有 economics consumer 测试同步 = 定向 304 passed / 1 skipped；
    全量 non-GUI 套件零回归（见 §6）；fresh-runner N+1 3/3（见 §7）；既有 4 个
    A4 prerequisite fresh-runner 驱动（N1 LOW 期望同步为 routed 形状）复跑全绿 +
    A3 驱动复跑全绿。

## 2. 实现

### 2.1 新模块 `ai_agent_framework/workbuddy_routing.py`

- `decide_workbuddy_route(risk_class, role, stage_agent, registry, facts=None, now=None, *, risk_source, registry_source, economic_facts_source)`：
  确定性纯逻辑决策（复用 selector；经济选择消费 fact layer）。校验 fail closed：
  未知 risk_class / 非法 role / 空 agent / 非 dict registry / 非 dict facts /
  naive now → ValueError。
- Gate 顺序（第一个失败的 gate 决定 reason）：
  `AGENT_NOT_WORKBUDDY` → `ROLE_NOT_VALIDATOR` → `RISK_UNAVAILABLE` →
  `RISK_NOT_LOW` → `INSUFFICIENT_ELIGIBLE_CANDIDATES`（< 2 eligible）→
  经济选择（rank 2 全部 → `NO_TRUSTWORTHY_ECONOMIC_WINNER`）→
  `WORKBUDDY_ECONOMIC_ROUTE_APPLIED`。
- 经济排序键 = (cheapness_rank, multiplier, model_id)：rank 0（权威免费）outranks
  rank 1（已知新鲜折扣）；rank 1 内更低 multiplier 获胜；经济完全相等 → model_id
  字典序确定性 tie-break（输入顺序无关，与 A2 shadow engine 同一惯例）。
- 经济排除 reason 词汇：ECON_STALE / ECON_FRESHNESS_UNKNOWN / ECON_INCONSISTENT
  （FRESH 但字段缺失/矛盾/无促销/全价——fact-layer 严格 gate）/ ECON_FACT_MISSING。
- `validate_workbuddy_routing`（schema_version / authoritative=true /
  fallback_used=false / routing_applied=True → selected==routed_model 非空 /
  routing_applied=False → selected+routed_model 必须 None / risk_source 契约）。
- `save_workbuddy_routing` / `load_workbuddy_routing`（原子写，同 A3 约定）。
- `apply_workbuddy_model_env` / `restore_workbuddy_model_env`（AAF_WORKBUDDY_MODEL
  精确 apply/restore；非 applied record apply → ValueError）。

### 2.2 `adapters.py`

- `_workbuddy_invocation(prompt, env, model=None)`：model 非 None 时精确追加
  `['--model', model]`（恰好一个；无 --effort）。
- `run_agent` workbuddy 分支读取 `AAF_WORKBUDDY_MODEL` env 覆盖并透传（无覆盖 →
  model=None → 与 A4 之前完全一致，CodeBuddy Auto）；transport retry 复用同一 args。

### 2.3 `runner.py`

- workbuddy stage 新增分支：解析 snapshot Risk → `decide_workbuddy_route(...)`
  （facts=None 缺省 baseline；now = 真实 wall clock）→ 原子写
  `workbuddy_active_routing.json`（写失败 → fail closed，无审计证据不得路由）→
  routing_applied 时 apply env（observation 后 restore，绝不泄漏）→ stage result
  携带 `workbuddy_active_routing_ref`。Hermes 分支零改动。

### 2.4 `workbuddy_economics.py`

- docstring / per-fact notes 同步：事实层唯一路由消费方 = workbuddy_routing；
  生产 invocation 仅在 A4 routing 生效时追加 --model；A2/A3 权威（adapters /
  shadow_routing / model_registry / active_routing / cost_guard）source-level 零
  直接引用保持（runner 只经 workbuddy_routing 消费）。

## 3. 行为验证（决策矩阵）

| 场景 | routing_applied | selected / routed_model | reason token |
|---|---|---|---|
| LOW + 2 eligible + fresh trustworthy economics（baseline facts @ 2026-09-02） | true | hy4-preview | WORKBUDDY_ECONOMIC_ROUTE_APPLIED |
| missing Risk | false | None | RISK_UNAVAILABLE |
| MEDIUM / HIGH / CRITICAL | false | None | RISK_NOT_LOW |
| 1 eligible candidate only | false | None | INSUFFICIENT_ELIGIBLE_CANDIDATES |
| stale economics（窗口过期） | false | None | NO_TRUSTWORTHY_ECONOMIC_WINNER |
| unknown economics（无窗口） | false | None | NO_TRUSTWORTHY_ECONOMIC_WINNER |
| contradictory economics（free+nonzero factor 等） | false | None | NO_TRUSTWORTHY_ECONOMIC_WINNER |
| eligible 候选无事实条目 | false | None | NO_TRUSTWORTHY_ECONOMIC_WINNER |
| capability-insufficient / qualification-unknown | （gate 先排除） | — | CAPABILITY_INSUFFICIENT / QUALIFICATION_UNKNOWN |
| rank 1 内更低 multiplier | true | 低 multiplier 候选 | WORKBUDDY_ECONOMIC_ROUTE_APPLIED |
| 经济平局 | true | model_id 字典序 | WORKBUDDY_ECONOMIC_ROUTE_APPLIED |

## 4. 关键决策说明

- **≥2 gate 是 eligible（capability+qualification）计数**，经济信任度作用于
  选择（谁可获胜）：当前 facts 下只有 hy4-preview 经济可信，但 deepseek-v4-flash
  仍计入 eligible 计数（Req 8/fresh-runner A 要求当前 facts 选择 hy4-preview）。
- **经济 winner 可以比 selector 默认更优**：selector 默认（deepseek-v4-flash，
  cost/locality 同 rank 的 key tie-break）与 economic winner（hy4-preview）分离，
  artifact 双字段记录——经济选择只对 eligible 候选排序，从不引入新候选。
- **rank 2（含 FRESH 全价/无促销）永不进入经济排序**：与 fact-layer 设计一致
  （RANK_UNKNOWN_OR_STALE = STALE/UNKNOWN/无促销/全价/字段缺失矛盾，绝不进入
  已知经济排序）；routing 只选择「可证明更优」的候选，全价候选不声称经济 winner。
- **freshness 参考时间 = 决策时刻（wall clock）**：promo 窗口过期 → 自动 fail
  closed 到 Auto（hy4-preview 窗口 2026-09-11 后 N1 如实不再路由；刷新 =
  重跑 economic probe）。artifact 记录 freshness_reference_time 供审计。
- **env override 机制与 A3 一致**（AAF_WORKBUDDY_MODEL ↔ AAF_HERMES_MODEL）：
  runner 决策 → env 覆盖 → adapters 透传；保持 run_agent 调用签名不变（既有
  (agent, prompt, workspace) mock 形态零破坏）。

## 5. 范围边界（已遵守）

- 无 MEDIUM/HIGH active model routing、无 effort routing、无 automatic fallback、
  无 Cost Gate UX、无 health polling/quarantine、无 runtime requalification loop、
  无 Hermes（A3）路由变更、无 Codex 路由变更、无 A5/A6、无本 slice 之外的
  multi-agent routing。

## 6. 测试

- 新增：`tests/test_a4_workbuddy_routing.py`（34 项）——Req 15 全矩阵
  （LOW 双合格 + fresh economics → applied + 经济 winner / missing + MEDIUM +
  HIGH + CRITICAL → Auto / 单 eligible → Auto / stale + unknown + contradictory
  economics → Auto / capability + qualification 先于 economics / 经济成本不能绕过
  资格 / 无 --effort / 无 fallback / 确定性输入顺序无关 + 经济平局 tie-break /
  artifact authority 语义（Req 13/14）/ env apply-restore / runner 集成
  LOW+HIGH+missing / 真实 argv 恰好一个 --model）。
- 同步：`tests/test_a4_workbuddy_economics.py` consumer 测试改为「唯一消费方 =
  workbuddy_routing」契约（A2/A3 权威 source-level 零直接引用保持）。
- 定向结果：**304 passed / 1 skipped**（新增 34 + 既有 A4/A3 相关文件）。
- 全量 non-GUI（4-file-deselect，与既往同一排除约定）：见 §8 实际数字。

## 7. Fresh-Runner N+1

`tests/fresh_runner_a4_wb_economic_routing_validation.py` + `_check.py`，3/3：

- **N1（Fresh Runner A：LOW active route）**：全新进程真实 runner 全链
  hermes -> workbuddy -> codex SUCCESS；`workbuddy_active_routing.json`
  routing_applied=true / selected=hy4-preview / routed_model=hy4-preview /
  fallback_used=false / economically_trustworthy=[hy4-preview]；fake codebuddy
  真实子进程 argv 精确 = `-p --output-format text -y --model hy4-preview`
  （恰好一个 --model，无 --effort）；**artifact 与真实 invocation 一致**。
- **N2（Fresh Runner B：HIGH preservation）**：全链 SUCCESS；routing_applied=false /
  routed_model=None；fake codebuddy argv 精确 = `-p --output-format text -y`
  （无 --model）；lifecycle/REPORT 正常。
- **N3（Fresh Runner C：no silent fallback）**：fresh-process 证明 fallback_used
  恒 false（validate fail-closed）、run_agent 的 env 覆盖 → retry args 精确含
  恰好一个 --model 且无 --effort/--provider、retry attempts 复用同一 routed args
  （无隐藏 Auto/model 换路径）、Auto 保持时 artifact 不声称 routed_model、非
  applied record apply → ValueError。

既有驱动复跑：QUALIFICATION / SECOND-CANDIDATE / ECONOMICS / ECONOMICS-FIX-001
（N1 LOW 期望同步为 routed 形状）全绿；A3 / A3-FIX-001 全绿（Hermes 路由零变化）。

## 8. 结果数字

- 定向聚焦测试：304 passed / 1 skipped（tests/test_a4_workbuddy_routing.py +
  economics + fix001 + second_candidate + qualification + discovery +
  active_routing + adapters + model_registry + workbuddy_retry）
- 全量 non-GUI 套件：见执行时实际输出（4-file-deselect，零回归）
- fresh-runner N+1：本任务 3/3；既有 4 个 A4 prerequisite 驱动 + 2 个 A3 驱动复跑全绿
- git：本任务 commit 未 push（review 后同步）

## 9. 未完成项 / 问题

- Unresolved Issues = None（本 slice 内）。
- 未来 A4 工作（NOT IMPLEMENTED，明确不在本 slice）：MEDIUM/HIGH active model
  routing、multi-agent（Codex 等）经济路由、更细经济策略（如 valid_until
  感知的选择、full-price 候选参与经济排序的决策）。
- A5（fallback / Cost Gate UX）/ A6（observation/calibration/runtime
  requalification）未进入。
