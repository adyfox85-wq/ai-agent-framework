# AAF-v0.5-A1-REGISTRY-RISK-001 — Implementation Report

> Task: A1 Registry + Risk — Establish A1 model registry and risk contracts（foundation only）
> Executor: Hermes（AAF Executor stage）2026-08-30
> Status: **IMPLEMENTED（foundation slice）** — 正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查 + Planner 确认（本任务不自行宣布 A1 full closed：Selection Engine / Shadow Routing 等 remaining slices 未实现，见 §6）

## 1. 结论（先给结论）

1. ✅ Model registry 契约已建立（`ai_agent_framework/model_registry.py`）：身份 / 适用 agent / capability tier / cost 分类 / locality / runtime qualification **六个维度严格分离**；cost 词汇复用 `model_observation.COST_CLASSES`（不另造词汇）。
2. ✅ **FREE 绝不隐含 qualified**：`is_usable_candidate` 只由 capability_tier + qualification.status 判定，fail closed；未验证元数据（tier / qualification 未知）绝不静默变成可用候选。
3. ✅ 基线 registry 只填 repository/runtime 证据支持的字段（deepseek-v4-flash 远程成本 UNKNOWN、qwen2.5vl:3b / qwen3:4b 本地 LOCAL_FREE、workbuddy/codex 模型身份 UNKNOWN）；capability tier / health / quota / stability / availability 未验证一律 UNKNOWN；每条非 UNKNOWN 事实带证据引用。
4. ✅ Risk 契约已建立（`ai_agent_framework/risk_contract.py`）：LOW / MEDIUM / HIGH / CRITICAL 四等级 + 初始 tier-floor 映射（逐项对齐已接受的 v0.5 设计）+ 自托管权威区域至少 HIGH + **分类为确定性纯逻辑，零 LLM / 零网络依赖**。
5. ✅ 已决定的 v0.5 设计完整保留：路由优先级（safety/correctness > quality threshold > cash/resource cost > elapsed time）、能力充分性先于成本优化、无 silent paid fallback（零 fallback 代码）。
6. ✅ Hermes FREE-model 用户观察已按证据级别登记 backlog **RW-030**（user-observed runtime constraint；非普遍断言；非永久模型健康结论）。
7. ✅ 范围边界零泄漏：未激活自动路由、未改 Hermes 模型、未实现 A2–A6、未改 cost_guard / runner / router / parser / lifecycle 任何执行路径。
8. ✅ 测试：58 项新增定向测试 + 分块全量 non-GUI **1453 passed / 1 skipped**（1395 基线 + 58 新增，零回归）。
9. ✅ Fresh-runner Run N+1 **本任务不需要**（见 §7：foundation-only，未触碰任何 live 执行/路由 authority 路径）。

## 2. 实现文件（最小集合）

| 文件 | 变更 | 说明 |
|---|---|---|
| `ai_agent_framework/model_registry.py` | 新增 | Model Registry 契约：常量词汇（capability tiers / locality / qualification statuses；cost 复用 model_observation）、`RegistryEntry` / `RuntimeQualification` 数据契约（构造校验 fail closed）、纯逻辑（`is_usable_candidate` / `tier_satisfies` / `free_of_cost`）、序列化（entry/registry ↔ dict，未知枚举 ValueError）、证据化基线（`baseline_entries` / `baseline_registry`）。零 I/O、零网络、零子进程。 |
| `ai_agent_framework/risk_contract.py` | 新增 | Risk 契约：`RISK_CLASSES`（LOW/MEDIUM/HIGH/CRITICAL）、`RiskFloor` + `RISK_FLOORS`（初始 tier-floor 映射）、`RISK_ROLE_OPTIONALITY`（validator T4/optional、reviewer usually none/optional 精确表示）、`floor_for` / `risk_at_least` / `max_risk`（确定性纯函数）、`SELF_HOSTING_AUTHORITY_AREAS`（7 区域）→ 至少 HIGH、`ROUTING_PRIORITY` 契约。零 LLM / 零网络。 |
| `tests/test_model_registry.py` | 新增 | 33 项定向测试（FREE≠qualified、UNKNOWN cost≠FREE、qualification unknown 显式、未知元数据不静默可用、tier/cost 独立、四组合表达、校验 fail closed、序列化 round-trip、基线纪律、范围静态断言）。 |
| `tests/test_risk_contract.py` | 新增 | 25 项定向测试（四等级、tier-floor 映射逐项、自托管区域 ≥ HIGH、确定性、零 LLM/网络、优先级契约）。 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | 新增 **RW-030**（Hermes FREE-model 用户观察）+ header Last Updated。 |
| `docs/internal/PROJECT_STATE.md` | 修改 | §0 v0.5 块：A1 = STARTED + A1 Delivered 摘要 + Next remaining slices + Last Updated。 |
| `docs/internal/AAF-v0.5-A1-REGISTRY-RISK-001-REPORT.md` | 新增 | 本文件。 |

