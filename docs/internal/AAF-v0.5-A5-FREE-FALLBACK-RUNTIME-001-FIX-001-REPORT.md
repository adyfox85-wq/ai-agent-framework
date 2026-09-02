# AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 — Fix Report

> Task: Close FREE fallback admission and audit fail-closed gaps
> （修复 AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001 的两个 Codex blocker：
> ① ALLOWED_AUTHORIZED_PAID 不得进入本 FREE/LOCAL_FREE fallback runtime 的
> 第二模型调用；② fallback 成功后权威 audit 校验/持久化失败时不得把该
> fallback 输出当作成功 stage result）
> Executor: Hermes（AAF Executor stage）2026-09-03
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Baseline: HEAD = local/origin `a0ac326630d68af4dac3b271429d3120cf412b57`（parent = `9216426263aad2a9802933108bb572cecccf62ff`；本任务**新提交、不 amend parent**）

## 1. 结论（先给结论）

1. ✅ **Codex BLOCKING #1 收口——ALLOWED_AUTHORIZED_PAID 不能进入 FREE fallback
   invocation**（TASK Requirement 1/2/3/4）：本 FREE/LOCAL_FREE fallback
   runtime 现在只把 A0 Paid Guard 结果 = `ALLOWED_FREE` 视为可执行准入；
   `ALLOWED_AUTHORIZED_PAID`（权威 Cost/Paid Guard 解析为 paid /
   authorized-paid / unknown-paid 语义）**绝不**发起第二模型 invocation——
   即使 registry 候选最初标为 FREE/LOCAL_FREE、即使 `AAF_COST_AUTH` 存在且
   精确匹配（A0 在 admission 边界按**既有**一次性语义原子 claim 该授权——A0
   Paid Guard 行为零修改：不 bypass、不削弱、不复刻、不建第二套授权系统；
   paid escalation = 后续 A5 任务 scope，本单元只拒绝并 fail closed）。
2. ✅ **Codex BLOCKING #2 收口——authoritative audit closure 是 fallback 结果
   被接受的前提**（TASK Requirement 5/6/7）：fallback invocation 已发生后，若
   权威 audit record 的组装/校验/持久化失败，该 invocation 的输出**不再**被
   接受为成功 stage result——返回 fail-closed 结构
   （attempted=true / used=false / result_text=None → runner 保留原始
   FRAMEWORK_ERROR）+ `audit_closure_error` 显式 surface（stage result 文本
   + stderr，绝不静默丢弃、绝不假装 attempt 未发生）；不发起第三模型、不
   重试另一个 fallback（单次调用点语义保持）。
3. ✅ **语义保持**（Requirement 6/8）：fallback_attempted=true 如实反映第二
   不同模型 invocation 实际发起；audit 未闭合时 fallback_used=false；
   exactly-one / no-chain / no-third-model / same-model transport retry 分离 /
   aux+unknown 排除 / same original 排除 / A3 初始 routing 零修改 / 零 paid
   escalation 实现——全部保持并被 FIX-001 fresh-runner 复证。
4. ✅ **测试**（Requirement 4/7）：`tests/test_a5_fallback_runtime.py` 新增 9 项
   FIX-001 聚焦（ALLOWED_FREE→可准入执行 / ALLOWED_AUTHORIZED_PAID→零
   invocation / blocked+mismatch→零 invocation / AAF_COST_AUTH 不能把本单元
   变成 paid fallback（也不能阻断真实免费 fallback）/ no silent paid /
   validator attempted⟹ALLOWED_FREE 不变量 / audit validation 失败注入 /
   audit persistence 失败注入 / audit 失败 + invocation 失败并存——均证明输出
   不被接受、attempted=true、无第三模型、audit failure 显式 surface），全量
   non-GUI 4-file-deselect **2035 passed / 1 skipped / 38 deselected** =
   HEAD（a0ac326）基线 **2026 + 9 精确零回归**。
5. ✅ **Fresh-runner 全新进程验证**（Requirement 10）：FIX-001 新驱动 **4/4**
   全绿 + parent 驱动（N1–N5）在 corrected code 上复跑 **5/5** 全绿（新 python
   进程 + 真实 runner + 真实 child fake CLIs + env marker / audit 注入证据），
   见 §5。
