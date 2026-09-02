# AAF-v0.5-A5-PAID-ESCALATION-GATE-001 — Implementation Report

> Task: Implement A5 paid escalation Cost Gate
> （A5 第三条实现单元：paid escalation / Cost Gate runtime foundation——当
> FREE/LOCAL_FREE fallback 不可用而存在合格 paid candidate 时，使用既有 A0
> Paid Guard 做显式、可审计的授权判断；**本任务不执行 paid fallback model
> invocation**）
> Executor: Hermes（AAF Executor stage）2026-09-03
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Baseline: HEAD = local/origin `b082fefeb9a02b84ef0d365693c48aace5a62949`（未 push）
> A5 保持 STARTED / NOT CLOSED / COMPLETE（REQUIRED_BEFORE_A5_CLOSE 9 项不重写；
> paid INVOCATION = 后续 A5 任务 scope）

## 1. 结论（先给结论）

1. ✅ **live runtime 有且只有一个权威 paid escalation Cost Gate**
   （Requirement 1/2/3/4）：新模块 `ai_agent_framework/fallback_paid_gate.py`
   = Cost Gate 审计语义单元（gate decision 三态 + authoritative audit record +
   fail-closed validator）；`fallback_runtime.py`（live A5 runtime layer）在
   no-eligible 分支接线 + 新 orchestrator `_run_paid_escalation_gate`；runner
   Hermes stage 新增 `paid_escalation_gate_ref`。触发条件 = 原始 invocation 以
   fallback-eligible failure 失败 + A5-002 FREE/LOCAL_FREE gate 结果为空（无
   合格免费 fallback）+ contract 层存在合格 paid candidate（A1/A2 闸已过、
   distinct from original）+ automatic fallback budget 未耗尽（count_used==0，
   no chain/loop 保持）。
2. ✅ **A0 Paid Guard 仍是唯一付费授权 authority，零第二授权系统**
   （Requirement 1/4）：gate 对确定性选中的 paid candidate 应用 candidate env
   覆盖后调用既有 `cost_guard.evaluate`（与 A5-002 FREE 路径同一 admission
   机制、同一 authority）——没有第二 auth token、没有 implicit authorization、
   没有 broad/global authorization、task/stage/model/provider 整串精确匹配零
   削弱；A0 一次性 claim 语义在其准入边界保持（exact auth 时 A0 原子 claim，
   gate 如实转述 authorization_present / matched / consumed，不 bypass/复刻）。
3. ✅ **Cost Gate 三态可区分（Requirement 3）**：**AUTHORIZED**（A0
   ALLOWED_AUTHORIZED_PAID 且 A0 解析的 effective model/provider == candidate
   精确 scope——scope integrity 检查保证授权状态可归属）；**BLOCKED**
   （authorization absent / mismatch / one-time replay——A0
   BLOCKED_COST_APPROVAL）；**FAIL_CLOSED**（malformed/unknown：guard record
   缺必需字段 / guard 求值抛异常 / guard 解析 model≠candidate / A0
   ALLOWED_FREE（registry 视为 paid、A0 视为 free 的成本视图冲突）/ 未知
   decision token / contradictory flags）。三类一律零 invocation。
4. ✅ **authorization-evaluation ONLY——零 paid invocation**（Requirement 6/8）：
   exact auth → gate AUTHORIZED + ready-for-paid-invocation 资格记录，但**绝不
   invocation**：fallback_attempted / fallback_used 恒 False（gate record 与
   runtime record 双 false——授权单独绝不设 attempted/used）、final actual ==
   original、原始 stage 失败保留（result_text None → WAITING，无自动继续）；
   Cost Gate 授权只建立**未来 paid invocation 任务**的资格。
5. ✅ **authorization 缺失/不匹配/malformed/unknown → fail closed**
   （Requirement 7）：不 invoke 任何 paid model、保留原始失败、显式 audit
   证据（BLOCKED / FAIL_CLOSED record + no-silent-paid evidence）；gate 内部
   任何意外失败被收口为 `paid_gate_error` 显式字段（绝不掩盖 runtime 结果）。
