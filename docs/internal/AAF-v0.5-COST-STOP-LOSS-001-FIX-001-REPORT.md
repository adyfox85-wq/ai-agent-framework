# AAF-v0.5-COST-STOP-LOSS-001-FIX-001 — Implementation Report

> Task: Enforce shared Hermes stage deadline across original and fallback
> invocations（修复 AAF-v0.5-COST-STOP-LOSS-001 的唯一 Codex blocker：Hermes
> 原始 invocation 与 A5 fallback 当前各自取得完整 per-attempt timeout，导致
> 整个 Hermes stage 可能超过原有 ~3600s 级问题边界）
> Executor: Hermes（AAF Executor stage）2026-09-05
> Parent: AAF-v0.5-COST-STOP-LOSS-001（37eb156a46a8ed4da69afd77749a9c839650e61c）
> Route: Hermes -> WorkBuddy -> Codex（final route acceptance = PENDING——本
> 实现 run 不自行声称 route verdicts；FRESH_RUNNER_VALIDATION_REQUIRED 已记录）

## 1. 结论（先给结论）

修复父任务 Codex REQUEST_CHANGE 的唯一 blocker：**Hermes stage 现在有一个
权威的共享绝对 stage deadline（wall-clock budget）**——original invocation 与
A5 FREE/PAID fallback 全部从**同一个**绝对 deadline 消费预算，fallback 绝不
能再重启一个完整 per-attempt timeout（HIGH/CRITICAL 理论 2400+2400=4800s
行为被消除，总 Hermes stage 墙钟有界）。

机制（三层、单一 deadline owner）：
1. **runner（deadline 唯一 owner）**：Hermes stage 首次模型 invocation 之前
   一次性写入 `AAF_HERMES_STAGE_DEADLINE = monotonic() + budget`（budget =
   `AAF_HERMES_STAGE_BUDGET` operator override 或默认 3600s——即原 ~3600s
   级无进度问题边界）；stage 结束还原。进入 fallback_runtime 绝不重算/重设
   （Requirement 7）。WorkBuddy/Codex stage 不触碰该 env。
2. **adapters.run_agent（每次 invocation 裁剪）**：每次 subprocess 创建前
   `effective_timeout = min(per_attempt_timeout, remaining_stage_budget)`
   （Requirement 4/8）——original 与每个 fallback invocation 同一公式；
   remaining ≤ 0 → subprocess.TimeoutExpired 有界早停（不 spawn child；
   分类路径 = ATTEMPT_TIMEOUT 不变）。
3. **runner 预算 gate（fallback 评估前）**：A5 fallback 层入口之前求值
   `hermes_fallback_allowed()`——remaining < 安全下限（默认 60s，
   `AAF_HERMES_STAGE_MIN_REMAINING` 可调/可归零）→ **不发起第二模型**
   （FREE 与 PAID 都被拦截——gate 在 A5 层入口之前），stage fail closed 并以
   机器可读 stop reason **STAGE_BUDGET_EXHAUSTED**（stop_loss 词汇表新成员）
   终止（stop_loss.json + stage result json 双通道）。底层失败文本原样保留，
   dirty workspace / RESUME / recovery 语义零变化。

机器可读证据：`stop_loss.json`（terminal_reason=STAGE_BUDGET_EXHAUSTED，
detail 含 remaining/min 数值）+ `hermes_result.json` stage stop_loss 引用。

**零语义放宽**：per-attempt timeout 仍是有界上限（effective = min）；429/
quota 早停、A0 Paid Guard、A3/A4 routing、A5 one-fallback / FREE-PAID policy
全部零修改（`fallback_runtime.py` / `fallback_contract.py` /
`fallback_paid_gate.py` / `workbuddy_retry.py` / `router.py` 零改动）。

## 2. 阻断发现（Codex blocker 原文要点）与修复语义

- Codex BLOCKER #1：Hermes stage 没有统一的总时限。原始 invocation 超时后，
  A5 fallback 会再次调用 `run_agent`，并重新取得完整的 per-attempt timeout——
  HIGH/CRITICAL 默认 2400s × 2 = 理论 ~4800s（还不含 fallback 决策开销），
  反而超过待解决的约 3600s 无进展等待；“one-attempt budget”只限制 fallback
  次数，未限制整个 Hermes stage 的墙钟预算。→ 本修复：共享绝对 stage
  deadline（默认 3600s）+ per-attempt 裁剪 + fallback 前预算 gate。
- Codex BLOCKER #2：现有 focused test 只验证单个 Hermes 调用获得 2400s
  timeout，没有覆盖“原始调用超时后 fallback 再次获得完整 timeout”的关键路径。
  → 本修复：新增 13 项 focused tests（stop_loss 纯函数 + adapters 裁剪 +
  真实 runner Hermes stage 集成），覆盖 Task Requirement 9 A–F 全矩阵。
