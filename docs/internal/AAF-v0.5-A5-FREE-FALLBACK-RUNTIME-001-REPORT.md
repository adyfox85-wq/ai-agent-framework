# AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001 — Implementation Report

> Task: Implement bounded FREE fallback runtime
> （A5 第二条实现单元：把已验收的 A5 fallback decision/audit contract 接入真实
> Hermes executor live runtime path——每 affected stage 最多 1 次 FREE/LOCAL_FREE
> model-level automatic fallback；本任务不实现 paid escalation）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Baseline: HEAD = local/origin `9216426263aad2a9802933108bb572cecccf62ff`（未 push）

## 1. 结论（先给结论）

1. ✅ **A5 fallback contract 已接入真实执行路径**（Requirement 1/2/3/5）：新模块
   `ai_agent_framework/fallback_runtime.py` = A5 fallback runtime layer；runner
   Hermes executor stage 的原始模型 invocation **真实失败后**（A3 初始 active
   routing 行为零修改，Requirement 9）至多发起**一次** automatic model-level
   fallback attempt，候选只允许 FREE/LOCAL_FREE。
2. ✅ **不创建平行判断系统**（Requirement 1）：decision = `fallback_contract.
   decide_fallback`（唯一权威；其内部复用 A2 selector → A1 registry/risk 契约：
   role 适用性 → capability → qualification → executor main-scope 闸）——
   fallback_runtime 零 eligibility 判断；Requirement-3 的 cost gate 复用 A3
   `active_routing.ACTIVE_ROUTING_COST_CLASSES`（FREE/LOCAL_FREE，同一词汇）；
   candidate admission 复用 A0 Paid Guard（`cost_guard.evaluate`）；
   candidate env 覆盖复用 A3 env 契约 / `restore_routing_env` 还原机制。
3. ✅ **exactly-one / no-chain / no-candidate fail closed**（Requirement 2/4/5/7）：
   - fallback_attempted=true 仅当第二个不同模型的 invocation 被实际发起；
   - fallback_used=true 仅当该 fallback invocation 的输出成为被接受的 stage
     执行结果（valid、非 FRAMEWORK_ERROR）；
   - 失败的 fallback = 一次 attempt（used=false），stage 保留原始失败文本，
     绝不触发第二次 fallback（无 A→B→C chain / 无 loop）；
   - 无合格 FREE/LOCAL_FREE 候选 → 不 invoke 第二模型、保留原始失败、
     attempted=false / used=false（显式 reason，fail closed）。
4. ✅ **no silent paid fallback**（Requirement 8/Context）：paid/unknown-cost
   候选被 cost gate 显式排除（notes 可审计）；eligible 候选仍须过 A0 Paid
   Guard admission——ALLOWED_FREE / ALLOWED_AUTHORIZED_PAID 才 invoke，
   BLOCKED_COST_APPROVAL → 不 invocation（authorization_outcome=BLOCKED
   + 显式 notes）；本任务零 paid escalation 实现（paid_escalation_required
   只在分类语义中出现；authorization 消费仍走既有 task-scoped Paid Guard）。
5. ✅ **Authoritative live audit**（Requirement 6/10）：每 live outcome 持久化
   `fallback_runtime.json`（authoritative=true；decision_kind=
   fallback_runtime_audit）——original actual model/provider、failure
   class/trigger（evidence-based 分类）、selected fallback candidate、
   attempted/used、paid_escalation_required、authorization_outcome、final
   actual model/provider、explicit no-silent-fallback evidence；经
   `validate_fallback_runtime_record` fail-closed 校验（used⟹attempted；
   attempted⟹decision=fallback_eligible 且 admission ALLOWED 且 final actual
   == candidate；eligible 未 attempt ⟹ authorization_outcome=BLOCKED；
   budget=1）。与 contract decision record（foundation 语义：attempted/used
   恒 False、final==original）以 decision_kind + authority 明确区分——闭合约
   contract 模块（fallback_contract.py）**byte-identical 零修改**。
