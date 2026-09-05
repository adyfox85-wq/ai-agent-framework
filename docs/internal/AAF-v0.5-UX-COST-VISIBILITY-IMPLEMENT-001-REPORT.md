# AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001 — Implementation Report

## 1. 结论（先给结论）

在既有 Bridge 状态窗口内新增最小 **display-only Cost / Model Visibility**：
用户无需打开 REPORT.md 即可直观看到每个已实际执行 route stage 的 Role/Stage、
actual Model、Provider、Cost Class、Fallback 状态与（有证据时）一行短 detail。

- 概念流 = 既有 authoritative runtime artifacts -> display-only 归一化 view
  （新模块 `bridge/cost_visibility.py`，纯函数只读）-> 既有 Bridge 状态窗口
  （`bridge/status_window.py` 渲染）。
- **零 authority 变更**：`ai_agent_framework/*` 全部零修改（router / runner /
  adapters / cost_guard / fallback_contract / fallback_runtime /
  fallback_paid_gate / model_registry / model_observation / active_routing /
  workbuddy_routing / report 保持）；不建 dashboard / billing / payment /
  routing / qualification 新系统；无 PH-2 / PH-3 实现。
- 显示词汇 = 任务与审计定义的闭集（Cost Class：FREE / LOCAL_FREE / PAID /
  UNKNOWN / BLOCKED；Fallback：NOT_USED / USED_FREE / USED_PAID / FAILED /
  UNKNOWN）；model/provider 缺失显示 "—"（既有窗口约定）。
- 权威规则 = **可证则证、不可证则 UNKNOWN，绝不猜测**（详见 §5 UI 字段语义）。
- Final route acceptance = **PENDING**（WorkBuddy 独立验证 + Codex review 按
  route 阶段执行，本实现 run 不超前声称 route verdicts）。
- **FRESH_RUNNER_VALIDATION_REQUIRED 已记录**（Req 25，见 §8）——本 run
  不自行声称 final closure。

## 2. 依据（只读审计）

- `AAF-v0.5-UX-COST-VISIBILITY-AUDIT-001`（SUCCESS）：唯一决策 =
  `COST_VISIBILITY_UI_READY_WITH_EXISTING_EVIDENCE`——每显示字段均有既有权威
  artifact；audit 的「最小实施计划」（§十）即本实现方案骨架。
- 字段 -> 权威源映射（audit §三/§四，全部为 task output_dir 内既有 artifact）：
  model_observation.json（post-hoc actual model/provider）、cost_guard.json
  （A0 准入镜像 + 阻断判定）、active_routing.json（A3 Hermes FREE/LOCAL_FREE
  active routing）、workbuddy_active_routing.json（A4 WorkBuddy 经济路由 +
  reason + economic facts）、fallback_runtime.json / paid_escalation_gate.json /
  paid_fallback_runtime.json（A5 三件套，仅真实 Hermes 失败路径产生）。

## 3. 设计（最小 display-only join + 复用纪律）

新模块 `bridge/cost_visibility.py`（~600 行，纯函数）：

- `read_json` / `load_observation`：fail-soft 只读（缺失/损坏/非 dict ->
  None，绝不抛异常；Req 14/15/I）。
- 每 route agent 一个纯 derive 函数（`derive_hermes_row` /
  `derive_workbuddy_row` / `derive_codex_row`；artifact 可注入 -> 测试确定性），
  产出 `CostRow{agent, model, provider, cost_class, fallback, detail}`。
- `build_cost_rows(output_dir, route_agents)`：按 ROUTE_AGENTS 固定序
  （hermes / workbuddy / codex）产出显示行；每行内部 fail-soft。