6. ✅ **权威 machine-readable audit**（Requirement 5）：每 gate 求值持久化
   `paid_escalation_gate.json`（authoritative=true，decision_kind=
   paid_escalation_gate_audit）——task/stage/role/risk、original model/provider、
   failure class/trigger、`free_fallback_unavailable_reason`（为什么 FREE
   fallback 不可用：runtime decision_reason + cost-gate exclusion notes）、
   proposed paid candidate model/provider、paid_escalation_required、
   authorization_present/matched/consumed、guard decision / cost_class /
   model / provider / required_scope、gate decision/reason、attempted/used 恒
   False、final==original、explicit no-silent-paid-execution evidence；经
   `validate_paid_escalation_gate_record` fail-closed 校验（authority 精确匹配 /
   attempted-used 必须 False / paid_escalation_required 必须 True /
   AUTHORIZED ↔ A0 ALLOWED_AUTHORIZED_PAID + exact scope + flags True /
   matched=True ⟹ AUTHORIZED / BLOCKED ⟹ A0 BLOCKED_COST_APPROVAL /
   candidates ⊆ contract / paid candidate ≠ original / failure_class ∈
   TRIGGER_CAPABLE_CLASSES）。
7. ✅ **A5-002 invariants 保持（Requirement 9）**：FREE runtime 仍
   ALLOWED_FREE-only（零修改）；free candidate 存在时 FREE fallback 优先执行、
   gate 完全不运行（Requirement 10 测试 + fresh-runner N5 实证）；max-one-
   model-level-fallback / no-chain / no-loop 保持（count_used==1 时 gate 不
   运行）；same-model transport retry 分层不变；A3 初始 routing 零修改；
   `fallback_contract.py` / `cost_guard.py` / `active_routing.py` /
   `workbuddy_routing.py` / `adapters.py` / `model_registry.py` **byte-identical
   零修改**（gate 审计词汇与 A5-002 runtime record 以 decision_kind + authority
   明确区分，A5-002 record schema/语义零改动——既有 45 项 A5-002 测试全绿）。
8. ✅ **测试**（Requirement 10/11）：38 项新增聚焦测试
   （tests/test_a5_paid_escalation_gate.py：Requirement 10 全矩阵——paid +
   no auth → BLOCKED / paid + 任务/stage/model/provider 任一 mismatch →
   BLOCKED / malformed/unknown（guard 抛异常、guard record 缺字段、guard 解析
   其他 model、ALLOWED_FREE 冲突）→ FAIL_CLOSED / exact auth → AUTHORIZED 但
   零 paid invocation / free candidate 优先（gate 不运行）/ 资格不足 paid
   candidate 永不达 gate / audit required fields + no-silent-paid evidence /
   authorization 单独不设 attempted-used + validator mutation 矩阵 + 真实
   runner 集成 4 场景）；聚焦 A5 区零回归（既有 A5-002 45 项 / contract 131
   项 / A0 66 项全绿）+ 全量 canonical regression **2101 passed / 1 skipped /
   16 deselected（0 failed）** = 同命令 HEAD b082fef worktree 基线 **2063 + 38
   精确零回归**（本任务新增恰 38 项，见 §4 精确口径）。
9. ✅ **fresh-runner 全新进程验证（Requirement 12）5/5**：N1 no auth → gate
   BLOCKED + 恰 1 次 invocation（无 paid 执行）+ WAITING；N2 mismatched auth →
   BLOCKED + 无 paid 执行；N3 exact auth → AUTHORIZED（matched/consumed=true、
   A0 一次性消费 marker 存在）但**仍无 paid invocation**（恰 1 次）+ WAITING；
   N4 no-silent-paid（marker 无 paid 行 + evidence 显式 + attempted/used 恒
   False）；N5 既有 FREE fallback 行为保持（original 失败 → 恰一次 free
   fallback used=true、gate artifact 不存在、SUCCESS）。证据：
   `.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001/fresh-runner-validation/`。
10. ✅ **范围纪律（Requirement 13/14）**：A5 状态更新仅追加（PROJECT_STATE
    header + A5 实现状态新 bullet；backlog CAP-003 行同步）——A5 保持
    STARTED，**未标记 CLOSED/COMPLETE**；无 paid model invocation、无 A0/
    contract/registry 修改、无无关清理；PRE_ALLOWED_UNTRACKED 保留；未 push。