6. ✅ **状态文档按需更新**（Requirement 11/12）：A5 保持 **STARTED**（NOT
   CLOSED / COMPLETE——REQUIRED_BEFORE_A5_CLOSE 9 项不重写：free→paid
   escalation 路径 / Cost Gate UX 未开始，本 FIX 只修复已交付 runtime 单元的
   两个 contract defects）；PROJECT_STATE header + A5 实现状态 bullet +
   backlog CAP-003 全行同步；A6 / A4+ 边界保持 outside；A0-A4 不重开。
7. ✅ **范围纪律**（Requirement 13）：无无关清理；PRE_ALLOWED_UNTRACKED
   （.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs）
   保留；本任务改动 = fallback_runtime.py（修复单元）+ runner.py（audit
   failure surface）+ 测试 2 文件 + docs 3 文件；no push。

## 2. 修复设计

### 2.1 准入 fail-closed（BLOCKING #1）

Codex 定位：`fallback_runtime.py` 把 `ALLOWED_FREE` 与
`ALLOWED_AUTHORIZED_PAID` 同时视为准入成功 → registry 标 FREE/LOCAL_FREE
但 A0 按实际 endpoint 判定为 paid/unknown 的候选，可在消费 `AAF_COST_AUTH`
后进入第二模型 invocation（未来 registry 变化即可激活的 latent paid fallback
path，违反 Requirement 3/8 与 Acceptance「本任务不实现 paid escalation / only
FREE or LOCAL_FREE」）。

修复（`run_fallback_after_failure` admission 分支重排）：

- A0 Paid Guard 求值结果**只有 `ALLOWED_FREE`** 才进入 invocation 分支（本
  FREE/LOCAL_FREE 单元唯一可执行准入）。
- `ALLOWED_AUTHORIZED_PAID` → 还原 candidate env 覆盖、**不 invocation**；
  审计 record 如实记录 `authorization_outcome=ALLOWED_AUTHORIZED_PAID`（A0
  权威 token 不伪装成 BLOCKED），notes/evidence 显式声明：A0 已在 admission
  边界按既有一次性语义 claim 精确 scope 授权（A0 零修改，本层不
  bypass/削弱/复刻），但本 FREE-only 单元拒绝执行 paid fallback（paid
  escalation = 后续 A5 任务 scope），fail closed、原始失败保留。
- `BLOCKED_COST_APPROVAL` / guard record 异常 / 其他任何非 ALLOWED_FREE
  结果（含 unknown-paid 语义）→ 既有 BLOCKED 路径保持（不 invocation，
  authorization_outcome=BLOCKED + 显式 notes）。
- validator 不变量同步收紧（Requirement 4「no silent paid execution」以
  schema 固化）：
  - `fallback_attempted=true` ⟹ `authorization_outcome == ALLOWED_FREE`
    （attempted + ALLOWED_AUTHORIZED_PAID 现在 ValueError——paid fallback
    执行在 schema 层即被拒绝）；
  - `fallback_eligible=true` 且未 attempt ⟹ authorization_outcome ∈
    {BLOCKED（A0 拒绝）, ALLOWED_AUTHORIZED_PAID（A0 准入为 paid 但本单元
    拒绝执行）}——eligible-未attempt + 其他 auth 值仍 ValueError。
- 复用纪律保持：**零新增判断系统**——cost gate 仍复用 A3
  `ACTIVE_ROUTING_COST_CLASSES`；admission 仍完全由 A0 Paid Guard
  （`cost_guard.evaluate`）求值；cost_guard.py 零修改。

### 2.2 authoritative audit closure fail-closed（BLOCKING #2）

Codex 定位：`_emit()` 捕获 audit 校验/写盘失败并返回 None 后，编排器仍把已
成功的 fallback 输出当 stage result 返回（只令 audit_record/artifact_ref=
None）→ runner 接受无权威审计的 fallback 输出，违反 Requirement 6 与 audit
acceptance。

修复：

- `_emit` 失败详情记录到闭包 `emit_failure`（audit failure 永不静默丢弃）。
- invocation 之后 `_emit` 失败（组装/校验/持久化任一层）→ 返回 fail-closed
  结构：`result_text=None`（runner 保留原始 FRAMEWORK_ERROR——fallback 输出
  绝不被接受）、`attempted=True`（invocation 已实际发生，不假装未发生）、
  `used=False`、`audit_record=None`、`artifact_ref=None`、
  `overlay_saved=overlay_saved`（调用方照常观察后还原 env）、
  `audit_closure_error=<显式失败详情>`。