6. ✅ **最小 evidence-based 失败分类**（classify_failure）：MISSING_COMMAND /
   非 invocation 异常 → framework_input_config（blocked_fail_closed，非
   fallback 上下文）；TimeoutExpired → transport_runtime（trigger-capable）；
   其他 RuntimeError → invocation_failure（trigger-capable）；无证据证明
   模型级失败 → 一律不评估（fail closed）。
7. ✅ **测试**（Requirement 10/11）：30 项新增聚焦
   （tests/test_a5_fallback_runtime.py：Req 10 全矩阵——eligible→恰一次
   attempt / fallback success→used=true+final=candidate / fallback failure→
   无第三模型 / 无 free 候选→无第二 invocation / aux+unknown qualification
   排除 / same original model 排除 / paid+unknown-cost 不静默使用（含 A0
   BLOCKED 路径）/ 非 fallback-eligible 失败→无 fallback / transport retry
   不消耗预算 / 每 live outcome audit 校验 + 真实 runner 集成全链），
   全量 non-GUI 4-file-deselect **2026 passed / 1 skipped / 38 deselected**
   = HEAD 基线 **1996 + 30 精确零回归**（A3/A4/A0/contract 测试零失败）。
8. ✅ **Fresh-runner 全新进程验证**（Requirement 12）：**5/5** 场景全绿
   （新 python 进程 + 真实 runner + 真实 child fake CLIs + env marker 证据），
   见 §5。
9. ✅ **状态文档按需更新（Requirement 13）**：A5 保持 **STARTED**（NOT CLOSED
   / COMPLETE——REQUIRED_BEFORE_A5_CLOSE 9 项仍未全部满足：free→paid
   escalation 路径 / Cost Gate UX 未开始）；PROJECT_STATE「A5 Scope
   Formalization」块 + header + backlog CAP-003 全行同步；A6 / A4+ 边界保持
   outside；A0-A4 不重开。
10. ✅ **范围纪律（Requirement 14）**：无无关清理；PRE_ALLOWED_UNTRACKED
    （.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs）
    保留；no push。

## 2. 设计（最小 live runtime path + 复用纪律）

**Live path**：runner.py Hermes stage——原始 invocation 在 try/except 中抛
异常（CLI 非零退出 / 空输出 / timeout / 缺失）→ A5 层在 **原始执行失败之后**
评估（guard 前置阻断 = 无模型执行失败 → 无 fallback 上下文，A0 authority 持有，
不评估；Risk 缺失 → contract 无法决策 → 不评估）。这与 A3 初始 active routing
（invocation **之前**的选择）严格分离（Requirement 9）。

**决策链**（全部复用既有 authority）：
1. `classify_failure(exc)` → A5 failure class + trigger + evidence；
2. original actual model/provider = env override（AAF_HERMES_MODEL/... =
   invocation truth）优先，否则 `cost_guard.resolve_effective_hermes`；
3. `fallback_contract.decide_fallback(...)` → contract decision record
   （`validate_fallback_record` 内部复核；候选 = A2 selector eligible 排除
   original——same-model 恢复 = RW-027 retry 层语义保持）；
4. Requirement-3 cost gate（`FALLBACK_COST_CLASSES` = A3 成本闸）→ runtime
   决策：contract eligible + gated 非空 → fallback_eligible（多候选按
   (economic rank, locality, key) 确定性选恰一——economic rank 复用
   `shadow_routing.economic_rank`）；否则 fallback_not_eligible + 显式
   reason（NO_QUALIFIED_FALLBACK_CANDIDATE / BUDGET_EXHAUSTED /
   ONLY_SAME_MODEL / contract 原 decision）；
5. eligible 时：candidate env 覆盖（**candidate 无 base_url 时显式清除 stale
   覆盖**——A3 初始 routing overlay 残留的 loopback base_url 绝不误导 A0
   判定 LOCAL_FREE）→ `cost_guard.evaluate`（A0 authority）→ ALLOWED → invoke
   恰一次；BLOCKED / admission 失败 → 还原 env、不 invocation（fail closed）；
6. 最终 audit record 组装 + 校验 + 原子落盘（fallback_runtime.json）。