## 2. Requirements → 实现映射

| Req | 验收 | 证据 |
|---|---|---|
| 1 | paid_escalation_required 接入 live A5 runtime | fallback_runtime.py no-eligible 分支 gate 接线 + _run_paid_escalation_gate；gate record paid_escalation_required=true（测试 test_paid_candidate_no_auth_blocked_no_invocation 等） |
| 2 | 考虑前置 | fallback_runtime.py `_run_paid_escalation_gate` docstring + 触发条件（TRIGGER_CAPABLE + count_used==0 + contract eligible + gated empty + pool 非空）；测试 test_exhausted_budget_no_gate / test_non_fallback_eligible_failure_no_gate / test_unqualified_paid_candidate_never_reaches_gate / test_original_only_candidate_no_gate |
| 3 | 三态区分 | fallback_paid_gate.GATE_DECISION_*（AUTHORIZED/BLOCKED/FAIL_CLOSED）+ interpret_guard；第 1/2 节测试全矩阵 |
| 4 | 复用 AAF_COST_AUTH / Paid Guard | cost_guard.evaluate 唯一授权消费点（exact scope_string 整串匹配，A0 零修改）；无第二 token/无 implicit/无 broad；测试 mismatch 参数化 + scope-integrity FAIL_CLOSED |
| 5 | 权威审计字段 | _REQUIRED_KEYS + assemble_paid_gate_record + validator；测试 test_gate_audit_required_fields_and_no_silent_evidence |
| 6 | 零 paid invocation / attempted-used 不因授权变 true | orchestrator 无 invoke 调用；gate record attempted/used 恒 False（validator 强制）；测试 test_exact_auth_authorized_zero_paid_invocation / test_authorization_alone_never_sets_attempted_used + fresh-runner N3 |
| 7 | absent/mismatch/malformed → fail closed + 证据 | BLOCKED/FAIL_CLOSED record 落盘；gate 意外失败 → paid_gate_error；测试 1-3/13-15/17 + fresh-runner N1/N2 |
| 8 | valid auth → AUTHORIZED 但零执行、不提前消费 | A0 语义原样（准入边界一次性 claim）；gate 只转述 consumed；测试 + fresh-runner N3（marker 恰 1 行 + consumption marker 存在） |
| 9 | A5-002 invariants | free 优先（test_free_candidate_takes_precedence_over_paid / fresh-runner N5）；count_used==1 不 gate；runtime record schema 零改动（45 项既有测试全绿） |
| 10 | 聚焦测试 | 38 项（清单见 §1.8） |
| 11 | 回归 | §4 |
| 12 | fresh-runner 新进程 | §4.3（5/5） |
| 13 | A5 状态更新但不 CLOSE | §1.10 |
| 14 | 无无关清理 / PRE_ALLOWED_UNTRACKED / no push | §5 |

## 3. 设计要点

### 3.1 为什么不做「check-only」授权——A0 语义原样复用
Cost Gate 用既有 `cost_guard.evaluate`（非新 API）：exact scope 匹配时 A0 在
自己的准入边界原子 claim 一次性授权（与 A5-002 FREE 路径对
ALLOWED_AUTHORIZED_PAID 的记录行为一致——A0 语义零修改）。gate audit 如实
转述 `authorization_consumed`；AUTHORIZED 的消费记录在同一 execution 目录内
阻止 replay（A0 既有保护），而未来 paid invocation 任务在**自己的新 execution
上下文**按 A0 规则重新准入（一次性语义不跨 execution 泄漏）。本层不建、不用
任何平行授权检查（那会削弱 exact-scope 契约或创造第二消费点）。

