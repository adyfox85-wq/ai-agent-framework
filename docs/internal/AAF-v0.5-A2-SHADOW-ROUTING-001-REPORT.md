# AAF-v0.5-A2-SHADOW-ROUTING-001 — Implementation Report

> Task: A2 Shadow Routing — Establish deterministic shadow-selection engine（observation only，首片）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **IMPLEMENTED（首片交付）→ A2 = STARTED（未 COMPLETE）**；A1 保持 CLOSED / COMPLETE / SYNCED
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **确定性影子选择引擎已建立**（`ai_agent_framework/shadow_routing.py`，纯函数）：输入
   (risk_class, role, stage_agent, registry) → 结构化 `ShadowDecision`；**假设性 / 非权威 /
   零执行影响**——没有任何 live 执行路径 import 或消费它（隔离静态测试锁定）。
2. ✅ **A1 契约原样复用**：`tier_satisfies` / `is_usable_candidate` / `FREE_OF_COST_CLASSES`
   / `floor_for` / `reviewer_allowed` 全部消费 A1 实现，零复制；A1 契约文件零修改。
3. ✅ **能力充分性先于成本**：过滤管线 = role 适用性 → 能力 → qualification → 经济 → tie-break；
   「更便宜但不充分」的候选（FREE T4 on MEDIUM）永不因便宜胜出（测试锁定）。
4. ✅ **FREE 绝不产生 qualification**（Requirement 13）：FREE + not_qualified /
   UNKNOWN qualification 全部排除；UNKNOWN 不静默提升（测试锁定）。
5. ✅ **UNKNOWN 成本保守规则**（Requirement 7）：已知成本 > UNKNOWN；UNKNOWN 永不因成本获胜
   （unknown ≠ free；与 A0 PAID_OR_UNKNOWN fail-closed 对齐）；全部 UNKNOWN 时成本维度如实
   不产生结论，由 locality / key 确定性 tie-break 决定。
6. ✅ **显式 NO_SHADOW_CANDIDATE**（Requirement 9）：无合格候选 → `selected=None` +
   `no_candidate_reason="NO_SHADOW_CANDIDATE: ..."`；无 silent fallback、无 forced choice。
7. ✅ **确定性**（Requirement 6/15）：排序键含 key 全序 tie-break → 候选输入顺序不影响决策；
   重复调用输出完全一致（测试锁定）。
8. ✅ **reviewer / schema 无回归**（Requirement 16/17）：HIGH reviewer T1/T2、CRITICAL T0/T1
   集合语义保持；`decision_from_dict` / A1 `registry_from_dict` schema 严格性（仅真实 int）
   全部测试覆盖。
9. ✅ **实际执行隔离**（Requirement 10/20）：runner / router / adapters / cost_guard / report /
   lifecycle 零修改、零 import；本任务**未**触碰 Hermes `-m`、provider override、WorkBuddy
   --model、Codex model、runner 命令、active Route、Paid Guard、live invocation。
10. ✅ **测试**：47 项新增定向测试（Requirement 15 全矩阵）+ 分块全量 non-GUI 零回归。
11. ✅ **Fresh-runner Run N+1 本任务不需要**（§10：纯非权威 selector，未触碰任何 live
    runner / router / model-invocation / lifecycle / report authority 路径）。

## 2. A2 Scope Boundary（Requirement 20）

本任务 = **A2 首片（observation-only shadow decision logic）**：

- **In scope**：纯选择模块 + 确定性数据契约 + 聚焦测试 + 最小文档/状态更新。
- **Out of scope（本任务显式不做，后续 A2 slice）**：运行期影子观测/集成（shadow
  observation 写入 runner 等）、实况 qualification 观测。
- **A2 boundary（Requirement 10/18/19）**：未改变实际执行的模型选择；未静默调用其他
  provider；未做付费 fallback；未激活 Hermes 自动免费路由 / WorkBuddy 经济路由；未实现
  fallback policy / 动态健康监控 / 动态隔离 / 自动 quarantine / 动态降级 / 基准循环 /
  Cost Gate UX / 观测-校准循环 / A3-A6 任何功能。

## 3. Reused A1 Contracts（Requirement 1/12/17）