**Audit record 与 contract decision record 的关系**：同一 31 字段 schema
词汇；contract record（decision_kind=fallback_decision）表达「permission
层决策」（foundation 语义不变，attempted/used 恒 False、final==original，
`validate_fallback_record` 零修改）；live audit record
（decision_kind=fallback_runtime_audit）表达「本执行单元的实际结果」——按
Requirement 7 语义如实记录 attempted/used/final actual，由
`validate_fallback_runtime_record` 用 live 不变量校验。两种 record 以
decision_kind + authority 字段互不混淆（A3 active_routing.json 与 A2
shadow_observation.json 的区分同型）。

**候选 env 与 observation 顺序**：fallback candidate overlay 在 model/shadow
observation **之后**才还原（observation 必须如实看到 final actual invocation
model——shadow observation 读 env 覆盖），还原顺序 = 设置的逆序（先 fallback
overlay，再 A3 routing overlay），绝不泄漏到后续 stage / 调用方。

## 3. 测试证据（Executor 实测）

- 新增 `tests/test_a5_fallback_runtime.py` **30 passed**（0.1s 内）：
  - classify_failure 矩阵（RuntimeError→invocation / MISSING_COMMAND→framework
    config / TimeoutExpired→transport_runtime / OSError+ValueError+KeyError→
    framework config fail closed）；
  - 编排器矩阵：eligible+success → attempted/used=true + final=candidate +
    overlay 返回 + artifact 落盘 reload 复验；eligible+fallback failure →
    attempted=true/used=false/result_text=None（保留原始失败）；paid+unknown
    池 → not_eligible + 零 invocation + auth none + notes 显式 cost-gate
    排除；aux/unknown qualification → 被 selector 排除（candidates 空）；
    same-original 排除（含 original 为唯一合格候选 → ONLY_SAME_MODEL fail
    closed）；OSError/MISSING_COMMAND → blocked_fail_closed 零 attempt；
    TimeoutExpired → trigger-capable 恰一次 attempt；transport_retry_count=3
    → budget 不受影响（attempted 照常、evidence 显式分离）；远程 FREE 候选
    无授权 → A0 BLOCKED → 零 invocation + authorization_outcome=BLOCKED +
    env 还原；Risk 缺失 → None 零 artifact；多 free 候选 → 确定性选中
    aaa-fb（locality+key）恰一次；audit validator 变异矩阵（used 无
    attempted / attempted 无 ALLOWED / final≠candidate / eligible-未attempt
    非 BLOCKED / original 入 candidates / 未知字段 / authority 篡改 /
    decision_kind 错 / count 超预算 → 全 ValueError）；
  - 真实 runner 集成（monkeypatch run_agent + baseline_registry 受控注入）：
    A3 初始路由 aaa-orig → 失败 → 恰一次 fallback zzz-fb（第二次 invocation
    env 覆盖 = zzz-fb）→ SUCCESS + stage fallback_runtime_ref；fallback 也失败
    → 恰 2 次调用无第三模型 → WAITING + 原始 FRAMEWORK_ERROR 保留；paid/
    unknown 池 → 1 次调用 fail closed；aux-only 候选 → 1 次调用；MISSING
    COMMAND → blocked 零 attempt；A3-routed same-model-only → 1 次调用
    （A3 no-silent-fallback 语义在 A5 有界评估下保持 fail closed）；远程
    FREE 无授权 → A0 BLOCKED 零 attempt（no silent paid）；Risk 缺失 →
    无 A5 评估（无 artifact，行为与 A5 前一致）；成功路径 A3 routing 照常
    applied + 无 A5 artifact。
- 全量 non-GUI 4-file-deselect（项目固定回归口径：
  `--deselect tests/test_phase_e_cancel_ui_e2e.py --deselect
  tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py
  --deselect tests/test_phase_f_e2e.py`）：**2026 passed / 1 skipped / 38
  deselected** in 72.32s = HEAD（9216426）基线 **1996 + 30 精确零回归**。