- 显示归一化规则（audit §五映射，逐 token 白名单回显；无推断）：
  - **Hermes cost**：paid_fallback_runtime 存在 -> PAID（真实 paid-class
    invocation 已执行）；guard decision = BLOCKED_COST_APPROVAL -> BLOCKED /
    ALLOWED_AUTHORIZED_PAID（+matched+consumed）-> PAID / ALLOWED_FREE ->
    LOCAL_FREE；无 guard 时 A5 free-fallback used=true -> LOCAL_FREE（最终
    actual = A0 ALLOWED_FREE 端点证据）> A3 routing_applied=true -> A1
    registry label（FREE / LOCAL_FREE；FREE_PROMO 归一 FREE）> observation
    LOCAL_FREE（端点证据）> UNKNOWN。
  - **Hermes model/provider**：A5 paid/免费兜底 used=true 的 final actual ->
    observation（post-hoc，env overlay 还原前观测 = final actual）-> guard
    （pre-invocation 准入镜像）-> A3 routed -> "—"。
  - **Hermes fallback**：fb_paid（used -> USED_PAID；否则 FAILED）> gate
    （AUTHORIZED 无 paid runtime 证据 -> NOT_USED + detail「not USED_PAID」=
    Req 12；BLOCKED / FAIL_CLOSED -> FAILED）> fb_free（used -> USED_FREE；
    否则 FAILED）> 无 A5 artifact -> NOT_USED。
  - **WorkBuddy model**：A4 routing_applied=true -> routed_model（精确
    --model）；否则 observation（CodeBuddy CLI 通常不可观测 -> "—"）。
    provider：仅 observation 有证据时显示。
  - **WorkBuddy cost**：仅 A4 权威可证 FREE —— routing_applied=true **且**
    routed winner 的 economic fact `cheapness_rank==0` +
    `promotion_status=="free"`（RANK_AUTHORITATIVE_CHEAP）-> FREE（free promo
    附注）；**其余一律 UNKNOWN**——LOW/MEDIUM economic routing 存在绝不等于
    FREE（Req 9）；WorkBuddy 无 paid gate/guard -> 永无 BLOCKED/PAID 声称。
  - **Codex model/provider**：仅 observation（config 证据）回显；cost 恒
    UNKNOWN；fallback = 架构性 NOT_USED（AAF 无 Codex 模型级 fallback）。
- 绝无模型名推断（代码中无任何 model-name 解析）；display 层不 import
  subprocess / os.environ / guard 决策代码（测试 K 静态锁定）。

`bridge/status_window.py`（既有窗口，改动最小）：

- `StatusSnapshot` 新增 `cost_rows: list`（默认 []；未知 provider 兜底快照
  不受影响）。
- `collect_status` 复用既有 `ref.output_dir` + `route` + `strip`，调
  `_cost_rows_for`（内部 `build_cost_rows` + fail-soft）；**只显示已开始 / 已
  完成 stage 或已有可证 evidence 的 agent 行**（Req 17：不把 unproven future
  selection 显示成 actual）。
- `_build_ui`：Stage Strip 下方新增紧凑 Cost / Model 区（header + 最多 3 对
  行/灰字 detail 标签；无行/无任务时整区隐藏）；`_render_cost_rows` 每秒随
  既有 1s 刷新更新（Req 17「evidence 可用即更新」；artifact 落盘后 ≤1s 可见）。
- 渲染 = 每 agent 一行 `Agent | Cost Class | model (provider)`；fallback !=
  NOT_USED 或存在短 reason 时附加一行灰色小字 detail（Req 15/16 紧凑）。
- 窗口/终端 reopen 路径零改动：collect_status 每次从 output_dir 持久化
  artifact 重建 -> 完成态任务 reopen 自动重构 Cost/Model 显示（Req 18）。
- Recovery / single-launcher / Paid Guard / fallback 语义零触碰（Req 19/20/21）。

`bridge/main.py` 零修改（collect_status 签名不变）。

## 4. 测试证据（Executor 实测）