| A1 契约 | 消费方式 | 复制？ |
|---|---|---|
| `model_registry.RegistryEntry` / `RuntimeQualification` | 直接作为候选数据结构 | 否 |
| `model_registry.tier_satisfies` | 能力充分性（executor/validator 下限） | 否 |
| `model_registry.is_usable_candidate` | qualification 闸门（tier 已知 + qualified） | 否 |
| `model_registry.FREE_OF_COST_CLASSES` | 经济 rank 0 集合（零现金类并列） | 否 |
| `model_registry` locality / qualification 词汇 | 排序维度与排除原因 | 否 |
| `risk_contract.floor_for` / `RISK_FLOORS` | executor/validator 下限 + reviewer 允许集合 | 否 |
| `risk_contract.reviewer_allowed` | reviewer 集合成员判定（T0 最强；集合外更强也拒绝） | 否 |
| `risk_contract` RISK_CLASSES / role 词汇 | 输入校验 | 否 |
| `model_observation.COST_CLASSES`（经 model_registry） | 经济排序（不发明价格） | 否 |

基线诚实（Requirement 12）：A1 基线 registry 的 5 个真实条目（deepseek-v4-flash /
qwen2.5vl:3b / qwen3:4b / agent:workbuddy / agent:codex）全部 tier=None +
qualification UNKNOWN → 影子选择如实返回 NO_SHADOW_CANDIDATE，**不发明任何
capability / qualification 事实**（测试锁定）。Hermes FREE-model 用户观察（RW-030）
不升级为 per-model 健康事实。

## 4. Shadow Selection Contract（Requirement 3）

```python
select_shadow_candidate(risk_class: str, role: str, stage_agent: str,
                        registry: dict[str, RegistryEntry]) -> ShadowDecision
```

`ShadowDecision`（frozen dataclass，可审计）字段：

- `risk_class` / `role` / `stage_agent`：决策上下文。
- `required_floor`：executor/validator 的下限 tier；reviewer → None（能力表达为允许集合）。
- `allowed_tiers`：reviewer 允许集合（HIGH=("T1","T2")、CRITICAL=("T0","T1")）；executor/validator → ()。
- `candidates_considered`：排序后的全部 registry keys。
- `excluded`：`(candidate, reason)` 排除记录（排序）。
- `eligible`：通过全部过滤的候选 keys（排序）。
- `selected`：影子选中 key（无候选 → None）。
- `selection_reason`：REASON_SOLE_ELIGIBLE / REASON_LOWEST_KNOWN_COST /
  REASON_COST_TIE_LOCALITY / REASON_COST_LOCALITY_TIE_KEY（无候选 → None）。
- `deciding_dimension`：sole_eligible / cost / locality / key（无候选 → None）。
- `no_candidate_reason`：无候选时 = "NO_SHADOW_CANDIDATE: ..."（显式、可审计）。

序列化：`decision_to_dict` / `decision_from_dict`（schema_version=1，严格类型校验）。
未知 risk / role / 空 stage_agent / 非 dict registry → ValueError（fail closed）。

## 5. Filtering Pipeline（Requirement 6）

```
A. stage/role 适用性   applicable_agents 空（未知/通用）或含 stage_agent → 通过
                      否则 → ROLE_NOT_APPLICABLE
B. 能力充分性          executor/validator: tier_satisfies(tier, floor)（tier None → False）
                      reviewer: reviewer_allowed(risk, tier)（集合成员）
                      不满足 → CAPABILITY_INSUFFICIENT
C. qualification       is_usable_candidate(entry)（A1 原样消费；FREE 不参与）
                      不满足 → NOT_QUALIFIED / QUALIFICATION_UNKNOWN（按 status 区分）
D. 经济偏好            economic_rank：零现金类（LOCAL_FREE/FREE/FREE_PROMO）并列 0
                      < PAID(1) < UNKNOWN(2)；已知成本 > UNKNOWN
E. 确定性 tie-break    locality local(0) < remote(1) < unknown(2) → key 字典序全序
                      （排序键 = (economic_rank, locality_rank, key) → 输入顺序无关）
```

排除原因词汇（Requirement 14）：`ROLE_NOT_APPLICABLE` / `CAPABILITY_INSUFFICIENT` /
`NOT_QUALIFIED` / `QUALIFICATION_UNKNOWN` / `UNSUPPORTED`（registry 值不是
RegistryEntry = invalid registry data）。管线顺序保证：**能力评估先于任何成本/局部偏好**；
local/free 偏好严格 subordinate（Requirement 8）。

