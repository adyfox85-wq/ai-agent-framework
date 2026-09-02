# AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001 — Implementation Report

> Task: Prevent auxiliary-only models from Hermes active routing
> （修复 A3 LOW Hermes active routing 的资格错误：不能把仅有 auxiliary/local
> endpoint 证据的模型当作 Hermes 主 executor 模型）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）

## 1. 结论（先给结论）

1. ✅ **根因定位**（Requirement 1）：qwen3:4b@custom 进入 Hermes executor active
   routing 的确切资格路径 = A1 registry 条目（`applicable_agents=("hermes",)` +
   `capability_tier=T4` + `qualification=QUALIFIED`，QUALIFIED evidence =
   RW-030-001 的 **auxiliary 槽位身份 + 本地端点直连** probe）
   → A2 selector 的 stage 适用性 filter（applicable_agents 含 hermes）把它当作
   hermes stage 候选 → capability（LOW floor T4）+ qualification 双闸通过 →
   **经济偏好**（LOCAL_FREE rank 0 < 真实主模型 deepseek UNKNOWN rank 2）选中
   qwen3:4b@custom → A3 cost gate（LOCAL_FREE ∈
   ACTIVE_ROUTING_COST_CLASSES）+ 防御性 qualification 复核通过 →
   routing_applied=true。缺口 = A1 qualification 契约没有表达「evidence 覆盖
   哪个调用上下文」——aux-only evidence 被静默当作主 executor 资格。
2. ✅ **修复**（Requirement 2/3/6）：A1 `RuntimeQualification` 新增 `scope`
   维度（main / auxiliary / unknown，缺省 unknown fail closed）；A2 selector
   **executor 角色**（唯一会被 active routing 真实选择/改变执行的角色）新增主调用
   资格闸：候选除 capability + qualification 双闸外必须 `qualification.scope ==
   main`（auxiliary → `AUXILIARY_ONLY`；unknown → `MAIN_INVOCATION_UNPROVEN`）。
   validator / reviewer hypothetical 语义零变化；capability / qualification /
   cost gate 顺序与强度零减弱（专项测试锁定：能力闸先于 scope 闸、status 闸先于
   scope 闸）。A3 active_routing / runner / cost_guard / adapters **生产逻辑零改动**
   ——同一 selector 语义自动修正 A3（复用纪律保持：不创建第二套路由判断）。
3. ✅ **当前真实证据行为**（Requirement 4/5，Acceptance 1/2）：
   qwen3:4b@custom **不再是** LOW Hermes executor 的 eligible/selected 候选
   （excluded=AUXILIARY_ONLY，可审计）；唯一 main-scope eligible =
   deepseek-v4-flash@deepseek（其 qualification evidence = 真实 AAF 执行经
   Hermes main-chat 调用路径），但 cost_class=UNKNOWN 非 FREE → A3 cost gate
   拒绝（SELECTED_NOT_FREE）→ **routing_applied=false、configured DeepSeek
   保留、fallback_attempted=false、Paid Guard 行为零变化**。LOW 无合格
   FREE/LOCAL_FREE Hermes executor 时保持 configured 是**正确状态**——未来免费
   executor 必须拿到真实 main-chat 调用路径 qualification evidence
   （scope=main）才可能被路由；绝不因 FREE / 本地端点 / LOW probe 自动提升。
4. ✅ **valid qualified Hermes executor behavior remains supported**
   （Requirement 8/Acceptance）：scope=main + QUALIFIED + LOCAL_FREE 的候选仍被
   真实 active route（单元 + runner + fresh-runner N2 全链实证，guard
   ALLOWED_FREE 零授权）。
5. ✅ **回归**：全量 non-GUI 4-file-deselect **1832 passed / 1 skipped / 38
   deselected** = HEAD（f6c577d）基线 1815 + 17 精确零回归；fresh-runner N+1
   **4/4**（Requirement 9：全新进程验证修正后的路由 authority）；既有 A3 /
   A3-FIX-001 / A4 全系 fresh-runner 驱动期望同步后复跑全绿。