- 注：裸 `pytest tests/` 会在真实桌面 UI E2E（test_phase_e_cancel_ui_e2e.py）
  处触发 Windows fatal exception——既有环境性 E2E 崩溃，与本次变更无关
  （项目固定以 non-GUI 4-file-deselect 为回归口径）。

## 4. 验收对照（Acceptance）

- live runtime 可执行恰一次 eligible FREE/LOCAL_FREE fallback ✅（runner
  集成测试 + fresh-runner N2：invocation 计数 = 2、marker MODEL 行 =
  aaa-orig@custom → zzz-fb@custom、used=true、final=zzz-fb）
- fallback contract 是 decision/audit 语义 authority ✅（runtime 只调用
  decide_fallback + validate_fallback_record；contract 模块零修改）
- qualification/capability/risk 先于 economics ✅（selector 闸原样生效；
  cost gate 在其后；fresh-runner N5 paid 池被排除）
- 无 fallback chain/loop ✅（fresh-runner N3：恰 2 次 invocation、attempted=
  true/used=false、无第三模型；单次调用点 + budget=1 validator 不变量）
- 无 silent paid fallback ✅（N5 + A0 BLOCKED 路径 + cost-gate notes +
  authorization_outcome 审计）
- 无 eligible candidate → fail closed ✅（N1 baseline 真实 registry /
  N4 受控唯一候选：1 次 invocation、attempted=false、WAITING、原始失败保留）
- audit 准确记录 attempted/used/final model ✅（N1-N5 artifact 全字段 +
  validator 全绿）
- focused tests pass ✅（30/30）
- canonical regression passes ✅（2026 passed / 1 skipped / 38 deselected，
  精确零回归）
- fresh-runner closure passes ✅（5/5，全新进程）
- WorkBuddy independent verification：route 阶段执行
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None
- no push ✅

## 5. Fresh-runner N+1 验证证据（Requirement 12，全新进程）

驱动 = `tests/fresh_runner_a5_free_fallback_validation.py`（wrapper =
`tests/fresh_runner_a5_free_fallback_wrapper.py`，模块级 registry 注入 +
fake bin PATH 前置；与 A3/A4 fresh-runner 同一技术，production 代码零
test hook）。每个场景 = 全新 python 进程运行真实 runner + 真实 child
fake hermes.bat/codebuddy.bat/codex.bat；每次 hermes chat invocation 向
marker append `MODEL=<model>@<provider>`（env 覆盖 = actual invocation
model）。证据目录（不提交）：
`.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001/fresh-runner-validation/`。

| # | 场景 | 结果（实测） |
|---|---|---|
| N1 | baseline 真实 registry + 精确 AAF_COST_AUTH：deepseek-v4-flash@deepseek 失败 → same-model 排除后无候选 | hermes chat **恰 1 次**；audit attempted=false/used=false、decision=fallback_not_eligible、original=deepseek-v4-flash；run=WAITING（corrected code loaded + no candidate => fail closed under REAL facts） |
| N2 | fb_success 受控池（aaa-orig/zzz-fb 双 LOCAL_FREE main-scope）+ fail aaa-orig | hermes chat **恰 2 次**（marker：MODEL=aaa-orig@custom → MODEL=zzz-fb@custom）；audit attempted=true/used=true、final_actual=zzz-fb/custom、decision=fallback_eligible、authorization_outcome=ALLOWED_FREE；run=**SUCCESS**（at most one fallback + used） |
| N3 | fb_success + aaa-orig 与 zzz-fb 均失败 | hermes chat **恰 2 次（无第三模型）**；audit attempted=true/used=false、final_actual=zzz-fb；codebuddy 未 spawn（chain 中断）；run=WAITING（fallback failure => no chain） |
| N4 | fb_single（唯一候选 aaa-orig）→ 失败 | hermes chat **恰 1 次**；audit attempted=false、fallback_candidates=[]、decision=fallback_not_eligible；hermes_result 保留 FRAMEWORK_ERROR；run=WAITING（no candidate => fail closed） |
| N5 | fb_paid_pool（aaa-orig + zzz-paid PAID + mmm-unk UNKNOWN）→ fail aaa-orig | hermes chat **恰 1 次**；audit attempted=false、decision=fallback_not_eligible、candidates 无 paid/unknown、notes 显式 cost-gate 排除、authorization_outcome=none；run=WAITING（no silent paid fallback） |

