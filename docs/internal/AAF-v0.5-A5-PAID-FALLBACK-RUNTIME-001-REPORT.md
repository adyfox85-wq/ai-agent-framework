# AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001 REPORT

Task: Implement one-shot authorized paid fallback runtime
Status: DELIVERED — 待 WorkBuddy 独立验证 + Codex APPROVE（A5 保持 STARTED，NOT
CLOSED / COMPLETE；REQUIRED_BEFORE_A5_CLOSE 9 项不重写）
Baseline parent: dd4e6e03c12b0918e96155b8c68cd4bc1eb330ab（no amend / no push）

## 1. 交付结论（结论先行）

在 A5-003（Paid Escalation / Cost Gate，authorization-evaluation-only，已
CLOSED/SYNCED）之上，把 **AUTHORIZED** gate 状态接入 live fallback runtime：
仅当 original invocation 以 fallback-eligible failure 失败、FREE/LOCAL_FREE
fallback 不可用（free gate 空）、contract 层存在合格 paid candidate（A1/A2 闸
已过、distinct from original）、one-attempt budget 未耗（count_used==0）、A5
Cost Gate 决策 = **AUTHORIZED**（既有 A0 Paid Guard 在准入边界按一次性语义原子
claim exact task/stage/model/provider scope —— 唯一付费授权 authority）时，
runtime 对确定性选中的 paid candidate 执行**恰一次** paid fallback invocation；
任何 BLOCKED / FAIL_CLOSED / malformed / missing / stale / mismatch 授权状态
→ **零 paid invocation**（fail closed，原始失败保留，权威证据持久化）。

一次性语义保持：FREE 与 paid fallback 共享同一 one-attempt budget（free 候选
存在时 free 优先、gate 不运行；ALLOWED_AUTHORIZED_PAID 绝不进入 FREE 路径；
A5-002 FREE 路径 / record schema / validator 零修改）。paid 成功输出只有在
权威 paid runtime audit（paid_fallback_runtime.json）闭合后才被接受（used=true）；
audit closure 失败 → 输出拒绝（attempted=true / used=false / audit_closure_error
surface）；paid invocation 自身失败 → attempted=true / used=false / 无第三模型 /
无第二 paid candidate / 原始失败保留。

## 2. 变更清单

- ai_agent_framework/fallback_runtime.py
  - A5-004 编排：run_fallback_after_failure 的 paid-consideration 分支在 gate
    AUTHORIZED 时委托 _execute_authorized_paid_fallback 执行**恰一次** paid
    fallback invocation（Requirement 5 复验 → candidate env 覆盖 → invoke →
    authoritative paid audit closure；exception-safe fail-closed 边界与 FREE
    路径 FIX-002 同型——任何 audit 异常 → attempted=true/used=false/
    audit_closure_error surface/overlay_saved 返回）。
  - 新 paid runtime audit artifact：DECISION_KIND_PAID =
    paid_fallback_runtime_audit / paid_fallback_runtime.json / AUTHORITY_PAID /
    assemble_paid_runtime_audit_record（Req 11 全字段，自包含 AUTHORIZED gate
    授权证据）/ validate_paid_fallback_runtime_record（Req 12 validator 独立
    拒绝矛盾/伪造 record）/ save/load。FREE 层 fallback_runtime.json schema +
    validator 零修改。
  - 模块 docstring / gate 相关注释同步（A5-004 段）。
- ai_agent_framework/fallback_paid_gate.py
  - AUTHORITY / evidence / gate_reason 措辞同步：gate 单元（authorization
    evaluation）自身仍零执行权威（attempted/used 恒 False、final==original）；
    AUTHORIZED = 授权证据，由 A5 paid fallback runtime 消费执行恰一次
    invocation（paid_fallback_runtime.json 另行审计）。interpret_guard /
    validate_paid_escalation_gate_record 语义零修改。
- ai_agent_framework/runner.py
  - Hermes stage 捕获 fb_outcome['paid_audit_artifact_ref'] → stage 新增
    `paid_fallback_runtime_ref`（与 fallback_runtime_ref /
    paid_escalation_gate_ref 三引用并存区分）；A5 段注释同步。
- tests/test_a5_paid_fallback_runtime.py（新增，+24 项聚焦，Req 15 全矩阵）
- tests/test_a5_paid_escalation_gate.py（3 项 live-runtime 场景随 A5-004 语义
  翻转：exact auth → 恰一次 paid invocation；gate record 层 attempted/used
  仍恒 False；BLOCKED/FAIL_CLOSED 零 invocation 语义保持；另 +1 runner paid
  failure 场景）
- tests/test_a5_fallback_runtime.py（FIX-001 拒绝路径 note 措辞同步 1 断言）
- tests/fresh_runner_a5_paid_fallback_wrapper.py（新增：pf_paid_only /
  pf_free_intact / pf_original_only registry 模式 + paid audit save 故障注入）