未改动：cost_guard / runner / router / adapters / parser / lifecycle / report / bridge（全部 live 执行路径零修改）；Hermes 全局 config 零修改。

## 3. Model Registry 契约（Requirement 3/4/5）

### 3.1 维度分离（a–f）

| 维度 | 词汇 | 基线事实（有证据） |
|---|---|---|
| (a) model/provider 身份 | 条目 `model` + `provider`；key = `model@provider`（模型未知 → `agent:<agent>`） | deepseek-v4-flash@deepseek；qwen2.5vl:3b@custom；qwen3:4b@custom；agent:workbuddy；agent:codex |
| (b) 适用 agent/stage | `applicable_agents`（空 = 未知/通用） | hermes / workbuddy / codex |
| (c) capability tier | `T0`（最强）… `T4`（最轻/本地级）；None = UNKNOWN | 全部 None（未验证，不发明） |
| (d) cost 分类 | 复用 `model_observation.COST_CLASSES`：LOCAL_FREE / FREE / FREE_PROMO / PAID / UNKNOWN | deepseek-v4-flash → UNKNOWN（A0 REPORT §5/§10：cost 元数据未暴露）；qwen* → LOCAL_FREE（base_url 本地端点证据） |
| (e) locality | local / remote / unknown | deepseek-v4-flash → remote；qwen* → local；workbuddy/codex → unknown |
| (f) runtime qualification | qualified / not_qualified / unknown（+ evidence / observed_at） | 全部 unknown（本任务无健康轮询；未来运行时观测填充） |

### 3.2 关键纯逻辑（确定性、fail closed）

- `is_usable_candidate(entry)`：**仅当** capability_tier 已知 **且** qualification.status == qualified 才 True。成本分类绝不参与 → FREE 不隐含 qualified；UNKNOWN cost ≠ FREE。
- `tier_satisfies(candidate, floor)`：T0 最强；候选/下限任一未知 → False。
- `free_of_cost(cost_class)`：成本维度判定；未知 cost_class → ValueError。
- 构造 / 反序列化校验：未知 tier / cost / locality / qualification → ValueError（fail closed）。

### 3.3 schema 能表达的四种组合（测试覆盖）

free-but-not-qualified / free-and-qualified / paid-or-unknown-cost-and-qualified / health-qualification-unknown —— 全部可构造、可区分、语义正确（`test_schema_expresses_all_required_combinations`）。

## 4. Risk 契约（Requirement 6/7/8）

### 4.1 初始 tier-floor 映射（已接受的 v0.5 设计，逐项保留）

| 风险 | executor | validator | reviewer |
|---|---|---|---|
| LOW | T4 | T4（可选） | 通常无 |
| MEDIUM | T3 | T3 | 可选 |
| HIGH | T2 | T2 | T1/T2 → floor T1 |
| CRITICAL | T1 | T1 | T0/T1 → floor T0 |

角色可选性精确表示：`RISK_ROLE_OPTIONALITY[LOW] = {validator, reviewer}`、`[MEDIUM] = {reviewer}`、`[HIGH]/[CRITICAL] = {}`。

### 4.2 自托管权威区域（Requirement 7）

`SELF_HOSTING_AUTHORITY_AREAS = {runner, router, parser, lifecycle_authority, report_authority, model_routing, cost_gate}` → `risk_for_authority_area()` 一律返回 **HIGH**（至少 HIGH）；未知区域 → ValueError（fail closed，不静默降级）。测试覆盖全部 7 区域。

### 4.3 零额外 LLM 调用（Requirement 8）

- 分类契约全部为确定性纯函数（`floor_for` / `risk_at_least` / `max_risk` / `risk_for_authority_area`），无 I/O、无网络、无子进程。
- 静态断言测试：`risk_contract.py` 依赖图 = stdlib（dataclasses / typing）+ 同 package `model_registry`；无任何 LLM/网络 import。
- 本任务**未把**分类接入 live runner（无兼容性路径需求，Requirement 8 允许仅契约）。