全部场景 `FAILURES: 0`（每场景 artifact 经 `validate_fallback_runtime_record`
复验 + run.json/result.md 断言）。A5 层生效（fallback 实际发生）本身即证明
**修正后的 runtime 代码在全新进程中被实际加载**——若加载的是旧 runner
（A5 之前语义），N2 不会产生第二次 invocation。

## 6. 边界（不重开 / 未进入 / 未实现）

- **A5 = STARTED（NOT CLOSED / COMPLETE）**：本单元 = runtime 接线 +
  automatic FREE/LOCAL_FREE fallback 实际执行（REQUIRED_BEFORE_A5_CLOSE
  #2/#3/#4/#5/#6/#8/#9 的实现贡献）；free→paid escalation 路径与 Cost Gate
  UX（#7 及其余）仍为后续独立 Planner-approved 单元（未开始）；9 项全部满足
  后方可 CLOSE。
- **paid escalation 未实现（Requirement 8）**：本单元零付费模型调用；A0 Paid
  Guard 语义权威保持（candidate admission 复用、授权消费/一次性语义不变）；
  paid_escalation_required 分类只记录「恢复必经 A0 authority」，不产生任何
  授权动作。
- **A6**（health scoring / quarantine / long-term availability / automatic
  requalification / calibration / ongoing observation policy）显式 outside，
  未进入。
- **A4+**（HIGH / CRITICAL WorkBuddy routing、broader Codex / multi-agent
  routing）显式 outside，未进入。
- **A0-A4 不重开**：A0 Paid Guard / A3 Hermes routing / A4 WorkBuddy economic
  routing 已关闭历史不可变；fallback_contract.py（A5 已验收 contract）零修改
  （byte-identical）；active_routing.py / workbuddy_routing.py / cost_guard.py
  / adapters.py / model_registry.py / shadow_routing.py 零修改。
- 无功能删除、无未来能力放弃；REQUIRED_BEFORE_A5_CLOSE / completion
  boundary 文档不重写（2026-09-02 AAF-v0.5-A5-SCOPE-FORMALIZATION-001 仍为
  唯一权威边界定义）。

## 7. 变更清单

- `ai_agent_framework/fallback_runtime.py`（新增——A5 bounded FREE/LOCAL_FREE
  fallback runtime layer：classify_failure / Requirement-3 cost gate /
  确定性候选选择 / live audit record + validate_fallback_runtime_record /
  run_fallback_after_failure 编排器 / 原子落盘）
- `ai_agent_framework/runner.py`（Hermes stage 集成：捕获 invocation 异常 →
  原始执行失败后调用 fallback 层（Risk 缺失 / guard 前置阻断不评估）；A5
  audit artifact ref 进 stage result；fallback candidate env overlay 在
  observation 后还原）
- `tests/test_a5_fallback_runtime.py`（新增——30 项聚焦测试：Req 10 全矩阵
  module + 真实 runner 集成）
- `tests/fresh_runner_a5_free_fallback_wrapper.py`（新增——fresh-runner
  wrapper：registry 受控注入模式 baseline/fb_success/fb_single/fb_paid_pool）
- `tests/fresh_runner_a5_free_fallback_validation.py`（新增——N+1 验证驱动
  N1-N5，全新进程 + fake CLIs + marker/audit 断言）
- `docs/internal/PROJECT_STATE.md`（header Last Updated 新条目 +「A5 Scope
  Formalization」块「当前实现事实」更新 +「A5 实现状态」新 bullet：
  A5 保持 STARTED / runtime 单元已交付 / NOT CLOSED）
- `docs/internal/AAF_MASTER_BACKLOG.md`（CAP-003 title / Status / Current
  Implementation / Remaining Gap / Do Not Forget / Summary 行同步）
- 本 REPORT（docs/internal/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-REPORT.md）