## 6. Qualification Semantics（Requirement 5/13）

- 候选**只有**在 `qualification.status == qualified` 且 tier 已知时才进入经济选择
  （经 `is_usable_candidate`，A1 契约原样）。
- UNKNOWN qualification 显式保留为排除原因 `QUALIFICATION_UNKNOWN`，**绝不静默提升**。
- FREE 是成本属性：FREE + UNKNOWN qualification 与 FREE + not_qualified 都被排除；
  FREE 绝不隐含 available / stable / healthy / qualified / sufficient。
- 未发明任何 live 健康事实；静态 qualification 字段（A1 已可表达）被消费，动态观测未实现。

## 7. Economic Ordering Rule（Requirement 7，文档化 + 测试锁定）

1. 只使用 registry cost_class 分类（不发明数值价格）。
2. 已知成本 rank：零现金类 {LOCAL_FREE, FREE, FREE_PROMO}（= A1 FREE_OF_COST_CLASSES，
   同为 0 现金 → **并列**）< PAID。
3. **UNKNOWN 保守规则**：任何已知 cost_class 排在 UNKNOWN 之前；UNKNOWN **永不因成本
   获胜**。理由：`unknown ≠ free`（A1/RW-030 纪律）——把 UNKNOWN 当作「可能更便宜」即
   假设它可能是免费（伪造排序方向）；A0 Paid Guard 同样把未知成本按 PAID_OR_UNKNOWN
   fail-closed 处理。当剩余候选全部 UNKNOWN（成本无可比较）时，成本维度不产生结论，
   由 locality / key tie-break 决定，决策如实记录（测试：`test_all_unknown_cost_tie_uses_key_tiebreak`）。
4. 本地偏好（locality）只是次级 tie-break，严格排在充分性与 qualification 之后
   （测试：remote FREE 胜过 local PAID）。

## 8. No-Candidate Semantics（Requirement 9）

无合格候选（含空 registry）→ `selected=None`、`selection_reason=None`、
`deciding_dimension=None`、`no_candidate_reason="NO_SHADOW_CANDIDATE: <detail>"`。
无 silent fallback、无 forced choice、无隐藏降级。

## 9. Actual Execution Isolation（Requirement 10）

- 本模块零 I/O、零网络、零子进程、零 LLM、零环境变量读取（静态断言测试）。
- live 执行路径（runner / router / adapters / cost_guard / report / project_boundary /
  task_lifecycle / context_packet / reconcile / finalize_cancelled / task_validation）
  **零 import** shadow_routing（静态断言测试逐一扫描）。
- 未触碰：Hermes `-m` / provider override / WorkBuddy --model / Codex model / runner
  执行命令 / active Route / Paid Guard 授权 / live provider invocation。

## 10. Fresh-runner Run N+1 判定（Requirement 20）

**不需要。** 本任务 = 纯 non-authoritative selector，未连接 live runner / router 执行
路径、未触碰 model invocation / lifecycle / report authority（零 import 变更，隔离测试
证明）。按 TASK fresh-runner 规则，不构成自托管路由变更，Run N+1 不是接受前置条件。

## 11. Tests（Requirement 15 全矩阵 + 守卫）

`tests/test_shadow_routing.py`（47 项新增）：

| Requirement 15 项 | 测试 |
|---|---|
| LOW + qualified T4 | `test_low_task_qualified_t4_selected` |
| MEDIUM 拒绝不充分 T4 | `test_medium_task_rejects_insufficient_t4` |
| HIGH 接受充分 qualified T2 | `test_high_task_accepts_sufficient_qualified_t2` |
| CRITICAL 能力下限强制 | `test_critical_task_enforces_capability_floor` |
| FREE 但不合格不胜出 | `test_free_but_unqualified_candidate_does_not_win` |
| FREE + UNKNOWN qualification 不静默合格 | `test_free_with_unknown_qualification_not_silently_qualified` |
| 更便宜合格候选胜出 | `test_cheaper_qualified_wins_over_expensive_equivalent` |
| 更便宜但不充分落败 | `test_cheaper_but_insufficient_loses` |
| UNKNOWN 成本确定性 | `test_unknown_cost_loses_to_known_free` / `test_unknown_cost_loses_to_known_paid` / `test_all_unknown_cost_tie_uses_key_tiebreak` / `test_economic_rank_function_contract` |
| 无候选显式结果 | `test_no_valid_candidate_returns_explicit_no_candidate` / `test_empty_registry_no_candidate` |
| role-inapplicable 排除 | `test_role_inapplicable_candidate_excluded` |
| 输入顺序无关 | `test_input_order_does_not_alter_decision` / `test_selection_is_pure_no_env_or_side_effects` |

