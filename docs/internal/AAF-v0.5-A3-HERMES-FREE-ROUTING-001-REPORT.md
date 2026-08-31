# AAF-v0.5-A3-HERMES-FREE-ROUTING-001 — Implementation Report

> Task: Activate LOW-risk Hermes free routing（A3 最小 active-routing slice ——
> 仅当 Hermes executor task 显式声明 Risk: LOW 且现有 selector 选出已 QUALIFIED 的
> LOCAL_FREE/FREE candidate 时，该 shadow decision 升级为真实 Hermes model/provider 选择）
> Executor: Hermes（AAF Executor stage）2026-09-01
> Status: **IMPLEMENTED（A3 = STARTED，未标 COMPLETE）**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **LOW-risk Hermes FREE active routing 首次真实生效**（Objective / Acceptance）：
   新模块 `ai_agent_framework/active_routing.py` 是 authoritative routing decision 层，
   **复用现有 A2 selector（shadow_routing.select_shadow_candidate）+ A1 baseline
   registry + risk_contract 词汇，不创建第二套路由判断**（Requirement 1）。仅当
   Hermes executor task 显式 `Risk: LOW` + selector 返回 eligible candidate +
   selected 候选 cost_class ∈ FREE_OF_COST_CLASSES + qualification=QUALIFIED 时
   `routing_applied=true`（Requirement 2/3）：runner 在 Paid Guard 求值与真实
   invocation 之前设置 `AAF_HERMES_MODEL=qwen3:4b` / `AAF_HERMES_PROVIDER=custom` /
   `AAF_HERMES_BASE_URL=http://127.0.0.1:11434/v1` 覆盖，`adapters.run_agent` 透传
   `-m qwen3:4b --provider custom`——**qwen3 被实际调用，而非仅 shadow 推荐**。
2. ✅ **非 LOW / missing Risk 行为不变**（Requirement 4）：Risk 缺失 →
   `RISK_UNAVAILABLE`；MEDIUM/HIGH/CRITICAL → `RISK_NOT_LOW`；selector 无候选 →
   `NO_SHADOW_CANDIDATE`；候选非 FREE → `SELECTED_NOT_FREE`——全部保持 configured
   Hermes model/provider（deepseek-v4-flash@deepseek），测试 + N+1 control case 锁定。
3. ✅ **无 silent fallback**（Requirement 5）：`fallback_attempted` 恒为 false
   （fixed semantic + validate fail-closed）；routing 后 local invocation 失败 →
   如实 FRAMEWORK_ERROR → 链中断 WAITING，run_agent 只调用一次，绝不自动改用
   deepseek 或其他模型（runner 级测试断言）。
4. ✅ **active-routing decision 可审计**（Requirement 6）：`active_routing.json`
   记录 risk + provenance（TASK_RISK_SOURCE）/ considered / eligible / selected /
   routing_applied / routed + configured model+provider / reason /
   fallback_attempted=false；stage result 携带 `active_routing_ref`。
5. ✅ **shadow 与 active 明确区分**（Requirement 7）：A2 `shadow_observation.json`
   保持 authoritative=false / execution_affected=false（hypothetical）；A3
   `active_routing.json` 为 authoritative=true（真实决策），stage result 双 ref 并存。
6. ✅ **Paid Guard 未被绕过**（Requirement 8）：routed LOCAL_FREE 经**既有**
   `classify_cost` loopback 判定（registry evidence-backed base_url →
   127.0.0.1 loopback）→ `ALLOWED_FREE`（零授权、零 claim）；非免费路径继续遵循
   A0 规则（N+1 N2 control：deepseek 仍需精确 AAF_COST_AUTH）；fake-local URL
   对抗测试证明 AAF_HERMES_BASE_URL 不是 FREE 后门。
7. ✅ **范围零扩张**（Requirement 9）：未实现 WorkBuddy/Codex routing、
   MEDIUM/HIGH 自动模型选择、automatic fallback、health polling / quarantine、
   automatic qualification promotion、A4-A6。
8. ✅ **测试 + 回归 + fresh-runner N+1 全过**（Requirement 10 / Fresh Runner）：
   31 项新增聚焦测试（tests/test_active_routing.py）+ 全量 non-GUI 零回归
   （stash 反证：HEAD 基线同命令 1595 passed / 1 skipped；本分支 = 1595 既有 +
   31 新增 = **1626 全过**，精确对账）+ fresh-runner N+1 通过（N1 LOW 真实路由到
   qwen3:4b@custom / N2 HIGH control 保持 deepseek，见 §6）。
9. ✅ **A3 = STARTED，未标 COMPLETE**（Acceptance）：正式 COMPLETE 判定留待
   WorkBuddy 独立验证 + Codex APPROVE + Planner。

## 2. Scope Boundary

