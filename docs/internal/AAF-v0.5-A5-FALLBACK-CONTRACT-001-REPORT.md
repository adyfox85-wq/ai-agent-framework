# AAF-v0.5-A5-FALLBACK-CONTRACT-001 — Implementation Report

> Task: Implement A5 fallback decision and audit contract
> （A5 第一条实现单元：唯一权威 fallback decision / audit contract foundation——
> 统一、可审计地描述「是否出现可触发 fallback 的失败」并给出有界决策；本任务
> 不执行第二模型、不实现 paid escalation、不接入 runtime）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Baseline: HEAD = origin/main = `cc404c12b83f4aa34d517ae10172faf95d6d81ac`（未 push）

## 1. 结论（先给结论）

1. ✅ **唯一权威 A5 fallback decision contract 已交付**（Requirement 1）：
   新模块 `ai_agent_framework/fallback_contract.py`（纯逻辑、无 I/O/网络/LLM/
   subprocess、确定性、可测试）——`decide_fallback()` 产出 machine-readable
   decision + audit record，`validate_fallback_record()` fail-closed 复核。
   **不创建平行 routing / cost / qualification 判断系统**：候选资格完全复用
   A2 selector（`shadow_routing.select_shadow_candidate` → A1 registry/risk
   契约：capability → qualification → executor main-scope 闸），本模块只在其
   `eligible` 之上做 fallback 层判定；cost/authorization 维度不做本层判断
   （paid/cost 场景由调用方按既有 A0 Paid Guard / Cost Guard 事实分类，两类
   永不产出 fallback_eligible）。
2. ✅ **Bounded failure taxonomy 已定义**（Requirement 2）：8 类（Req 2 五类
   + A5 scope 文档 minimum classes 余项）——`invocation_failure`（model/
   provider invocation failure）、`unavailable_unsupported_model_provider`、
   `capability_qualification_failure`（execution boundary 发现）、
   `quality_validation_failure`、`transport_runtime_failure`（RW-027 层）、
   `cost_authorization_blocked`、`paid_escalation_required`、
   `framework_input_config_failure`；token/label 一一对应、词汇有界。
3. ✅ **决策输出 4 token 可区分**（Requirement 3）：`fallback_eligible` /
   `fallback_not_eligible` / `paid_escalation_required` /
   `blocked_fail_closed`——决策矩阵确定性（见 §2）。
4. ✅ **规则全部保留**（Requirement 4）：same-model transport retry（RW-027）≠
   model-level fallback（`transport_retry_count` 独立字段、不计入预算、绝不翻转
   attempted/used）；one-fallback rule 编入 schema（budget = 1 常量 +
   `automatic_fallback_count_used ∈ {0,1}`，>1 输入 → ValueError fail closed）；
   预算耗尽即拒 → **无 fallback chain / loop**；same-model 恢复自动排除在
   fallback candidates 之外（= retry 层）。
5. ✅ **Authoritative audit record / schema**（Requirement 5）：Req 5 全部字段
   在场（task/stage/role/risk、original model/provider、failure class/trigger、
   fallback eligibility、candidates、attempted/used、paid escalation required、
   authorization outcome、final actual model/provider、explicit
   no-silent-fallback evidence）+ JSON 可序列化 + validate fail-closed
   （缺字段/未知字段/枚举违例/不变量违例一律 ValueError）。
6. ✅ **foundation 语义（Requirement 6）**：fallback_attempted / fallback_used
   恒 False（模块无执行 authority；validate 拒绝任何 True 的 record）；无第二
   模型执行；无 paid fallback 实现（authorization_outcome 恒 "none"，绝不产生
   授权结果——任何未来 paid 路径必须消费既有 A0 authority）；final actual ==
   original；**A3/A4 路由与 A0 Paid Guard 行为零变化**（模块未被任何 live 路径
   import——源码级 grep 实证仅 authority 字符串自引用 + 测试文件）。
7. ✅ **Fail closed**（Requirement 7）：未知 failure_class / role / risk /
   malformed 输入 / 超预算 count / 负 retry count / 非 dict registry 等 →
   ValueError（16 项 malformed 参数化 + 非法 record 变异测试锁定）。
8. ✅ **测试**（Requirement 8）：131 项新增聚焦（tests/test_a5_fallback_contract.py），
   全量 non-GUI 4-file-deselect **1963 passed / 1 skipped / 38 deselected**
   = HEAD（cc404c1）基线 **1832 + 131 精确零回归**。
9. ✅ **状态文档按需更新（Requirement 9）**：A5 = **STARTED**（第一条实现单元
   交付；**NOT CLOSED / COMPLETE**——REQUIRED_BEFORE_A5_CLOSE 9 项未全部
   满足：runtime 接线 / automatic fallback 执行 / free→paid / Cost Gate UX
   等剩余单元未开始）；A6 / A4+ 边界保持 outside；A0-A4 不重开。
10. ✅ **范围纪律（Requirement 10）**：无无关清理；PRE_ALLOWED_UNTRACKED
    保留；no push。