6. ✅ **边界**（Requirement 7/10）：未修改任何 A5 scope 文档、未启动 A5
   实现；A4 WB validator economic routing 零变化（WB 候选 qualification
   scope=main，且 validator role 不经 executor scope 闸——专项测试锁定）；
   A3 formal scope boundary / A3 CLOSED 历史不重写（closure 描述的是当时
   accepted 语义，本任务是对已发现 qualification 错误的修正实现）；no push。

## 2. Confirmed Evidence（任务背景事实，全部如实采用）

- LOW routing 曾选中 qwen3:4b@custom 且 routing_applied=true（真实运行 artifact）。
- Cost Guard 正确放行 LOCAL_FREE（端点事实分类无误——问题不在 guard）。
- 真实 Hermes main-chat invocation：`hermes ... -m qwen3:4b --provider custom`
  → **HTTP 400**（qwen3:4b 不是受支持的主 API 模型——它只是 auxiliary 槽位模型：
  compression / title_generation / web_extract / summarization）。
- DeepSeek main-chat invocation 成功（deepseek-v4-flash@deepseek = 已配置主模型）。
- base_url Markdown 假设被证伪（不是端点写法问题，是模型身份不在主 API 模型集）。

## 3. Reused Contracts（复用，零复制、零发明）

| 契约 | 消费方式 |
|---|---|
| A1 model_registry `RuntimeQualification` + 新增 `scope` 词汇（main/auxiliary/unknown） | 本 fix 的资格语义载体——QUALIFIED 只声明「有 runtime evidence」，scope 声明「evidence 覆盖什么调用路径」 |
| A1 baseline registry scope 事实 | deepseek-v4-flash@deepseek=main（A2-004 证据覆盖真实 main-chat 执行）；qwen3:4b@custom=auxiliary（RW-030 probe 只覆盖 aux 槽位/本地端点）；WB 两资格化候选=main（真实 CodeBuddy CLI 主 invocation probe）；qwen2.5vl=unknown |
| A2 shadow_routing selector（现有引擎） | executor 角色主调用资格闸加在既有过滤管线 C（qualification）之后、D（经济）之前——同一 eligibility 系统，未建第二套 |
| risk_contract 角色/风险词汇 | executor = 唯一被 active routing 真实选择/改变执行的角色（scope 闸只作用于它） |
| A3 active_routing / runner / adapters / cost_guard | **零生产代码改动**（同一 selector 语义自动修正 A3 决策链） |

## 4. Implementation（实现明细）

### 4.1 model_registry.py（A1）
1. 新词汇：`QUAL_SCOPE_MAIN = "main"` / `QUAL_SCOPE_AUXILIARY = "auxiliary"` /
   `QUAL_SCOPE_UNKNOWN = "unknown"`（缺省 = unknown，fail closed）。
2. `RuntimeQualification` 新增 `scope: str = QUAL_SCOPE_UNKNOWN` 字段 +
   `__post_init__` 校验（未知值 → ValueError）。
3. 序列化：`entry_to_dict` / `entry_from_dict` 增加 qualification["scope"]
   （旧 dict 缺字段 → 缺省 unknown，向后兼容且 fail closed）。
4. 基线 scope 事实 + 每条目的 notes/注释更新（见 §3）；RW-030 证据锚点与
   observed_at 原文不改（历史证据不可变，scope 是新的解释层）。

### 4.2 shadow_routing.py（A2 selector）
1. 新排除 token：`EXCL_AUXILIARY_ONLY = "AUXILIARY_ONLY"` /
   `EXCL_MAIN_INVOCATION_UNPROVEN = "MAIN_INVOCATION_UNPROVEN"`（加入
   EXCLUSION_REASONS，decision_from_dict 校验同步接受）。