- Codex 非阻断警告（本任务 Required Delta 未含，如实不扩大范围）：WorkBuddy
  terminal reason 2-vs-3 标签问题（workbuddy_retry 语义，非本 blocker）；
  Hermes timeout env 恢复不在 finally（BaseException 泄漏）——父 leg 已存在，
  非本 FIX 范围；FRESH_RUNNER_VALIDATION_REQUIRED 保持 mandatory（见 §7）。

## 3. 实现

- `ai_agent_framework/stop_loss.py`：
  - 词汇表新成员 `STOP_REASON_STAGE_BUDGET_EXHAUSTED = "STAGE_BUDGET_EXHAUSTED"`
    （∈ TERMINAL_STOP_REASONS，机器可读 terminal reason）。
  - env 常量：`AAF_HERMES_STAGE_BUDGET`（总预算，operator 逃生口）/
    `AAF_HERMES_STAGE_DEADLINE`（绝对 monotonic deadline，runner 写入）/
    `AAF_HERMES_STAGE_MIN_REMAINING`（fallback 安全下限 override）。
  - 默认：`DEFAULT_HERMES_STAGE_BUDGET = 3600.0`（原问题边界；> 全部 risk 档
    per-attempt 上限 → 单次成功 invocation 语义零变化）、
    `DEFAULT_HERMES_STAGE_MIN_REMAINING = 60.0`。
  - 纯函数：`_monotonic()`（测试可注入时钟单点）、
    `resolve_hermes_stage_budget` / `resolve_hermes_stage_min_remaining`（env
    override、非法回退默认）、`hermes_stage_deadline_value`（deadline=now+
    budget，只算一次）、`hermes_stage_remaining_seconds`（deadline-now；无
    deadline env → None = 既有语义）、`effective_attempt_timeout`（min 公式）、
    `hermes_fallback_allowed`（预算 gate，返回 allowed/remaining/min/reason）。
  - `build_stop_loss_record` 新增 `stage_budget_exhausted` 证据参数：预算耗尽
    → 记录 terminal_reason=STAGE_BUDGET_EXHAUSTED（覆盖分类；缺省 None 时
    既有 classify 路径零变化）。
- `ai_agent_framework/adapters.py`：`run_agent` 在 timeout 解析后、
  subprocess 创建前读取共享 deadline——`effective = min(per_attempt, remaining)`；
  remaining ≤ 0 → `subprocess.TimeoutExpired(agent, timeout)` 有界早停（不
  spawn；分类 = ATTEMPT_TIMEOUT）。无 deadline env → no-op（codex/workbuddy
  stage、直接调用本模块的测试零变化）。
- `ai_agent_framework/runner.py`（Hermes stage 内；非 Hermes stage 零触碰）：
  - 首次 invocation 前（现有 attempt-timeout env overlay 旁）：写入绝对
    deadline env（`hermes_stage_deadline_value()`，只一次）+ 记录旧值。
  - A5 fallback 评估**之前**：`hermes_fallback_allowed()` gate——不允许 →
    跳过整个 fallback 层（free/paid 都不评估），stderr 显式记录 suppressed
    reason，stage fail closed；允许 → 既有 fallback 逻辑原样执行。
  - stop_loss 记录构建传入 `stage_budget_exhausted` 证据。
  - Hermes stage 结束时与 attempt-timeout env 同纪律还原 deadline env
    （operator 预设值精确还原；绝不泄漏到后续 stage/调用方）。
- 零改动文件：`fallback_runtime.py`、`fallback_contract.py`、
  `fallback_paid_gate.py`、`workbuddy_retry.py`、`workbuddy_economics.py`、
  `router.py`、`active_routing.py`、`cost_guard.py`、`model_registry.py` 等。

## 4. 测试证据（Executor 实测）

Hermetic：全部 fake run_agent / fake subprocess.run / fake Popen / 注入单调
时钟（`stop_loss._monotonic` 单点 patch）——零真实 Agent CLI、零真实等待。
新增/扩展 `tests/test_stop_loss.py`（20 → 33 项；13 新增覆盖 Requirement 9
A–F 全矩阵）：

- Requirement A（original 消耗大部分预算 → fallback 只拿剩余）：
  `test_runner_shared_deadline_original_and_fallback_same_absolute_value`
  （真实 runner + 受控 registry + A5 层真实执行：两次 hermes invocation 看到
  同一绝对 deadline env `["3400","3400"]`；fallback 时剩余 = 2400−1200 =
  1200s，非完整 per-attempt budget；deadline env 不泄漏到 workbuddy/codex
  stage）+ `test_run_agent_clips_to_remaining_stage_budget`（numeric clip：
  remaining 500 → subprocess timeout 500，显式 timeout 参数同被裁剪）。