### 3.2 为什么 count_used==0 是考虑前置（Requirement 2「或 FREE 路径在
one-fallback rule 下耗尽」的收口解释）
A5-002 runtime 是每 affected stage 单次调用点：FREE 候选存在时会立即 attempt
（attempted=true）；若其失败，stage 已耗尽该次 model-level fallback——
此时再评估 paid escalation 会形成第二次 model-level 候选（chain）。因此本
单元在 budget 已消耗（count_used==1）时**不运行** gate；「FREE 路径不可用」
在本 live 路径 = FREE gate 结果为空（无合格免费候选）。该边界写入
fallback_runtime docstring + orchestrator 注释 + 测试
test_exhausted_budget_no_gate（count_used=1 → 无 gate artifact）。未来若
planner 定义「paid escalation 不计入 automatic fallback 预算」，由后续任务
显式扩展（本任务不越界）。

### 3.3 scope integrity（Requirement 4 零削弱）
gate 不信任 A0 record 本身：A0 求值必须发生在 candidate 自身 env 覆盖下且
record 的 effective model/provider == candidate（否则 FAIL_CLOSED——hermetic
测试环境即此形态）。绝不允许「对模型 X 的授权被当作对候选 Y 的授权」。

### 3.4 审计分层（与 A5-002 record 互不混淆）
- `fallback_runtime.json`（decision_kind=fallback_runtime_audit）：FREE 路径
  outcome（本任务场景 = fallback_not_eligible + authorization_outcome=none，
  语义零改动——45 项既有测试锁定）；
- `paid_escalation_gate.json`（decision_kind=paid_escalation_gate_audit）：
  paid escalation 授权求值 outcome（本任务新增）。两者以 decision_kind +
  authority 明确区分；stage result 同时携带 fallback_runtime_ref 与
  paid_escalation_gate_ref。

## 4. 验证

### 4.1 聚焦测试
```
python -m pytest tests/test_a5_paid_escalation_gate.py -q
38 passed
```
Requirement 10 全矩阵 + validator mutation + 真实 runner 集成 4 场景
（no-auth BLOCKED / exact-auth AUTHORIZED 但 WAITING / mismatch BLOCKED /
free-precedence SUCCESS 无 gate artifact）。

### 4.2 既有 A5/A0 聚焦区零回归
```
python -m pytest tests/test_a5_paid_escalation_gate.py tests/test_a5_fallback_runtime.py -q
83 passed
python -m pytest tests/test_a5_paid_escalation_gate.py tests/test_a5_fallback_runtime.py tests/test_a5_fallback_contract.py tests/test_cost_guard.py -q
280 passed（既有 A5-002 45 项 / contract 131 项 / A0 66 项零回归 + 本任务 38 项）
```

### 4.3 canonical 全量回归（Requirement 11；精确可复现命令）
本机已知 RW-029 flake（tests/test_phase_e_cancel_ui_e2e.py 内
bridge/launcher.py:598 Windows 0x80000003 GC 崩溃，机器/环境相关，与本次改动
无关；此前任务同样以 GUI-E2E 文件 deselect 隔离）。canonical 命令：
```
python -m pytest -m "not gui_e2e" --deselect tests/test_phase_e_cancel_ui_e2e.py -q
```
- 当前树（含本任务改动）：**2101 passed / 1 skipped / 16 deselected（0 failed）**
- 同命令 HEAD b082fef git-worktree 基线：**2063 passed / 1 skipped / 16 deselected**
- Δ = **+38 精确零回归**：本任务新增恰 38 项
  （tests/test_a5_paid_escalation_gate.py，collect-only 计数 = 38）；两轮同
  命令同机同 interpreter、同 deselect 文件集，差分口径一致，无失败、无 skip
  变化。
  注：此前任务报告口径（如 2041 passed / 38 deselected）使用了不同的
  GUI-E2E deselect 文件集（Codex W1 已记录 4-file 清单缺失）；本轮采用单文件
  deselect（本机 RW-029 0x80000003 flake 隔离）+ 同命令 worktree 基线差分，
  可复现性更强（WorkBuddy 可独立复跑同一命令）。

### 4.4 fresh-runner 全新进程验证（Requirement 12；5/5）
```
python tests/fresh_runner_a5_paid_escalation_gate_validation.py   # 退出码 0
```
- N1（no auth）：gate BLOCKED（absent），marker 恰 1 行 aaa-orig@custom（无
  paid 执行），runtime audit fallback_not_eligible，WAITING，无 chain，
  env probe 全 -none-