2. 过滤管线新增 **C2（executor 主调用资格）**：`role == ROLE_EXECUTOR` 时，
   usable（capability + QUALIFIED）之后还必须 `qualification.scope == main`；
   scope=auxiliary → AUXILIARY_ONLY 排除；scope 非 main（unknown）→
   MAIN_INVOCATION_UNPROVEN 排除。validator / reviewer 不经此闸。
3. 模块 docstring 同步（排除原因词汇 + executor 主调用资格规则说明）。

### 4.3 测试（Requirement 8）
- 新增聚焦回归 **16 项**：`tests/test_a3_executor_qualification_fix.py`
  （A scope 词汇/序列化/基线 scope 事实契约；B selector 矩阵——aux-only 排除
  executor / unknown-scope 排除 / aux-only 即使 FREE+LOCAL 也不进经济排序 /
  main-scope 仍选中 / capability 闸先于 scope 闸 / status 闸先于 scope 闸 /
  validator hypothetical 不扩散；C A3 决策层——基线 no-route 保留 configured /
  aux-only 池 NO_ELIGIBLE / main-scope free 仍路由；D runner 全链——aux-only 池
  configured 保留 + 零 fallback / routed 失败 FRAMEWORK_ERROR 零 fallback）。
- 既有 bug 语义测试翻转为修正后语义（这些测试原本把 qwen3-被选中锁为验收）：
  test_shadow_routing.py（helpers 默认 scope=main + LOW 基线测试改为
  AUXILIARY_ONLY 排除）、test_shadow_observation.py（LOW 基线 selected=deepseek +
  actual_vs_shadow=SAME）、test_active_routing.py（LOW 基线 no-route +
  受控 main-scope 用例保持 routed 分支全覆盖 + runner 集成 3 项改造）、
  test_task_risk_provenance.py、test_a4_workbuddy_discovery.py /
  test_a4_workbuddy_qualification.py（Hermes 选择语义同步 = qwen3 不再 eligible）。
- 既有 fresh-runner 驱动期望同步：fresh_runner_a3_validation.py /
  fresh_runner_a3_fix001_validation.py N1 改为 LOW 真实 facts no-route（configured
  deepseek 保留，精确 AAF_COST_AUTH）；fresh_runner_a3_fix001_wrapper.py 的
  FREE_PROMO fixture 显式 scope=main（该 fixture 测的是 A3 cost gate，不是 scope
  闸）；A4 qualification/second_candidate/economics/fix001/medium 驱动 LOW 场景
  Hermes stage 补精确 AAF_COST_AUTH（configured deepseek 保留语义）。

### 4.4 fresh-runner N+1（Requirement 9，全新进程）
- 新驱动 `tests/fresh_runner_a3_executor_qualification_fix_validation.py` +
  wrapper（AAF_TEST_REGISTRY_MODE = baseline | aux_sole | main_free，test-only
  fixture，production 零 hook）：
  - **N1**（LOW + 真实 baseline）：qwen3 excluded=AUXILIARY_ONLY /
    routing_applied=false / selected=deepseek-v4-flash@deepseek /
    SELECTED_NOT_FREE / configured deepseek 保留（ALLOWED_AUTHORIZED_PAID 精确
    授权）/ child 零 env 覆盖 / 全链 SUCCESS。
  - **N1b**（LOW + aux-only 受控池）：NO_ELIGIBLE / AUXILIARY_ONLY 可审计排除 /
    全链 SUCCESS。
  - **N2**（LOW + main-scope 受控 LOCAL_FREE）：仍真实 active route /
    ALLOWED_FREE 零授权零 claim / child 见 main-free/custom/本地端点 / shadow
    actual_vs_shadow=SAME / 全链 SUCCESS。
  - **N3**（LOW + main-scope routed 后 invocation 失败）：FRAMEWORK_ERROR /
    fallback_attempted=false / run=WAITING（no silent fallback）。

## 5. Requirements → Evidence 映射