- **In scope**：A3 最小 active-routing slice（Hermes-only、LOW-only、FREE-only）；
  新模块 active_routing.py + runner Hermes stage 集成 + cost_guard 端点事实支持
  + model_registry base_url 字段；focused/regression tests；fresh-runner N+1；文档。
- **Out of scope（显式 anti-pullback，Requirement 9）**：WorkBuddy/Codex routing；
  MEDIUM/HIGH 自动模型选择；automatic fallback；health polling / quarantine；
  automatic qualification promotion；A4-A6。A3 后续范围全部未实现。

## 3. 设计

### 3.1 复用（Requirement 1：不创建第二套路由判断）

- 候选筛选 = 现有 `shadow_routing.select_shadow_candidate`（A2-001 引擎原样调用）；
  同一 selector 同时被 A2 shadow observation 与 A3 active routing 消费。
- Risk 词汇 = `risk_contract.RISK_CLASSES`（唯一 authority；TASK 顶层 `Risk` 字段
  由既有 task_validation 校验，runner 从 immutable TASK.snapshot.md 解析）。
- Registry = `model_registry.baseline_registry()`（A1 有证据基线）。
- Paid Guard = A0 `cost_guard` 零逻辑改动（仅新增 AAF_HERMES_BASE_URL 显式端点
  事实读取；分类逻辑 classify_cost 原样）。

### 3.2 Activation gates（Requirement 2/4）

| Gate | 不满足时行为 |
|---|---|
| agent == "hermes" | AGENT_NOT_HERMES → 不路由 |
| role == "executor" | ROLE_NOT_EXECUTOR → 不路由 |
| 显式 Risk == LOW | None → RISK_UNAVAILABLE；MEDIUM/HIGH/CRITICAL → RISK_NOT_LOW |
| selector selected 非 None | NO_SHADOW_CANDIDATE → 不路由 |
| selected cost_class ∈ FREE_OF_COST_CLASSES | SELECTED_NOT_FREE → 不路由 |
| selected qualification == QUALIFIED | SELECTED_NOT_QUALIFIED（防御性双保险）→ 不路由 |

全部满足 → `routing_applied=true`，routed model/provider/base_url 取自 selected
registry entry（qwen3:4b / custom / http://127.0.0.1:11434/v1）。

### 3.3 执行链（runner Hermes stage）

1. 解析 snapshot Risk → `decide_active_route(...)`（复用 selector + gates）。
2. `save_active_routing(output_dir, record)`（审计 artifact；写失败 → fail closed）。
3. `routing_applied` → `apply_routing_env(record)` 设置 env 覆盖
   （保存旧值）。
4. Paid Guard `evaluate`（env 覆盖下 effective model == qwen3:4b@custom →
   LOCAL_FREE → ALLOWED_FREE）→ `run_agent`（透传 `-m qwen3:4b --provider custom`）。
5. model observation / shadow observation（env 覆盖仍在 → shadow 如实记录
   actual=qwen3:4b@custom，actual_vs_shadow=SAME）。
6. 还原 env（绝不泄漏到后续 stage / 调用方）。

### 3.4 No silent fallback（Requirement 5）

本模块不存在 fallback 分支；`fallback_attempted` 恒 false 且 validate fail-closed
（任何 True 都是契约违规）。routing 后 invocation 失败走既有异常语义：
FRAMEWORK_ERROR → 链中断 → WAITING，证据完整保留。

## 4. Changed Files

- `ai_agent_framework/active_routing.py`（**新增**：A3 决策模块——gates / 审计记录 /
  schema 校验 / 原子持久化 / env apply-restore）
- `ai_agent_framework/runner.py`（Hermes stage 集成：决策 + 落盘 + env 覆盖 +
  observation 后还原 + stage result `active_routing_ref`）
- `ai_agent_framework/cost_guard.py`（新增 `AAF_HERMES_BASE_URL` 端点事实读取，
  env-override 路径透传；classify_cost 零改动）
- `ai_agent_framework/model_registry.py`（RegistryEntry 新增 `base_url` 字段 +
  序列化；qwen3:4b@custom 填入 evidence-backed 本地端点）