## 2. Decision contract（权威语义摘要）

**决策矩阵（确定性；class 边界优先于候选存在性）**：

| failure class | 条件 | decision |
|---|---|---|
| trigger-capable 5 类（invocation / unavailable / capability-qualification / quality-validation / transport-runtime） | 预算已耗尽（count_used == 1） | fallback_not_eligible（AUTOMATIC_FALLBACK_BUDGET_EXHAUSTED——no chain/loop） |
| 同上 | 无 A1/A2 gate 合格**其他**候选 | fallback_not_eligible（NO_QUALIFIED_FALLBACK_CANDIDATE / ONLY_SAME_MODEL_RECOVERY_IS_RETRY_NOT_FALLBACK + 显式 reason） |
| 同上 | 存在合格其他候选 | **fallback_eligible**（有界可审计；foundation 不执行——attempted/used 恒 False；>1 候选时 fallback_candidate=None，选择权留未来 runtime 单元） |
| paid_escalation_required | 任何情况 | **paid_escalation_required**（never automatic；authorization_outcome=none；未来 paid 路径必须经既有 Paid Guard / Cost Guard，fail closed） |
| cost_authorization_blocked | 任何情况（含候选存在） | **blocked_fail_closed**（A0 Paid Guard 前置 authority 持有；无模型执行失败 → 无 fallback 上下文；不引入 fallback-from-cost-block） |
| framework_input_config | 任何情况（含候选存在） | **blocked_fail_closed**（诚实 FRAMEWORK_ERROR；非 fallback 上下文） |

**关键不变量（validate_fallback_record 强制）**：attempted/used 必须 False；
budget 必须 == 1；count_used ∈ [0,1]；final actual == original；decision 与
flags/candidates/class 互洽；fallback_eligible ⟹ 候选非空且 class trigger-capable
且预算未耗尽；非 eligible 决策必须带显式 decision_reason；candidates 唯一有序且
不含 original key；no_silent_fallback_evidence 非空。

**与既有权威的关系（复用纪律）**：fallback 候选枚举 = 复用
`select_shadow_candidate`（executor 角色主调用资格闸、capability/qualification
闸原样生效——auxiliary-only / unknown-scope / 未合格候选绝不出现在 fallback
candidates，测试锁定）；不复制 A1/A2/A3/A4/A0 任何判断。

## 3. 测试证据（Executor 实测）

- 新增 `tests/test_a5_fallback_contract.py` **131 passed**（0.13s）：
  - taxonomy：Req 2 五类 label 全覆盖断言 + 8 类逐一产出合法 record；
  - 决策矩阵：5 个 trigger-capable 类 × {合格候选 → eligible（候选列表完整、
    sole candidate 记录/多候选 None）/ 无候选 → not_eligible + 显式 reason /
    空 registry → not_eligible}；blocked 2 类在**候选存在时**仍 blocked_fail_closed
    （类边界优先）；paid escalation required → paid_escalation_required +
    auth outcome none；
  - 候选资格复用：tier=None / qualification=unknown / NOT_QUALIFIED /
    auxiliary-only（executor）/ unknown-scope（executor）全部被既有 gate 排除；
    MEDIUM floor（T3）下 T4 候选不 eligible（能力先于一切）；非 RegistryEntry
    registry 值按 UNSUPPORTED 排除不中断决策；输入顺序无关；
  - same-model 规则：original 也是 qualified 候选 → 从 candidates 排除（notes
    显式记录）；original 为唯一合格候选 → not_eligible（ONLY_SAME_MODEL）；
    `transport_retry_count=5` → count_used 0 / attempted-used False / decision
    与 retry=0 相同 / notes + no-silent evidence 显式记录「不计为 fallback」；
  - one-fallback：count_used=1 + 合格候选存在 → not_eligible
    （BUDGET_EXHAUSTED，validate 通过——合法 stage 状态）；count_used ∈
    {2, 3, -1, "1", 1.5, True} → ValueError；budget 常量 == 1；
  - malformed fail-closed：16 项参数化（未知 class / 空 trigger / 空 task_id /
    空 stage / 非法 role / 未知 risk / 空 risk_source / 空 original model /
    空白 provider / 非 dict registry / 负或非 int retry / 超预算 count /
    trigger_evidence 非法）；
  - audit schema：Req 5 17 字段全部在场 + JSON 可序列化；逐一删除 required
    field → ValueError；19 项不变量变异（attempted=True / used=True / budget=2 /
    count=2 / final≠original / flags 与 decision 矛盾 / 未知 decision / 未知
    class / label 错配 / auth outcome 非 none / 非法 role / risk / 空 evidence /
    candidates 重复/乱序/含 original / 缺 decision_reason / 多余字段 / 空
    generated_at）全部 ValueError；eligible 无候选 → ValueError；
  - foundation fixed semantic：8 类 × 3 种 registry 全场景矩阵 attempted/used
    恒 False、final actual == original、auth outcome == none、validate 通过。