| Req | 证据 |
|---|---|
| 1 定位确切资格路径 | 本报告 §1.1 + model_registry qwen3 条目注释（scope=auxiliary 根因说明） |
| 2 主调用路径证据要求 | RuntimeQualification.scope 契约 + selector C2 闸（§4.1/4.2）+ 测试 A/B |
| 3 aux-only 不 qualify | test_a3_executor_qualification_fix.py B 矩阵（AUXILIARY_ONLY / MAIN_INVOCATION_UNPROVEN 排除）+ baseline 测试 |
| 4 当前证据下 qwen3 不被选 | 单元 + runner + fresh-runner N1 全链（excluded=AUXILIARY_ONLY） |
| 5 无合格 free executor → configured 保留 / routing_applied=false / 零 fallback / Paid Guard 不变 | test C/D + fresh-runner N1/N1b + A3 SELECTED_NOT_FREE / NO_ELIGIBLE reason |
| 6 不弱化既有 checks | capability 闸先于 scope 闸、status 闸先于 scope 闸专项测试；cost gate 逻辑零改动 |
| 7 不改 A5 文档 / 不启动 A5 | 本任务零 A5 文件改动（git diff 无 docs A5 文件）；scope 文档保持 |
| 8 聚焦回归测试 | tests/test_a3_executor_qualification_fix.py 16 项（4 个验收点全覆盖） |
| 9 fresh-runner 新进程验证 | tests/fresh_runner_a3_executor_qualification_fix_validation.py 4/4 |
| 10 no push | git log 本地提交，未 push（§7） |

## 6. Test Evidence

- 定向聚焦：tests/test_a3_executor_qualification_fix.py 16 passed；
  test_shadow_routing 50 / test_shadow_observation 28 / test_active_routing 38 /
  test_task_risk_provenance / test_a4_workbuddy_*（discovery / qualification /
  second_candidate / routing / routing_fix001 / routing_medium / economics /
  economics_fix001）全绿。
- 全量 non-GUI 4-file-deselect（与既往同一排除约定：
  `--deselect tests/test_phase_e_cancel_ui_e2e.py --deselect tests/test_phase_e_e2e.py
  --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_f_e2e.py`）：
  **1832 passed / 1 skipped / 38 deselected**（HEAD f6c577d 基线 1815 + 17 精确零回归）。
- fresh-runner：新驱动 4/4；复跑 fresh_runner_a3_validation 2/2、
  fresh_runner_a3_fix001_validation 2/2、fresh_runner_a4_wb_qualification_validation
  0 failures、fresh_runner_a4_wb_second_candidate_validation 0 failures、
  fresh_runner_a4_wb_econ_validation 0 failures、
  fresh_runner_a4_wb_econ_fix001_validation 0 failures、
  fresh_runner_a4_wb_econ_medium_validation 0 failures。
- 运行时证据：.aaf/AAF-v0.5-A3-HERMES-EXECUTOR-QUALIFICATION-FIX-001/
  fresh-runner-validation/scenario_record.json（不提交）。

## 7. Unresolved Issues / 未完成项

- Unresolved Issues = None。
- 未推送（no push）；route 下游 = WorkBuddy 独立验证 + Codex APPROVE 按任务流程执行。
- 临时全量测试日志 `_full_run.log`（仓库根目录）已在提交前删除，不进入 commit。

## 8. Scope Boundary（显式 anti-pullback）

- 不实现 automatic fallback / A5（fallback / escalation / Cost Gate UX 文档与
  实现均未触碰）；不实现 A6（health / quarantine / runtime requalification /
  observation / calibration）；不进入 A4+（HIGH/CRITICAL WorkBuddy routing、
  multi-agent / Codex routing）。
- 不改 A0 Paid Guard 分类/授权逻辑（LOCAL_FREE loopback 判定与 task-scoped
  授权语义零变化——只是不再有 aux-only 候选被路由到它头上）。
- 不改 WorkBuddy validator 经济路由（A4 已关闭 scope 的行为零变化）。
- 历史 closure / 报告不可变（A2/A3/A4/A5 历史文档不重写；本报告是对已发现
  qualification 错误的修正实现记录）。