- `tests/test_active_routing.py`（**新增**：31 项聚焦测试，Req 10 全矩阵）
- `tests/fresh_runner_a3_validation.py`（**新增**：N+1 驱动 N1/N2）
- `docs/internal/AAF-v0.5-A3-HERMES-FREE-ROUTING-001-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（状态同步）

## 5. 测试

- **31 项新增聚焦测试**（tests/test_active_routing.py）：
  - LOW + qwen3 qualified → active route 到 qwen3（基线 + 合成 registry）
  - LOW 但 free 候选不合格（qualification unknown）→ 保持 configured
  - LOW + free 不合格但 deepseek(UNKNOWN) eligible → SELECTED_NOT_FREE
  - LOW + PAID selected → SELECTED_NOT_FREE
  - missing Risk → RISK_UNAVAILABLE
  - MEDIUM/HIGH/CRITICAL（parametrized）→ RISK_NOT_LOW
  - role / agent gate（reviewer / codex → 不路由）
  - 审计字段全齐（Req 6）+ shadow vs active 可审计区分（Req 7）
  - validate fail-closed（routing_applied 无 routed_model / fallback_attempted=True /
    authoritative=False → ValueError）
  - env apply/restore 精确还原（含保留既有值）
  - **Paid Guard invariant**：真实 resolve+classify → routed LOCAL_FREE →
    ALLOWED_FREE 零授权；fake-local URL（localhost.evil.example）→ 仍
    PAID_OR_UNKNOWN → BLOCKED（AAF_HERMES_BASE_URL 不是 FREE 后门）
  - env → argv 透传（apply 后 run_agent args 含 `-m qwen3:4b --provider custom`）
  - runner 集成 5 项：LOW 全链（env 可见 + active_routing.json +
    shadow SAME + 双 ref + SUCCESS）/ invocation 失败零 fallback（单次调用 +
    FRAMEWORK_ERROR + WAITING + 证据保留）/ missing Risk / non-LOW /
    AAF_MODEL_OBSERVATION=0 时 routing 仍生效（执行权威 ≠ telemetry）
- **全量 non-GUI 零回归**：stash 反证——HEAD 基线同命令 = 1595 passed / 1
  skipped；本分支 = 1595 既有 + 31 新增 = **1626 passed / 1 skipped**（精确对账）。
- 定向回归：test_model_registry / test_cost_guard（+fix002/003/005/006）/
  test_shadow_routing / test_shadow_observation / test_runner /
  test_task_risk_provenance / test_adapters / test_risk_contract /
  test_model_observation = **390 passed**。

## 6. Fresh-runner N+1

证据目录：`.aaf/AAF-v0.5-A3-HERMES-FREE-ROUTING-001/fresh-runner-validation/`
（N1-low-routed/ + N2-high-control/ + scenario_record.json；fakebin
hermes.bat/codebuddy.bat/codex.bat + TASK.md + out/ + marker_*；驱动 =
tests/fresh_runner_a3_validation.py，`python tests/fresh_runner_a3_validation.py`
→ failures=0）。

**N1（Risk: LOW）——active routing 真实生效**：
- `active_routing.json`：routing_applied=true、authoritative=true、
  selected=qwen3:4b@custom、routed_model=qwen3:4b、routed_provider=custom、
  fallback_attempted=false、reason=active_route_applied_low_free_qualified
- `cost_guard.json`：decision=ALLOWED_FREE、cost_class=LOCAL_FREE、
  model=qwen3:4b、provider=custom、model_source=env_override、
  cost_metadata evidence = loopback IP 127.0.0.1 → **Paid Guard 零授权放行**
- fake hermes chat **真实子进程** marker：`MODEL=qwen3:4b / PROVIDER=custom /
  BASE_URL=http://127.0.0.1:11434/v1`（routing env 覆盖在 child 内可见；env →
  `-m/--provider` argv 透传由单元测试 test_hermes_override_passed_to_invocation +
  test_routed_env_reaches_invocation_args 覆盖）
- `shadow_observation.json`：authoritative=false / execution_affected=false /
  actual_model=qwen3:4b / actual_vs_shadow=SAME（路由后 actual == selected）
- 零 `cost_auth_consumed.json`（ALLOWED_FREE 不 claim）；无 deepseek invocation
- 全链 SUCCESS（run.json status=SUCCESS）；REPORT/lifecycle 正常

**N2（Risk: HIGH control）——active routing 不生效**：
- `active_routing.json`：routing_applied=false、reason=RISK_NOT_LOW、
  configured_model=deepseek-v4-flash
- `cost_guard.json`：decision=ALLOWED_AUTHORIZED_PAID、model=deepseek-v4-flash、
  provider=deepseek（精确 AAF_COST_AUTH 授权并消费——A0 规则原样）
- fake hermes chat marker：MODEL/PROVIDER/BASE_URL 全空（configured model 原样）
- shadow risk_class=HIGH；全链 SUCCESS

## 7. Unresolved Issues

- None（本任务范围内）。A3 正式 COMPLETE 判定、WorkBuddy 独立验证、Codex 审查为
  route 后续阶段的前置闸门，不属于本 Executor 任务范围。

## 8. 边界与后续

- A3 = **STARTED**（未标 COMPLETE）。
- 未实现（Requirement 9 显式 anti-pullback）：WorkBuddy/Codex routing、
  MEDIUM/HIGH 自动模型选择、automatic fallback、health polling / quarantine、
  automatic qualification promotion、A4-A6。
- 已知观测（如实记录）：model_observation.json 仍记录 config 默认
  （deepseek-v4-flash，model_source=config——只读 discovery artifact）；invocation
  真值在 active_routing.json + cost_guard.json + 子进程 marker（本报告 §6）。