- 全量 non-GUI 4-file-deselect（与既往同一排除约定：
  `--deselect tests/test_phase_e_cancel_ui_e2e.py --deselect
  tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py
  --deselect tests/test_phase_f_e2e.py`）：**1963 passed / 1 skipped / 38
  deselected** in 70.55s = HEAD（cc404c1）基线 **1832 + 131 精确零回归**。
- 注：未加 4-file-deselect 的裸 `pytest tests/` 会在
  test_phase_e_cancel_ui_e2e.py 真实桌面 UI E2E 处触发 Windows fatal
  exception（bridge launcher GC breakpoint）——既有环境性 E2E 崩溃，
  与本次变更无关（本项目固定以 non-GUI 4-file-deselect 为回归口径）。

## 4. 验收对照（Acceptance）

- one authoritative A5 fallback decision contract exists ✅
  （ai_agent_framework/fallback_contract.py，唯一权威；REPORT 记录于本任务）
- bounded failure taxonomy exists ✅（8 类；Req 2 五类全覆盖断言）
- audit artifact/schema machine-readable and validated ✅
  （dict + JSON 可序列化 + validate_fallback_record fail-closed + Req 5 字段
  逐一测试）
- no second-model execution introduced ✅（模块零 runtime 接线；attempted/used
  恒 False；无任何调用第二模型的代码路径存在）
- no silent fallback possible ✅（validate 拒绝 attempted/used=True；eligible
  仅 contract-level permission；final actual == original 强制；explicit
  no-silent-fallback evidence 必填）
- existing routing/Paid Guard semantics unchanged ✅（A3 active_routing /
  A4 workbuddy_routing / A0 cost_guard / runner / adapters 零修改；新模块零
  live import；1963 全量回归零失败）
- focused tests pass ✅（131/131）
- WorkBuddy independent verification：route 阶段执行
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None
- no push ✅

## 5. 验证证据（Executor 实测）

- `git status`：tracked 变更 = 本任务 4 个文件（1 新增 .py + 1 新增 test + 2
  docs 修改，待 REPORT 入库后 = 1 新增 REPORT）；untracked 仅既有
  PRE_ALLOWED_UNTRACKED 常驻项（`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、
  `scripts/start_bridge_hidden.vbs`）+ 本任务临时脚本（.aaf 下，不入库）
- `git diff --stat` 见 commit message；无 cost_guard / active_routing /
  workbuddy_routing / runner / adapters / model_registry / risk_contract /
  shadow_routing 修改
- 源码级 grep：`fallback_contract` 在 ai_agent_framework/ 下仅 authority
  字符串自引用（`fallback_contract.py:99`），无任何 live 模块 import
- baseline HEAD = `cc404c12b83f4aa34d517ae10172faf95d6d81ac` 记录于本任务
  Context；origin/main = same（未 push）

## 6. 边界（不重开 / 未进入 / 未实现）

- **A5 = STARTED（NOT CLOSED / COMPLETE）**：本单元 = foundation（decision +
  audit contract）；REQUIRED_BEFORE_A5_CLOSE 9 项中本单元贡献 contract 层
  （failure classification / bounded one-fallback schema / audit record），
  runtime 接线、automatic fallback 实际执行、free→paid 授权路径、Cost Gate
  UX 仍为后续独立 Planner-approved 单元（未开始）；9 项全部满足后方可 CLOSE。
- **A6**（health scoring / quarantine / long-term availability / automatic
  requalification / calibration / ongoing observation policy）显式 outside，
  未进入。
- **A4+**（HIGH / CRITICAL WorkBuddy routing、broader Codex / multi-agent
  routing）显式 outside，未进入（prerequisite 记录保持）。
- **A0-A4 不重开**：A0 Paid Guard / A3 Hermes routing / A4 WorkBuddy economic
  routing 已关闭历史不可变；本任务对 A0/A3/A4 行为零修改。
- 无功能删除、无未来能力放弃；REQUIRED_BEFORE_A5_CLOSE / completion
  boundary 文档不重写（2026-09-02 AAF-v0.5-A5-SCOPE-FORMALIZATION-001 仍为
  唯一权威边界定义）。

## 7. 变更清单

- `ai_agent_framework/fallback_contract.py`（新增——唯一权威 A5 fallback
  decision contract：taxonomy / decision / audit schema / validate）
- `tests/test_a5_fallback_contract.py`（新增——131 项聚焦测试）
- `docs/internal/PROJECT_STATE.md`（header Last Updated 新条目 +「A5 Scope
  Formalization」块新增「A5 实现状态」bullet：A5 = STARTED / NOT CLOSED）
- `docs/internal/AAF_MASTER_BACKLOG.md`（header Last Updated 新条目 + CAP-003
  title / Status / Current Implementation 尾 / Remaining Gap / Do Not Forget +
  CAP-004 Do Not Forget + §7 Summary CAP-003 行——A5 = STARTED（foundation
  单元 001 已交付、NOT CLOSED / COMPLETE））
- 本 REPORT（docs/internal/AAF-v0.5-A5-FALLBACK-CONTRACT-001-REPORT.md）