## 5. Hermes FREE-model 观察登记（Requirement 10）

登记于 `docs/internal/AAF_MASTER_BACKLOG.md` **RW-030**（Status OBSERVATION / P1），措辞严格保留证据级别：

- **user-observed / runtime constraint**：真实 Hermes v0.20.5 安装/使用中观察到部分 FREE 标记模型实际不可用、部分可用 FREE 模型可能不稳定；
- **不是**「所有 Hermes 免费模型都坏」的普遍断言；
- **不是**任何具体模型的永久健康 verdict。

对 AAF 的约束：FREE 是价格/成本属性；FREE 不得自动隐含 available / stable / healthy / qualified / sufficient——本 A1 契约据此把 cost_class 与 runtime_qualification 分离（`is_usable_candidate` 与 cost 无关）。

## 6. 范围边界（Requirement 11 — 零泄漏）

未实现 / 未激活：自动模型选择、Hermes 模型自动切换、A2 Shadow Routing、A3 Hermes Free Auto Routing、free fallback、Cost Gate UX、健康轮询、动态隔离、A4–A6、A0 重开、桌面 UI 重设计。

静态断言测试锁定：`model_registry` / `risk_contract` 公开 API 无 select/route/fallback/poll/quarantine/monitor/switch/activate/spawn/run 等任何选择/执行类函数；模块依赖图零网络/零子进程。

## 7. Fresh-runner Run N+1 判定

**不需要。** 本任务为 non-authoritative foundation 契约代码：`model_registry.py` / `risk_contract.py` 未被 runner / router / parser / lifecycle / report / adapters / cost_guard 任何 live 执行路径引用或导入（零 import 变更），未修改任何 live execution / model-routing authority 路径。按 TASK fresh-runner 规则，Run N+1 不构成接受前置条件。

## 8. 测试与命令/结果（Requirement 9/13）

```
python -m pytest tests/test_model_registry.py tests/test_risk_contract.py -q
  → 58 passed in ~0.1s
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_e_e2e.py
  → 1433 passed, 1 skipped, 29 deselected（53.8s）
python -m pytest tests/test_phase_e_cancel_ui_e2e.py tests/test_phase_e_force_e2e.py \
  tests/test_phase_e_e2e.py -q   → 20 passed
```

合计 **1453 passed / 1 skipped**（1395 FIX-006 基线 + 58 新增，零下降；RW-029 环境 flake 按项目惯例分块隔离）。

定向覆盖矩阵（Requirement 9）：
- **Registry**：FREE 不隐含 qualified（unknown/not_qualified 均不可用）；UNKNOWN cost ≠ FREE 且序列化保持；qualification unknown 显式（默认 + 有 tier 仍不可用）；未知元数据（tier=None / 双未知）不静默可用；tier 与 cost 独立（交叉构造 + 判定互不影响）；schema 四组合；构造/反序列化 fail closed；基线无发明 tier/价格/健康 + 证据引用 + key 唯一。
- **Risk**：四等级全表示 + 严重度单调；tier-floor 映射逐项精确断言；7 个自托管区域全部 ≥ HIGH；未知区域/未知风险 ValueError；确定性（重复调用一致、max_risk 顺序无关）；依赖图静态断言零 LLM/网络；优先级契约顺序。

## 9. Git / 状态

- 基线：main @ `75c79eea96750d15df4692abdfc7fd70c9897302`（= origin/main，ahead/behind 0/0，tracked CLEAN）。
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；**未 push**（Requirement 12：A1 提交须经独立 review 后同步；与 A0 FIX-003/005/006 惯例一致）。
- PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`scripts/start_bridge_hidden.vbs`、`AAF_TASK004_PROCESS_CHECK.txt`）未删除、未 clean。
- 无 force push、无历史改写。

## 10. 验证状态 / 已知限制

- WorkBuddy 独立验证 + Codex 架构/政策保真/范围审查由 route 阶段（hermes → workbuddy → codex）执行并记录；若发现 blocking 按惯例开 FIX。
- 已知限制（如实）：基线 registry 不含任何 capability tier / 健康结论（无证据）；qualification 观测需 A2+（shadow / 实况）填充；codex 模型 catalog 不可枚举（documented limitation）。
- A1 = STARTED（foundation slice delivered）；**未**宣布 A1 full closed（Selection Engine / Shadow Routing / Hermes candidate tier 赋值 / 运行时 qualification 观测等 remaining slices 未实现）。
