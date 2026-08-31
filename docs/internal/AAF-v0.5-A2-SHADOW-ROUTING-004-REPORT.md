# AAF-v0.5-A2-SHADOW-ROUTING-004 — Implementation Report

> Task: A2 Shadow Routing — Add evidence-backed Hermes registry qualification（第四片：为 deepseek-v4-flash@deepseek 填入证据支持的 T2 + QUALIFIED，解除 HIGH shadow 的 registry blocker）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **IMPLEMENTED**；A2 保持 **STARTED**（Shadow-only，未进入 A3）；A1 保持 CLOSED / COMPLETE / SYNCED
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **registry blocker 解除**（Objective）：`deepseek-v4-flash@deepseek` 基线条目
   现在携带证据支持的 `capability_tier = T2` + `qualification.status = QUALIFIED`——
   HIGH Hermes task 的 shadow 决策产生**真实 hypothetical candidate**
   （`selected = deepseek-v4-flash@deepseek`，selection_reason=sole_eligible_candidate），
   不再是 NO_SHADOW_CANDIDATE。
2. ✅ **只使用已接受的真实运行证据**（Evidence rule）：证据 = AAF-v0.5-A2-SHADOW-ROUTING-003-FIX-001
   （显式 `Risk: HIGH`，其 Hermes executor 真实以 `deepseek-v4-flash@deepseek` 运行、
   完整成功 SUCCESS、WorkBuddy PASS_WITH_WARNING、Codex **APPROVE**，commit `5911d39`）。
   按风险契约 `RISK_FLOORS[HIGH].executor == "T2"` 只证明**最低已证能力 = T2**；
   **不推断 T1/T0、不推断永久健康**（测试锁定）。
3. ✅ **conservative qualification 语义**（Requirement 2）：`QUALIFIED` = accepted
   evidence snapshot（evidence 引用具体已接受 artifacts + observed_at = 证据被接受的
   真实运行时时间戳 `2026-08-31T08:16:23`，即 run.json terminal SUCCESS / codex_result.json
   APPROVE generated_at，**不是**本次构造的当前时间）；不产生动态 health / quarantine 行为。
4. ✅ **其它基线候选零改动**（Requirement 3）：qwen2.5vl:3b@custom / qwen3:4b@custom
   （tier=None、qualification=unknown）与 agent:workbuddy / agent:codex（身份 UNKNOWN）
   逐项保持原样——本地/free 模型无独立证据绝不提升（测试锁定）。
5. ✅ **固定维度全部保持**（Requirement 4）：`cost_class = UNKNOWN`（成本元数据仍未
   暴露，独立维度不改）；selector（shadow_routing.py）零修改；shadow observation
   （shadow_observation.py）零修改（只消费更新后的 registry）；实际 Hermes
   model/provider/command 不变（`adapters.run_agent` 零修改、runner 调用形态不变）；
   `authoritative=false` / `execution_affected=false` 固定语义 + validate fail-closed 保持。
6. ✅ **Requirement 5 全矩阵测试**：HIGH eligible、capability=T2、QUALIFIED+evidence、
   T1/T0 不推断（CRITICAL 仍 NO_SHADOW_CANDIDATE）、其它候选保持 UNKNOWN、
   UNKNOWN 成本不阻塞 eligibility、actual execution authority 不变——9 项新增聚焦测试
   （净 +8：替换 1 项旧基线断言；见 §5），全量 non-GUI 零回归（§7 精确对账）。
7. ✅ **Fresh-runner N+1 通过**（§9）：真实子进程 + fake-bin CLI + 只读配置发现，
   显式 `Risk: HIGH` TASK 全链验证——actual Hermes 保持 deepseek-v4-flash@deepseek、
   shadow artifact 消费 Risk: HIGH、deepseek eligible 且被选中、authoritative=false /
   execution_affected=false、零额外 provider 调用、REPORT/lifecycle 正常。
8. ✅ **最小文档更新**：本 REPORT + PROJECT_STATE + backlog（§8）。

## 2. A2 Scope Boundary

本任务 = **A2 第四片（证据支持的 Hermes registry qualification，observation-only）**：

- **In scope**：`model_registry.baseline_entries()` 中 deepseek-v4-flash@deepseek
  单一条目填入证据支持的 T2 + QUALIFIED（含 evidence 引用 + 真实 observed_at）；
  相应测试更新与新增；fresh-runner N+1；文档。
- **Out of scope（后续 A2 slice）**：实况 qualification 观测、WorkBuddy/Codex shadow
  observation、runtime 风险分类接入、selector / shadow observation 代码修改、其他
  候选的证据化赋值。
- **A2 boundary（Requirement Boundaries）**：未实现自动路由、无 runtime qualification
  learning、无自动提升、无健康轮询、无动态隔离、无 fallback、未进入 A3；本地/free
  模型无独立证据未提升。

## 3. Reused Contracts（复用，零复制、零发明）