- Requirement B（original 耗尽预算 → fallback 不发起）：
  `test_runner_original_exhausts_budget_fallback_not_invoked_machine_reason`
  （hermes 恰 1 次 invocation；WAITING；零 fallback/gate/paid artifact）。
- Requirement C（original timeout + fallback 不超配置 stage 墙钟预算）：
  `test_original_timeout_plus_fallback_cannot_exceed_stage_budget`（adapters
  顺序调用：original 拿满 2400 → 剩余 0 → fallback 在 spawn 前 TimeoutExpired；
  变体：original 用 1200 → fallback 只剩 1200；每次 effective ≤ 该时刻
  remaining；累计贴住 deadline 不超）。
- Requirement D（paid fallback 同受共享 deadline 约束）：
  `test_runner_paid_fallback_obeys_same_shared_deadline_exhausted`（paid-only
  registry + exact auth：预算耗尽 → 0 次 paid invocation、gate 未运行、A0 授权
  未消费）+ `test_runner_paid_fallback_success_under_shared_deadline`（预算
  充足：paid fallback 恰一次成功，original 与 paid 两次 invocation 同一绝对
  deadline `["3400","3400"]`，SUCCESS）。
- Requirement E（成功快速 original 失败留下有效 fallback 预算）：
  `test_runner_fast_original_failure_leaves_valid_fallback_budget`（30s 级快速
  失败 → fallback 拿到 2370s 有效预算并成功，SUCCESS、无 stop_loss.json）。
- Requirement F（预算耗尽 stop reason 机器可读）：B/D1 测试断言
  `stop_loss.json` terminal_reason == `STAGE_BUDGET_EXHAUSTED` ∈
  TERMINAL_STOP_REASONS + detail 含 remaining/min 数值 + stage result json
  引用。
- 纯函数/单元：`test_shared_deadline_vocab_and_defaults`、
  `test_resolve_hermes_stage_budget_override_and_defaults`、
  `test_resolve_min_remaining_override_zero_allowed`、
  `test_shared_deadline_absolute_remaining_and_fallback_gate`（deadline 绝对
  值、remaining 单调、gate 拒绝 reason 机器可读、min=0 边界、非法 env 不 gate）、
  `test_effective_attempt_timeout_min_remaining_formula`、
  `test_run_agent_exhausted_deadline_raises_timeout_without_spawn`（≤0 → 不
  spawn、TimeoutExpired 分类 ATTEMPT_TIMEOUT 不变）。

实测结果：
- focused：`python -m pytest tests/test_stop_loss.py` → **33 passed**
  （20 既有保持 + 13 新增，零下降）。
- A5 fallback/paid/gate/contract + workbuddy_retry 回归：
  `tests/test_a5_fallback_runtime.py test_a5_paid_fallback_runtime.py
  test_a5_paid_escalation_gate.py test_a5_fallback_contract.py
  test_workbuddy_retry.py` → **352 passed, 1 skipped**（既有语义锁定：
  A5 层零改动、WorkBuddy retry 零改动）。
- runner/routing 回归：`tests/test_runner.py test_adapters.py test_router.py
  test_a4_workbuddy_routing*.py` → **154 passed**（含 Hermes stage env
  overlay/stop_loss 既有集成测试全部保持）。
- 全量 sweep（独立干净 env——本机会话 ambient 存在 AAF_HERMES_ATTEMPT_TIMEOUT
  等 operator 预设值，会触发既有 env-cleanliness 断言（test_a4_workbuddy_
  discovery），unset 后复跑）：**2274 passed, 1 skipped, 9 deselected**，零失败
  （111s；覆盖全部收集模块，含 runner/fallback/recovery/cost/A5 全组）。

## 5. 边界（不重开 / 未进入 / 未实现）

- 不扩大 scope：token billing / cost dashboard / PH-2 / PH-3 / scheduler /
  worker 系统全部未触碰（Requirement 11）。
- WorkBuddy stage 有自己的 `AAF_WORKBUDDY_*` retry/stage-budget 机制，
  本修复的共享 deadline 只作用于 Hermes executor stage（A5 fallback 属于
  Hermes stage）——两套 budget 语义分层，互不混淆。
- 无 deadline env 的调用路径（codex/workbuddy stage、直接调用
  `run_fallback_after_failure` 的既有测试）行为与修复前完全一致
  （`hermes_stage_remaining_seconds` → None → 不 gate 不裁剪）。
- Codex 非阻断警告（WorkBuddy NO_PROGRESS 标签 2-vs-3、Hermes timeout env
  finally 恢复）不在本任务 Required Delta 内，如实未扩大处理。
- 本项目文档（PROJECT_STATE.md / AAF_MASTER_BACKLOG.md 顶部 Last Updated
  链）沿用父实现 37eb156 的惯例：v0.5 途中 FIX leg 不在正文登记，route
  closure（WorkBuddy + Codex approve）时统一收口登记。