- 新增聚焦测试 `tests/test_cost_visibility.py` **32 passed**（Req 22 A–K 全
  矩阵 + 词汇闭集 + 渲染行格式 + 行序确定性）：
  A proven FREE -> FREE（A4 free-promo 权威路径 / registry 回显）；B proven
  LOCAL_FREE -> LOCAL_FREE（guard ALLOWED_FREE / observation 端点 / A3 registry）；
  C proven PAID -> PAID（guard ALLOWED_AUTHORIZED_PAID / paid runtime）；
  D 无/歧义证据 -> UNKNOWN（三 agent 全空 / WorkBuddy Auto / 无授权
  PAID_OR_UNKNOWN 不猜）；E BLOCKED 仅权威时（guard BLOCKED -> BLOCKED；
  gate BLOCKED 单独不把 cost 误标 BLOCKED）；F free fallback -> USED_FREE
  （含 cost=LOCAL_FREE）；G 真实授权付费兜底 -> USED_PAID；H gate AUTHORIZED
  无 invocation -> 绝不 USED_PAID（= NOT_USED + detail）；I missing/corrupt/
  wrong-type artifact -> UNKNOWN 不崩溃（含 build 永不 raise）；J reopen 两次
  读取确定性重建 + row_visible 过滤未开始 stage；K 只读——多次 build 后目录
  文件字节零变化/零新文件 + display 模块无 subprocess/os.environ/guard 决策
  import。
- `tests/test_status_window.py` 新增 **5 项**（headless + 真实 Tk）：完成态
  reopen snapshot 重建（Hermes PAID / WorkBuddy UNKNOWN / Codex UNKNOWN）；
  missing/corrupt artifact -> UNKNOWN 行不崩溃；无任务 -> cost_rows 空；
  真实 Tk 渲染（Cost / Model 标题、Hermes 行文本、detail）；PENDING future
  stage 行隐藏（已开始 stage 诚实 UNKNOWN）。文件合计 53 passed。
- Bridge/status/recovery 回归（Req 23）：`test_status_window.py +
  test_bridge_ui_headless.py + test_bridge_state_recovery.py +
  test_bridge_state_recovery_exited_window.py + test_bridge_launcher.py +
  test_bridge_tray.py + test_bridge_config.py + test_bridge_task_io.py +
  test_bridge_handoff.py + test_phase_e_cancel_ui.py` =
  **173 passed**（26.12s）。
- 更宽回归（Req 24）：分块全量 non-GUI（4 e2e 文件按项目固定口径排除）
  = **2181 passed / 1 skipped / 零失败**（四块：689 + 491 + 508（9
  gui_e2e-deselected）+ 493（1 skipped））。注：单进程整跑在该 Windows 环境
  触发既有 RW-029（0x80000003 fatal exception，GC 期崩溃于
  test_phase_e_core.py）——项目既有环境 flake，与本变更无关；按项目惯例
  （分块隔离）复跑全绿。
- 真实运行证据 smoke：当前任务 dir `.aaf/AAF-v0.5-UX-COST-VISIBILITY-
  IMPLEMENT-001/`（本次执行自身的真实 artifact）-> hermes 行 =
  `PAID deepseek-v4-flash (deepseek)` detail「explicitly authorized paid」
  （guard ALLOWED_AUTHORIZED_PAID + matched + consumed 权威证据）；workbuddy
  / codex 行 = UNKNOWN（尚无证据，诚实显示）。
- 测试命令与基线：本变更前 HEAD = 02e1b11（docs-only 基线，无本特性代码）；
  新增 37 项测试全部通过；既有测试零失败（分块全量 2181 = 全 test_*.py
  除 4 个 e2e 文件外的完整集合）。

## 5. UI 字段语义与权威规则（Req 26 —— durable documentation）

状态窗口新增「Cost / Model」区（display-only；Stage Strip 下方）：