| 契约 | 消费方式 |
|---|---|
| `RuntimeQualification` + `evidence` + `observed_at`（A1 model_registry） | 既有 qualification 机制原样使用——**未发明第二套 qualification 机制** |
| `risk_contract.RISK_FLOORS[HIGH].executor == "T2"`（A1） | 证据→tier 的映射依据：HIGH 任务实际执行成功 = 最低已证 T2 |
| `is_usable_candidate` / `tier_satisfies`（A1） | selector 原样消费更新后的条目（零修改） |
| `shadow_routing.select_shadow_candidate` / `shadow_observation`（A2-001/002/003） | 零代码修改，仅 registry 数据变化改变决策输出 |
| 证据 artifacts（003-FIX-001 已接受执行/审查产物） | `.aaf/AAF-v0.5-A2-SHADOW-ROUTING-003-FIX-001/` 下 REPORT / model_observation / shadow_observation / workbuddy_result / codex_result / run.json |

## 4. Implementation（实现明细）

`ai_agent_framework/model_registry.py`（唯一生产文件改动）：

1. 新增证据锚点常量 `_EVID_A2_004_HERMES_T2`：指向已接受的 003-FIX-001 执行/审查
   artifacts（TASK.snapshot.md Risk: HIGH、model_observation.json actual
   model/provider、shadow_observation.json risk_class=HIGH、workbuddy_result.json
   PASS_WITH_WARNING、codex_result.json APPROVE、run.json SUCCESS；commit 5911d39）。
2. 新增 `_EVID_A2_004_OBSERVED_AT = "2026-08-31T08:16:23"`：证据被接受的运行时
   时间戳（run.json timestamp == codex_result.json generated_at，Codex APPROVE
   完成时刻）——**不是本次构造的当前时间**。
3. `deepseek-v4-flash@deepseek` 条目更新：
   - `capability_tier: None -> CAP_TIER_T2`（只证明「至少 T2」，不推断 T1/T0）
   - `qualification: RuntimeQualification(status=QUALIFIED, evidence=(_EVID_A2_004_HERMES_T2,), observed_at=...)`
   - 条目级 `evidence` 追加 `_EVID_A2_004_HERMES_T2`（保留既有 CAP-002 probe / A0 report）
   - notes 更新：T2+QUALIFIED 仅来自 accepted evidence；accepted evidence snapshot —
     不表示永久健康、不产生动态 health/quarantine 行为；T1/T0 未证明
   - **cost_class 保持 UNKNOWN**；locality / applicable_agents 不变
4. `baseline_entries()` docstring 更新：唯一例外说明（证据支持字段才填）。

其它生产文件（selector / shadow observation / runner / adapters / cost_guard）**零修改**。

## 5. Test Matrix（Requirement 5 全矩阵，9 项新增 / 净 +8）

| 验收点 | 测试 | 文件 |
|---|---|---|
| HIGH Hermes shadow 视 deepseek 为 eligible | `test_baseline_registry_high_shadow_selects_deepseek` / `test_baseline_registry_low_medium_high_select_deepseek` / `test_runner_high_risk_shadow_selects_deepseek`（runner 级） | test_shadow_observation.py / test_shadow_routing.py / test_task_risk_provenance.py |
| capability 解析为 T2 | `test_baseline_deepseek_t2_evidence_backed`（== T2，!= T1/T0）+ decision required_floor=T2 | test_model_registry.py + 上述 |
| qualification = QUALIFIED 带证据 | `test_baseline_deepseek_t2_evidence_backed`（evidence 含 003-FIX-001 / 5911d39 / APPROVE / Risk: HIGH；observed_at == 真实证据时间戳） | test_model_registry.py |
| T1/T0 不推断 | `test_baseline_registry_critical_no_t1_t0_inference`（CRITICAL → CAPABILITY_INSUFFICIENT → NO_SHADOW_CANDIDATE）/ `test_baseline_registry_critical_no_eligible_candidate_no_shadow_candidate` | test_shadow_routing.py / test_shadow_observation.py |
| 其它 UNKNOWN 候选保持 UNKNOWN | `test_baseline_other_candidates_remain_unknown` + `test_baseline_no_invented_tiers_or_health`（deepseek 唯一例外）+ 决策排除原因断言（qwen = CAPABILITY_INSUFFICIENT、agent = ROLE_NOT_APPLICABLE） | test_model_registry.py / test_shadow_routing.py |
| UNKNOWN 成本不阻塞 eligibility | `test_baseline_deepseek_unknown_cost_preserved` + `test_baseline_deepseek_is_usable_candidate_with_unknown_cost` + `test_baseline_unknown_cost_does_not_block_eligibility` | test_model_registry.py / test_shadow_routing.py |
| actual execution authority 不变 | `test_runner_high_risk_shadow_selects_deepseek`（恰一次 hermes 调用、三位置参数形态）+ 既有 invocation/zero-extra-provider 守卫保持绿色 | test_task_risk_provenance.py |