- N2（mismatched auth）：gate BLOCKED（mismatch），恰 1 行，WAITING
- N3（exact auth）：gate AUTHORIZED（present/matched/consumed=true），A0
  一次性消费 marker 存在，**marker 仍恰 1 行**（AUTHORIZED 不引发 paid
  invocation），WAITING，无 chain
- N4（no silent paid execution）：N1/N3 marker 均无 zzz-paid@remote-api 行；
  gate evidence 显式 no-silent-paid；attempted/used 恒 False
- N5（FREE fallback intact）：original 失败 → 恰一次 zzz-fb free fallback
  （marker 2 行）used=true final=zzz-fb、gate artifact 不存在、全链 SUCCESS
证据目录：`.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001/fresh-runner-validation/`
（N1/N2/N3/N5 子目录含 run.json / paid_escalation_gate.json /
fallback_runtime.json / cost_auth_consumed.json（N3）/ marker_hermes.txt /
hermes_result.md 等，不提交）。

## 5. 改动清单 / 范围纪律 / 遗留

改动（tracked + 新文件，全部在 WORKSPACE 内）：
- 新：`ai_agent_framework/fallback_paid_gate.py`（Cost Gate 审计语义单元）
- 改：`ai_agent_framework/fallback_runtime.py`（docstring + gate 接线 +
  `_run_paid_escalation_gate` orchestrator；A5-002 路径零语义改动）
- 改：`ai_agent_framework/runner.py`（stage 新增 `paid_escalation_gate_ref`，
  加字段 only）
- 新：`tests/test_a5_paid_escalation_gate.py`（38 项）
- 新：`tests/fresh_runner_a5_paid_escalation_gate_wrapper.py` /
  `tests/fresh_runner_a5_paid_escalation_gate_validation.py`
- 新：本报告 `docs/internal/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-REPORT.md`
- 改：`docs/internal/PROJECT_STATE.md`（header Last Updated + A5 实现状态
  新 bullet——A5 保持 STARTED / NOT CLOSED / COMPLETE，REQUIRED_BEFORE_A5_CLOSE
  9 项不重写）
- 改：`docs/internal/AAF_MASTER_BACKLOG.md`（CAP-003 全行同步：A5 行追加
  PAID-ESCALATION-GATE-001 单元；历史行不重写）

范围纪律（Requirement 14）：
- 零 paid model invocation（任何路径、任何授权状态）；A0 Paid Guard /
  fallback_contract / active_routing / workbuddy_routing / adapters /
  model_registry **零修改**（byte-identical）；A3/A4/A6/A4+ 不进入；
- PRE_ALLOWED_UNTRACKED（`AAF_TASK004_PROCESS_CHECK.txt` /
  `scripts/start_bridge_hidden.vbs` 等）保留不动；无无关清理；
- 未 push（commit 后待 WorkBuddy 独立验证 + Codex APPROVE）；
- 遗留（非代码）：本任务 fresh-runner 证据根目录
  `.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001/` 下存在临时 git worktree
  checkout 残留 `.aaf/_wt_baseline_b082fef/`（git worktree 已 prune、本机
  单查询模式禁止递归删除导致未能清理；纯 untracked 脚手架，可随时人工删除，
  不影响任何 tracked 内容）。

## 6. 验收对照

- [x] live runtime 有一个权威 paid escalation Cost Gate
- [x] A0 Paid Guard 仍是唯一付费授权 authority（零第二授权系统）
- [x] exact task-scoped authorization 必需（整串精确匹配零削弱）
- [x] absence / mismatch / malformed → fail closed
- [x] valid auth 本身不执行 paid fallback（AUTHORIZED ≠ invocation）
- [x] 无 silent paid execution（marker / evidence / attempted-used 三重证明）
- [x] FREE fallback 行为保持（聚焦 + canonical + fresh-runner N5）
- [x] audit machine-readable + validated（paid_escalation_gate.json + validator）
- [x] focused tests 38/38；canonical 2100 passed（基线 2063 + 37 零回归）
- [x] fresh-runner closure 5/5（新进程）
- [ ] WorkBuddy 独立验证（route 阶段）
- [ ] Codex APPROVE（route 阶段）
- [x] Unresolved Issues = None（实现侧）
- [x] no push