| 字段 | 值域 | 语义与权威规则 |
|---|---|---|
| Role / Stage | Hermes / WorkBuddy / Codex | route.json agents（route 内已开始 stage 才显示行） |
| Actual Model | model id 或 "—" | 最强可证证据：A5 兜底 final actual -> model_observation（post-hoc actual）-> guard 镜像 -> A4/A3 路由决策 model -> Codex config 证据；无证据 "—" |
| Provider | provider 或 "—" | observation/guard 有证据才显示（WorkBuddy/Codex 通常不可观测 -> "—"） |
| Cost Class | FREE / LOCAL_FREE / PAID / UNKNOWN / BLOCKED | 只按 artifact token 白名单回显：BLOCKED <- guard BLOCKED_COST_APPROVAL（权威阻断）；LOCAL_FREE <- guard ALLOWED_FREE / observation·registry LOCAL_FREE 端点证据 / A5 免费兜底 accepted；FREE <- A1 registry FREE 条目被 A3 选中使用 或 A4 权威 free-promo（rank 0 + promotion_status=free）被路由执行；PAID <- guard ALLOWED_AUTHORIZED_PAID（matched+consumed）或真实 paid-class invocation 审计（paid_fallback_runtime）；UNKNOWN <- 其余一切（observation UNKNOWN / 无 guard 的 PAID_OR_UNKNOWN / discovery UNAVAILABLE / gate BLOCKED 不覆盖原 invocation 证据 / 缺 artifact） |
| Fallback | NOT_USED / USED_FREE / USED_PAID / FAILED / UNKNOWN | A5 artifact 驱动：paid runtime used -> USED_PAID；free runtime used -> USED_FREE；attempted-not-used / gate BLOCKED·FAIL_CLOSED / paid invocation 失败 -> FAILED；gate AUTHORIZED 但无执行证据 -> NOT_USED（**授权 != 执行**，绝不 USED_PAID）；无 A5 artifact -> NOT_USED；WorkBuddy/Codex 架构性 NOT_USED |
| detail（一行短） | 可选 | fallback 上下文（original <model> failed → free/paid fallback ... used / blocked）或短 reason（explicitly authorized paid / local free candidate / qualified free candidate / blocked: cost approval required / no proven free evidence）；仅在有可说明证据时出现 |

**权威规则（hard rule）**：
1. **UNKNOWN 而非猜测**：无法由既有 artifact 证明的 cost class / model /
   provider 一律 UNKNOWN / "—"；绝不从模型名推断 FREE/PAID（Req 2），绝不把
   未验证的远程模型当 FREE（A0 无远程 FREE 权威语义沿袭）。
2. **model_observation.json 不是唯一经济权威**（Req 3/4）：guard decision、
   A3/A4 routing record、A5 fallback/paid 审计与 observation join 后取最强
   可证证据；observation 单独为 UNKNOWN 时不覆盖更强的 routing/fallback/
   guard 证据，也不被当作 FREE/PAID 依据。
3. **零第二经济权威**：本层只读回显既有 artifact token；不新增任何
   routing/payment/billing 系统、不写任何 artifact、不调用任何决策代码
   （测试 K 锁定）。
4. **paid authorization ≠ paid invocation**（Req 12）：显示 USED_PAID /
   cost PAID 的唯一执行证据 = paid_fallback_runtime.json（真实 paid-class
   invocation 审计）或 guard ALLOWED_AUTHORIZED_PAID + consumed（准入即消费 =
   该 invocation 已被放行执行）；gate AUTHORIZED 单独存在（无执行审计）绝不
   显示 USED_PAID。
5. **BLOCKED 只来自权威阻断证据**（Req 13）：guard BLOCKED_COST_APPROVAL
   （Hermes 未执行）；paid gate BLOCKED / FAIL_CLOSED 显示在 fallback 列
   （FAILED）+ detail，不把原 invocation 的 cost 误标 BLOCKED。
6. **缺失/损坏 optional artifact -> UNKNOWN / NOT_USED，不崩溃**（Req
   14/15/I）：既有状态窗口在任何经济 artifact 缺失时保持可用。