## 6. 变更清单

- `ai_agent_framework/stop_loss.py`（共享 stage deadline 策略 + 新词汇 +
  build_stop_loss_record 扩展；纯增量）
- `ai_agent_framework/adapters.py`（run_agent per-invocation min 裁剪；+14 行）
- `ai_agent_framework/runner.py`（deadline env 设置/还原 + fallback 前预算
  gate + stop-loss 记录证据；Hermes stage 内）
- `tests/test_stop_loss.py`（+13 focused tests：A–F 全矩阵 + 纯函数/裁剪单元）
- 本 REPORT（docs/internal/AAF-v0.5-COST-STOP-LOSS-001-FIX-001-REPORT.md）

EOL：python 文件与仓库一致（CRLF working copy / LF index，core.autocrlf）；
REPORT = LF。`git diff --check` 通过。PRE_ALLOWED_UNTRACKED 保留（.aaf/、
AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs）。

## 7. FRESH_RUNNER_VALIDATION_REQUIRED

runner/fallback 执行权威变更（Hermes stage env overlay 增加 deadline env +
fallback 入口预算 gate + stop-loss 新 terminal reason）→ 按 route 惯例，
**FRESH_RUNNER_VALIDATION_REQUIRED**：需独立 fresh-runner leg 在本 commit
之上复跑相关 fresh_runner_* 验证（stop-loss / A5 free / A5 paid 组）后，
route acceptance 才可收口。本实现 run 不自行声称 final closure。

## 8. 验收对照（Requirements 1-14 + Acceptance）

1. 单一权威 Hermes stage deadline/budget（首次模型 invocation 前）——
   实现 = runner 一次性写入 AAF_HERMES_STAGE_DEADLINE（§3）；测试 =
   test_shared_deadline_absolute_remaining_and_fallback_gate + runner 集成
   用例（deadline env `["3400","3400"]` 两次一致）。
2. original 与每个 fallback 从同一绝对 deadline 消费——
   test_runner_shared_deadline_original_and_fallback_same_absolute_value /
   test_runner_paid_fallback_success_under_shared_deadline。
3. fallback 前 remaining = stage_deadline − now——hermes_fallback_allowed /
   test_shared_deadline_absolute_remaining_and_fallback_gate（单调递减）。
4. fallback effective timeout 裁剪到剩余预算——adapters min 裁剪 +
   test_run_agent_clips_to_remaining_stage_budget。
5. 预算耗尽/低于安全下限 → 不发起第二模型 + 机器可读 stop reason——
   runner gate + STAGE_BUDGET_EXHAUSTED；B/D1 集成测试。
6. FREE 与 PAID 都覆盖——runner gate 位于 A5 层入口前（单点拦截两种
   fallback）；free（A/B/E）+ paid（D1/D2）测试齐全。
7. 进入 fallback_runtime 不 reset deadline——deadline env 只由 runner 设
   一次/还原；两次 invocation 同值断言；fallback_runtime.py 零改动。
8. effective = min(per_attempt, remaining)——effective_attempt_timeout 纯
   函数 + adapters 实测（500/1200/2400 数值断言）。
9. runner/integration 测试 A–F——§4 全矩阵（13 新增 focused tests）。
10. 保留：workspace changes（dirty file 保留语义测试保持）/ recovery-resume
    （test_runner_hermes_stop_loss_artifact_workspace_preserved_and_recovery
    保持通过）/ 429-quota 早停（test_stop_loss 既有用例保持）/ 无 routing
    语义变化（A3/A4/A5 回归 352+154 passed）/ FREE-PAID policy 零修改。
11. 未扩大 scope——§5。
12. focused + runner/fallback/recovery 回归——§4（33 focused / 352 / 154 /
    全量 sweep）。
13. 恰一个 FIX commit on 37eb156，未 amend、未 push——见提交说明。
14. FRESH_RUNNER_VALIDATION_REQUIRED——§7。

Acceptance 对照：original + fallback 共享一个 Hermes stage deadline ✅；
fallback 不能重启完整 timeout budget ✅（min 裁剪 + gate）；HIGH/CRITICAL
理论 2400+2400 行为消除 ✅（≤3600s 单 stage 总预算）；总 Hermes stage
墙钟有界 ✅；预算耗尽阻止后续 invocation ✅（STAGE_BUDGET_EXHAUSTED）；
free 与 paid 均覆盖 ✅；focused tests 通过 ✅（33 passed）；相关回归通过
✅（A5 组 352+1s、runner 组 154、全量 sweep）；WorkBuddy 非阻断 / Codex
APPROVE = route 阶段判定（PENDING，本 run 不超前声称）；恰一个 FIX commit
✅；no push ✅；fresh-runner validation = 独立 leg（§7）。