- tests/fresh_runner_a5_paid_fallback_validation.py（新增：fresh-runner N1–N8）
- tests/fresh_runner_a5_paid_escalation_gate_validation.py /
  fresh_runner_a5_paid_escalation_gate_fix001_validation.py /
  fresh_runner_a5_paid_escalation_gate_fix002_validation.py（N3/F3/P3/P5 期望
  同步：exact auth → AUTHORIZED → 恰一次 paid invocation）
- docs/internal/PROJECT_STATE.md（Last Updated 头记录本任务；A5 STARTED 保持）
- docs/internal/AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001-REPORT.md（本文件）

## 3. 行为语义（与既有权威关系）

- 唯一付费授权 authority = 既有 A0 Paid Guard（cost_guard.evaluate）。本任务
  零新增授权机制 / 零第二 token 格式 / 零隐式授权 / 零宽泛授权；授权消费 =
  A0 准入边界一次性原子 claim（exclusive-create marker），同一 execution 目录
  内 replay 拒绝（A0 语义零修改）；跨 task/stage/model/provider 复用被 exact
  scope 匹配 + canonical 重建校验拒绝。
- 资格判定 = fallback_contract.decide_fallback（唯一 A5 decision contract，
  复用 A2 selector → A1 registry/risk 闸，executor main-scope 保持）；本任务
  零平行 eligibility 判断（paid candidate 必须是 contract fallback candidates
  成员——复验 membership）。
- 成本闸词汇 = A3 ACTIVE_ROUTING_COST_CLASSES（FREE/LOCAL_FREE）；paid pool =
  contract candidates 中 registry cost_class 不在 FREE gate 的成员。
- A5-002 FREE fallback（fallback_runtime.json / ALLOWED_FREE-only / FIX-001
  admission fail-closed / FIX-002 audit closure 边界）行为与代码零修改。
- A3 初始 routing / A0 guard / A4 经济路由 / fallback_contract.py 零修改。
- gate 单元（fallback_paid_gate.py）语义（qualification before cost、exact
  scope、malformed/contradictory → FAIL_CLOSED、raw/source 证据可审计）零修改。

## 4. 测试与验证证据

- A5 聚焦（pytest）：
  - tests/test_a5_paid_fallback_runtime.py：24 passed（新）
  - tests/test_a5_paid_escalation_gate.py：全绿（3 项语义翻转 + 1 项新增）
  - tests/test_a5_fallback_runtime.py：全绿（A5-002 FIX-001/002 保持）
  - tests/test_a5_fallback_contract.py：全绿（contract 零修改）
- fresh-runner N+1（全新 python 进程 + 真实 runner + fake hermes.bat /
  codebuddy.bat / codex.bat 子进程）：
  - 新驱动 fresh_runner_a5_paid_fallback_validation.py：N1–N8 **8/8 FAILURES: 0**
    （N1 no auth → 零 paid / N2 wrong scope → 零 paid / N3 exact auth → 恰一次
    paid invocation + used=true/final=zzz-paid@remote-api + SUCCESS / N4 paid
    failure → 无第三模型 + WAITING / N5 audit closure 失败 → 输出拒绝 +
    FRAMEWORK_ERROR + 无 paid artifact / N6 FREE precedence / N7 无 silent
    carryover / N8 no-silent-paid 综合）；证据目录
    .aaf/AAF-v0.5-A5-PAID-FALLBACK-RUNTIME-001/fresh-runner-validation/
    （N1..N8 各含 TASK.md / out/（run.json、hermes_result.md、各 audit
    artifact）/ marker_*.txt / env probe）
  - 既有 A5-003 驱动期望同步后复跑（N3/F3/P3/P5 → 恰一次 paid invocation）：
    见 .aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001[-FIX-00X]/fresh-runner-validation/
- canonical 回归：见任务 commit narrative（分块 non-GUI 全量零失败）。

## 5. 未完成项 / 边界

- A5 保持 STARTED（NOT CLOSED / COMPLETE）——REQUIRED_BEFORE_A5_CLOSE 9 项
  不重写；正式关闭仍待 WorkBuddy 独立验证 + Codex APPROVE + Planner。
- A6（health/quarantine/requalification）、A4+（broader agent scope）显式
  outside。
- 本任务的 paid fallback 只在 Hermes executor stage（role=executor）接线；
  WorkBuddy/Codex stage 无 paid fallback 路径（不在 A5 scope）。
- 未做真实付费模型调用验证（零真实 API 花费；行为经 fake CLI 子进程 + 全量
  单测证明）——真实 paid invocation 的端到端运行需用户在真实执行中提供
  AAF_COST_AUTH 精确授权。
- WorkBuddy 独立验证、Codex APPROVE 为 Acceptance 的后续 route 环节
  （本 executor 不自行宣布）。

## 6. 范围纪律

- 无无关清理；PRE_ALLOWED_UNTRACKED（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）保留；新 commit（no amend）；no push。