- runner 集成：`audit_closure_error` 存在时 → stderr 显式打印 + 追加到 stage
  result 文本（`FRAMEWORK_ERROR[a5-fallback audit closure failed]: ...`）——
  attempt 证据持久化到 hermes_result.md，链语义照常 fail closed（WAITING），
  无第三模型、无进一步 fallback retry。
- invocation **之前**的 audit/持久化失败语义保持（不发起第二模型，fail
  closed；返回 None / _no_attempt_result——无 attempt 可记录）。
- 本单元改动只落在 fallback_runtime.py（+ runner surface 层）；
  fallback_contract.py / active_routing.py / workbuddy_routing.py /
  cost_guard.py / adapters.py / model_registry.py 零修改。

### 2.3 语义矩阵（修复后）

| 场景 | guard 结果 | 第二模型 invocation | attempted | used | authorization_outcome |
|---|---|---|---|---|---|
| 真实免费候选 | ALLOWED_FREE | 恰一次 | true | true（audit 闭合后） | ALLOWED_FREE |
| registry FREE 但 A0 解析 paid + 精确授权 | ALLOWED_AUTHORIZED_PAID | **无**（FIX-001） | false | false | ALLOWED_AUTHORIZED_PAID（如实） |
| registry FREE 但无/错授权（unknown-paid） | BLOCKED | 无 | false | false | BLOCKED |
| 候选全 paid/unknown（gate 排除） | —（未到 admission） | 无 | false | false | none |
| fallback 成功但 audit 组装/校验失败 | ALLOWED_FREE | 恰一次 | **true** | **false**（输出不被接受） | ALLOWED_FREE |
| fallback 成功但 audit 写盘失败 | ALLOWED_FREE | 恰一次 | **true** | **false** | ALLOWED_FREE |

## 3. 测试证据（Executor 实测）

- 聚焦：`python -m pytest tests/test_a5_fallback_runtime.py` = **39 passed**
  （既有 30 + FIX-001 新增 9）。
- FIX-001 新增覆盖：
  1. `test_fix001_authorized_paid_never_invokes`——registry FREE 远程候选 +
     精确 AAF_COST_AUTH → guard ALLOWED_AUTHORIZED_PAID → 0 invocation、
     attempted=false、auth 如实记录、A0 claim marker 存在（一次性语义保持）、
     evidence「was NOT invoked / no silent paid fallback」、artifact 校验 +
     reload 复验。
  2. `test_fix001_cost_auth_cannot_convert_free_unit_to_paid`——AAF_COST_AUTH
     存在且精确匹配 + 真实 LOCAL_FREE 候选 → 仍 ALLOWED_FREE 恰一次、
     零授权消费（claim 只发生在 paid 分支）——auth 既不阻断免费也不能转换。
  3. `test_fix001_auth_mismatch_blocked_no_invocation`——错误 scope 授权 →
     BLOCKED → 0 invocation、notes 显式 mismatch（unknown-paid fail closed）。
  4. `test_fix001_validator_rejects_attempted_with_authorized_paid`——
     attempted + ALLOWED_AUTHORIZED_PAID → ValueError；eligible-未attempt +
     NONE → ValueError。
  5. `test_fix001_audit_validation_failure_after_fallback_success`——
     audit 校验失败注入：attempted=true / used=false / result_text=None、
     audit_closure_error 显式、无 artifact、恰一次 invocation、env 还原。
  6. `test_fix001_audit_persistence_failure_after_fallback_success`——
     audit 写盘失败注入：同上（输出不被接受，fail closed）。
  7. `test_fix001_audit_failure_when_fallback_invocation_also_failed`——
     invocation 失败 + audit 失败并存：attempted=true / used=false、audit
     failure 显式 surface（不静默丢弃）。
  8. `test_runner_fix001_authorized_paid_no_fallback_invocation`——真实
     runner 全链：无第二模型、audit auth=ALLOWED_AUTHORIZED_PAID、
     run=WAITING、env 零泄漏。
  9. `test_runner_fix001_audit_persistence_failure_output_not_accepted`——
     真实 runner + 写盘失败注入：hermes 恰 2 次 invocation（attempt 真实）、
     hermes_result.md 以 FRAMEWORK_ERROR 开头且含显式 audit closure 文本、
     无 fallback_runtime.json、run=WAITING、env 已还原。