7. **不显示 unproven future 选择**（Req 17）：仅已开始 stage / 已有 evidence
   的 agent 显示行；行内容随 artifact 落盘在 ≤1s 刷新内更新。

## 6. 边界（不重开 / 未进入 / 未实现）

- 未实现 PH-2 concurrency（Req 20 保持 single-launcher）、PH-3、A6、A4+。
- 未构建：billing ledger / token accounting / dashboard platform / budget
  management / 新 payment authorization / model marketplace / 图形化 Cost
  Gate UX（frozen MVP non-MVP 列表保持）。
- 未改动：`ai_agent_framework/*` 全部模块（零 diff）；frozen MVP / PH-1
  CLOSED / PH-2·PH-3 NOT STARTED 边界保持；post-freeze opt-in policy 不变。
- 显示层诚实局限（既有运行时真实限制，非 UI 缺陷）：Hermes 远程主模型
  cost=UNKNOWN（无元数据暴露，正常时由 guard 决定 PAID/BLOCKED）；WorkBuddy
  Auto 保留 / Codex server-side 时 actual model 不可观测 -> "—"；Codex cost
  恒 UNKNOWN（CLI/config 零成本元数据）。

## 7. 变更清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `bridge/cost_visibility.py` | 新增 | display-only join + 归一化层（CostRow / derive_* / build_cost_rows / row_visible / render_row_line） |
| `bridge/status_window.py` | 修改 | StatusSnapshot.cost_rows + collect_status join + Cost / Model 区构建/渲染（~+130 行） |
| `tests/test_cost_visibility.py` | 新增 | 32 项聚焦测试（Req 22 A–K + 词汇/渲染/只读锁定） |
| `tests/test_status_window.py` | 修改 | +5 项（snapshot reopen / missing artifact / no-task / 真实 Tk 渲染 / pending 隐藏） |
| `docs/internal/AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-REPORT.md` | 新增 | 本报告（含 UI 字段语义 §5 与 FRESH_RUNNER_VALIDATION_REQUIRED §8） |
| `docs/internal/PROJECT_STATE.md` | 修改 | Last Updated 新条目 + v0.5 段「Bridge Cost / Model Visibility」条目块 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | Last Updated 新条目 |

- git：`main == origin/main == 02e1b112d53809d5fc757f6b041e6dca6703a655`
  （执行起点）；单一实现 commit，未 amend，未 push；`git diff --check` 通过。
- PRE_ALLOWED_UNTRACKED 保留（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）；编辑脚本/临时 smoke 文件在系统 Temp
  （非仓库内），不进入 commit。

## 8. FRESH_RUNNER_VALIDATION_REQUIRED（Req 25）

本任务修改 Bridge/runtime 可观测性与 persisted-state 重建（状态窗口
Cost/Model 区从 output_dir 既有 artifact 重建显示）。**须由独立 fresh-runner
leg 验证**（全新进程、真实 Bridge/status 上下文，重点）：
1. 全新进程下状态窗口 Cost/Model 区从真实任务 dir artifact 正确重建显示；
2. 缺失/损坏 artifact 的既有任务 dir 不崩溃、区内容诚实 UNKNOWN；
3. 任务执行中 artifact 落盘后 UI ≤1s 更新、不显示 unproven future stage；
4. 完成态任务 reopen（terminal 恢复）重构最终 Cost/Model 显示；
5. 既有 recovery / reopen / single-launcher 行为零回归。

**本实现 run 不自行声称 final closure**——Unresolved Issues 中唯一非空项 =
required fresh-runner closure（见 §9）。

## 9. Unresolved Issues

- executor-side：无实现 blocker。唯一待办 = 上述 fresh-runner 独立验证
  （FRESH_RUNNER_VALIDATION_REQUIRED，按 route 阶段执行）+ WorkBuddy 独立
  验证 + Codex review（route PENDING，不超前声称）。