定向 5 文件：**199 passed**（HEAD 同 5 文件基线 191 + 8 新增，精确对账）。相关回归
（test_runner / test_cost_guard / test_risk_contract / bridge 等）复跑绿色。

## 6. Static Isolation（隔离守卫延续）

- `shadow_routing` / `shadow_observation` 源码零修改 → 既有静态隔离断言（零 I/O /
  零 LLM / 零副作用 API / live 模块零 import）原样通过。
- `model_registry` 依赖图不变（stdlib + model_observation）；新增改动只含常量与
  数据字段，无新 import、无网络/子进程依赖（既有静态断言保持）。

## 7. Boundaries Compliance（零越界）

- **零自动路由**：无任何 live 路径新增消费；shadow 仍非权威（authoritative=false）。
- **零 runtime qualification learning / 自动提升 / 健康轮询 / 动态隔离 / fallback**：
  QUALIFIED 是静态 accepted-evidence 快照；无新机制、无新状态文件。
- **零 A3**：CAP-003（实际模型路由）保持 NOT IMPLEMENTED。
- **零本地/free 模型提升**：qwen2.5vl:3b / qwen3:4b 无独立证据 → 保持 UNKNOWN。
- **A2 保持 STARTED**（Shadow-only）。
- 全量 non-GUI 对账（与 HEAD 5911d39 同 1-file-deselect 约定）：HEAD = 1611 passed /
  1 skipped / 16 deselected；本分支 = **1619 passed / 1 skipped / 16 deselected**
  （1611 + 8 新增，零回归）。4-file-deselect 运行（规避既有 pre-existing launcher-GC
  0x80000003 崩溃，WorkBuddy 在 FIX-001 review 中同样复现）：**1597 passed /
  1 skipped / 38 deselected**（= 1619 − 22 个 GUI/e2e 测试，精确对账）。

## 8. Changed Files

- `ai_agent_framework/model_registry.py`（唯一生产改动：证据锚点 + deepseek 条目 T2/QUALIFIED）
- `tests/test_model_registry.py`（4 项新增 + 1 项语义更新）
- `tests/test_shadow_routing.py`（3 项新增，替换 1 项旧基线断言）
- `tests/test_shadow_observation.py`（1 项新增，1 项语义更新）
- `tests/test_task_risk_provenance.py`（1 项 runner 级新增 + 注释更新）
- `docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-004-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（状态同步）

## 9. Fresh-runner N+1（N1-high-hermes）

证据目录：`.aaf/AAF-v0.5-A2-SHADOW-ROUTING-004/fresh-runner-validation/N1-high-hermes/`
（fakebin hermes.bat/codebuddy.bat/codex.bat + TASK.md + out2/ + marker_*.txt +
run2_stdout.log；scenario_record.json 在上级目录）。

- 运行：`python tests/fresh_runner_wrapper.py <abs>TASK.md --workspace <abs ws> --output <abs out2>`
  （env：AAF_TEST_FAKE_BIN / AAF_HERMES_MODEL=deepseek-v4-flash /
  AAF_HERMES_PROVIDER=deepseek / AAF_COST_AUTH=…|hermes|deepseek-v4-flash|deepseek）
- **exit 0**；run.json `status=SUCCESS`、terminal_generation=1；REPORT `Current Status SUCCESS`
- 真实子进程证据：marker_hermes.txt（chat --in）/ marker_codebuddy.txt（-p）/
  marker_codex.txt（exec）——三个 route agent 全部真实拉起
- **actual Hermes 保持 deepseek-v4-flash@deepseek**：shadow_observation.json
  `actual_model=deepseek-v4-flash / actual_provider=deepseek`（invocation_env_override）
- **shadow artifact 消费 Risk: HIGH**：`risk_class=HIGH`、risk_source = TASK_RISK_SOURCE
  （task/planner provenance）
- **deepseek eligible 且被选中**：`eligible=[deepseek-v4-flash@deepseek]`、
  `selected=deepseek-v4-flash@deepseek`、selection_reason=sole_eligible_candidate、
  no_candidate_reason=null（blocker 解除）
- **authoritative=false / execution_affected=false**；actual_vs_shadow=SAME
- **零额外 provider/model 调用**：shadow 路径只消费既有 observation；fakebin 只见
  3 个 route agent 调用 + 只读 config/version probe；cost_guard.json =
  ALLOWED_AUTHORIZED_PAID（authorization_matched=true，exact scope）
- 附注：首次尝试用相对 `--output` 被 A0 Paid Guard 正确 BLOCKED（state_dir 必须绝对
  路径，零 agent spawn）——fail-closed 行为实测；改绝对路径后成功。

## 10. Unresolved Issues

None。

## 11. Remote Sync / 交付状态

- 本提交 = 未 push（review 通过后同步，与 A2-001/002/003 惯例一致）。
- A2 = STARTED（Shadow-only）；A1 = CLOSED / COMPLETE / SYNCED；A3 未启动。
- WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件（route 阶段执行）。