- 相邻套件：A5 contract + A0 Paid Guard 全系（含 FIX-002/003/005/006）+
  A3 active routing + runner = **383 passed**（14.14s）。
- 全量 non-GUI 4-file-deselect（项目固定回归口径：
  `--deselect tests/test_phase_e_cancel_ui_e2e.py --deselect
  tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py
  --deselect tests/test_phase_f_e2e.py`）：
  **2035 passed / 1 skipped / 38 deselected** in 74.81s = HEAD（a0ac326）
  基线 **2026 + 9 精确零回归**（基线以 git stash 同一 canonical 命令于
  a0ac326 复跑确认：2026 passed / 1 skipped / 38 deselected in 73.11s）。
- 注：裸 `pytest tests/` 会在真实桌面 UI E2E（test_phase_e_cancel_ui_e2e.py）
  崩溃——既有 GUI 测试环境限制（headless），项目固定以 non-GUI 4-file-
  deselect 为回归口径（与 parent REPORT 披露一致）。

## 4. 验收对照（Acceptance）

- ALLOWED_AUTHORIZED_PAID cannot enter FREE fallback invocation ✅（§2.1；
  测试 1/8；fresh F1）
- AAF_COST_AUTH cannot enable paid fallback in this unit ✅（测试 1/2/8；
  fresh F1）
- fallback success without authoritative audit closure is not accepted ✅
  （§2.2；测试 5/6/9；fresh F2）
- audit failure records attempted=true / used=false semantics where
  representable ✅（返回结构 attempted=True/used=False + audit_closure_error；
  测试 5/6/7）
- no third model invocation ✅（测试 5/6/9 恰一次 fallback；fresh F3）
- no fallback chain/loop ✅（fresh F2/F3 codebuddy 未 spawn、WAITING）
- no silent paid fallback ✅（测试 1/2/3/8；fresh F1/F4）
- focused tests pass ✅（39/39）
- canonical regression passes ✅（2035 = 2026 + 9 精确零回归）
- fresh-runner closure passes ✅（FIX-001 4/4 + parent 驱动复跑 5/5）
- WorkBuddy independent verification / Codex APPROVE = route 阶段执行
- Unresolved Issues = None（route 判定）
- no push ✅

## 5. Fresh-runner N+1 验证证据（Requirement 10，全新进程）

每个场景 = 全新 python 进程运行真实 runner
（tests/fresh_runner_a5_free_fallback_fix001_wrapper.py）+ 真实 child fake
CLIs（fakebin/hermes.bat 等），每次 hermes chat invocation 向 marker 追加
`MODEL=<model>@<provider>`（env 覆盖 = actual invocation model）；audit
写盘失败经 wrapper env `AAF_TEST_AUDIT_SAVE_FAIL=1` 注入（test-only wrapper，
生产代码零 hook）。证据根：
`.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001/fresh-runner-validation/`
（F1–F4）与 `.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001/
fresh-runner-parent-regression/`（parent N1–N5 复跑；不覆盖 parent 历史证据）。

- **F1 authorized-paid refused（4/4 断言）**：fb_paid_admission（aaa-orig
  LOCAL_FREE + zzz-free registry-FREE 远程）+ 精确 AAF_COST_AUTH → hermes
  chat **恰 1 次**（marker = [aaa-orig@custom]，**无 zzz-free@remote-api
  行**）、audit attempted=false / auth=ALLOWED_AUTHORIZED_PAID（A0 token
  如实）/ evidence「was NOT invoked」、A0 claim marker 存在、run=WAITING。
- **F2 audit persistence failure fail-closed（4/4）**：fb_success +
  AAF_TEST_AUDIT_SAVE_FAIL=1 → hermes chat **恰 2 次**（marker =
  [aaa-orig@custom, zzz-fb@custom]——attempt 真实发生）→ hermes_result.md
  以 FRAMEWORK_ERROR 开头且含显式「audit closure」文本、fallback_runtime.json
  **不存在**、run=WAITING、codebuddy 未 spawn（无 chain）。