守卫（超越 Requirement 15 最小集）：
- reviewer 语义回归（Req 16）：HIGH T1/T2 允许、T0 拒绝；CRITICAL T0/T1 允许、T2 拒绝；
  `allowed_tiers` 记录精确。
- schema 严格性（Req 17）：`decision_from_dict` 拒绝 bool / float / str / 容器 / None /
  缺失 / 999（parametrized 10 值）；A1 `registry_from_dict` 严格性 spot-check 无回归。
- 基线诚实（Req 12/13）：A1 基线 registry → NO_SHADOW_CANDIDATE，排除原因逐条断言。
- 输入校验 fail closed（未知 risk / role / 空 stage_agent / 非 dict）。
- 隔离/范围静态断言（Req 10/18/19）：依赖图零 I/O；live 模块零 import；无副作用 API。

命令与结果：

```
python -m pytest tests/test_shadow_routing.py tests/test_model_registry.py \
  tests/test_risk_contract.py -q   → 131 passed
python -m pytest tests/test_shadow_routing.py -q   → 47 passed
分块全量 non-GUI                     → 见 §12（零回归）
```

## 12. 全量 non-GUI 回归

```
python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py \
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_e_e2e.py
  → 1537 passed, 1 skipped, 29 deselected（64.45s）
```

= 既有基线 **1490 passed / 1 skipped / 29 deselected**（同一命令 `--ignore
tests/test_shadow_routing.py` 复跑验证）+ 本任务 **47 项新增** = 1537，**零下降**（精确
对账）；RW-029 环境 flake 按项目惯例分块隔离；3 个真实桌面 Phase E e2e 文件按项目惯例
排除（与 A1 报告同一 canonical 命令形态）。

## 13. A3-A6 Anti-Pullback（Requirement 19）

本任务**未实现**：Hermes free automatic routing、实际模型切换、WorkBuddy economic live
routing、automatic fallback、Cost Gate UX 变更、observation/calibration loop、动态
registry 健康管理、健康轮询、后台监控、provider probe、自动隔离、动态降级、live benchmark
loop。CAP-003（实际 Model Routing）保持 **NOT IMPLEMENTED**（backlog 已注明 A2 shadow
started 不改变该状态）。

## 14. Git 状态（Requirement 22）

- 基线：main @ `8a9054f514e8244db23e972373bbecf36ebdb343`（= origin/main，ahead/behind
  0/0，tracked working tree CLEAN）——A1 = CLOSED / COMPLETE / **SYNCED** 验证成立。
- 本任务 commit：本地 main 新增（见 structured result `commit` 字段）；**未 push**
  （review 后同步，与 A1/A0 惯例一致）。
- PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`scripts/start_bridge_hidden.vbs`、
  `AAF_TASK004_PROCESS_CHECK.txt`）未删除、未 clean。
- 无 reset / rebase / amend / force push。

## 15. 验证状态 / 已知限制

- WorkBuddy 独立验证 + Codex 审查由 route 阶段（hermes → workbuddy → codex）执行并
  记录；若发现 blocking 按惯例开 FIX。
- 已知限制（如实）：影子选择器不产生任何真实模型调用；无运行期观测（A2 后续 slice）；
  基线 registry 无 verified candidate facts（真实模型 tier/qualification 仍 UNKNOWN）。

## 16. Next Smallest A2 Slice

按最小增量排序的候选（Planner 决定，本任务不启动）：

1. **运行期影子观测写入**：在 runner 的只读观察点计算 shadow decision 并落盘
   `shadow_decision.json`（零执行影响；需先定义观察触发点与 artifact 契约）。
2. **实况 qualification 观测**：为 registry 提供基于真实运行证据的 qualification 填充
   （只读 probe，证据化，仍不激活路由）。
3. **候选 tier 赋值**：对真实 Hermes FREE/本地模型做有证据的 capability 观测/校准后再
   赋值（当前保持 UNKNOWN，不发明）。