- **F3 one-fallback no-chain（4/4）**：aaa-orig 与 zzz-fb 都失败 → hermes
  chat 恰 2 次（无第三模型）、audit attempted=true used=false
  final=zzz-fb、run=WAITING、codebuddy 未 spawn。
- **F4 auth mismatch blocked（4/4）**：错误 scope AAF_COST_AUTH → guard
  BLOCKED → hermes chat 恰 1 次、audit attempted=false / auth=BLOCKED、
  run=WAITING。
- **parent 驱动复跑（5/5）**：N1 baseline fail-closed / N2 one-fallback
  success（used=true SUCCESS）/ N3 fallback failure no chain / N4 no-candidate
  fail-closed / N5 no silent paid——在 corrected code 上全部保持（修复未
  改变任何既有 FREE fallback 语义）。

退出码 = 失败场景数：FIX-001 驱动 0（4/4），parent 驱动复跑 0（5/5）。

## 6. 边界（不重开 / 未进入 / 未实现）

- A5 保持 **STARTED / NOT CLOSED / NOT COMPLETE**——REQUIRED_BEFORE_A5_CLOSE
  9 项 formal completion boundary **不重写**（free→paid escalation 路径 /
  Cost Gate UX 仍未开始）；本 FIX-001 只修复 parent runtime 单元的两个
  runtime-contract defects，不改变 A5 scope 判定。
- fallback_contract.py（decision + audit foundation 语义，attempted/used 恒
  False）**byte-identical 零修改**；cost_guard.py（A0 Paid Guard 权威）零
  修改——不存在第二套授权/成本/资格判断系统。
- active_routing.py（A3）/ workbuddy_routing.py（A4）/ adapters.py /
  model_registry.py 零修改——A3 初始 active routing 行为、A4 WorkBuddy
  routing、A0 guard 行为全部保持（Requirement 3）。
- A6（health/quarantine/requalification）与 A4+（HIGH/CRITICAL/Codex
  routing）边界保持 outside；paid escalation 实现 = 后续 A5 任务 scope
  （本任务显式不实现）。
- 无功能删除、无未来能力放弃；无无关 cleanup；PRE_ALLOWED_UNTRACKED
  保留；no push。

## 7. 变更清单

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/fallback_runtime.py` | 修复单元：模块 docstring（FIX-001 语义）+ admission 分支（仅 ALLOWED_FREE 可 invoke；ALLOWED_AUTHORIZED_PAID → 拒绝并如实审计）+ post-invocation audit closure fail-closed（attempted=true/used=false/result_text=None/audit_closure_error）+ validator 不变量（attempted⟹ALLOWED_FREE；eligible-未attempt ∈ {BLOCKED, ALLOWED_AUTHORIZED_PAID}）+ _emit 失败详情捕获 + no-silent-paid evidence 措辞按 attempted 区分 |
| `ai_agent_framework/runner.py` | audit_closure_error 显式 surface：stderr + 追加 stage result 文本（FRAMEWORK_ERROR 前缀保持 → 链 fail closed） |
| `tests/test_a5_fallback_runtime.py` | +9 项 FIX-001 聚焦测试（§3） |
| `tests/fresh_runner_a5_free_fallback_fix001_wrapper.py` | FIX-001 fresh-runner wrapper（registry modes：baseline / fb_success / fb_paid_admission；AAF_TEST_AUDIT_SAVE_FAIL 注入；production 零 hook） |
| `tests/fresh_runner_a5_free_fallback_fix001_validation.py` | FIX-001 fresh-runner driver（F1–F4；exit code = 失败数） |
| `docs/internal/PROJECT_STATE.md` | header Last Updated 新条目 + 「A5 Scope Formalization」块 A5 实现状态 bullet（FIX-001 修复事实） |
| `docs/internal/AAF_MASTER_BACKLOG.md` | CAP-003 全行 + 摘要表同步（A5 = STARTED；runtime 单元 = 已修复状态） |
| `docs/internal/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001-REPORT.md` | 本报告 |

Parent `a0ac326` 未 amend；新 commit 记录本 FIX-001。no push。
