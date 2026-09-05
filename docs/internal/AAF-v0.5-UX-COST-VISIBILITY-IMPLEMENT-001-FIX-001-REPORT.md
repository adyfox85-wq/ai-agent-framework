# AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-001 — Implementation Report

> Task: Fix Cost Visibility actual invocation truth semantics
> （修复 Codex REQUEST_CHANGE 唯一 blocker：guard authorization / routing
> candidate 证据被显示成 actual invocation truth）
> Executor: Hermes（AAF Executor stage）2026-09-05
> Parent: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001（cb52abd）
> Recovery: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-001-RESUME-001
> （Hermes executor stage timeout 后恢复执行：保留现场审计 + 独立复跑验证 +
>  单一 recovery commit；本报告 §8 = timeout recovery record）
> Route: Hermes -> WorkBuddy -> Codex（final route acceptance = PENDING——本
> 实现 run 不自行声称 route verdicts；FRESH_RUNNER_VALIDATION_REQUIRED 已记录）

## 1. 结论（先给结论）

修复 Codex 已确认的唯一阻断问题：**display layer 不再把
admission/authorization/routing candidate evidence 显示为 actual invocation
truth**。显示层现在按「planned/authorized ≠ actual invocation」的 truth model
分类证据：actual 字段只由 actual invocation 证据填充；guard/routing 单独存在
时 Actual = UNKNOWN，计划/授权信息以显式 `Planned:` 标签呈现（Requirement
6/7/8/9/10）。**零 authority 变更**：`ai_agent_framework/*` 全部零修改
（router / runner / adapters / cost_guard / fallback_contract /
fallback_runtime / fallback_paid_gate / model_registry / model_observation /
active_routing / workbuddy_routing / report 保持）——不改 routing、payment、
billing、PH-2、PH-3。display-only 架构保持。

## 2. 阻断发现与 truth model（FIX 语义）

Codex blocker（原文要点）：`cost_guard.json` 不是调用完成证据——runner 先写
guard artifact（runner.py:609-615）后调用 `run_agent(...)`（runner.py:619）；
`authorization_consumed` 只在 admission boundary claim（cost_guard.py）。显示层
旧实现把 guard model/provider、`ALLOWED_AUTHORIZED_PAID -> PAID`、
`ALLOWED_FREE -> LOCAL_FREE` 直接当作 actual 显示；测试也固定了该错误预期。

FIX-001 证据分类（bridge/cost_visibility.py 模块 docstring + 代码实现）：

| 证据类 | 内容 | 可填充 |
|---|---|---|
| planned / authorized | cost_guard decision+model（准入镜像）、A3/A4 routing_applied+routed_model（候选） | 绝不进入 actual；以显式 "Planned: ..." 标签呈现（含 AUTHORIZED token） |
| actual invocation（Hermes original） | `<hermes_result.md>` valid（非空且不以 FRAMEWORK_ERROR 开头——与 runner `_result_is_valid` 同语义：run_agent 真实返回输出） | Actual Model / Provider / cost class（guard decision 仅在 invocation 已证时允许把已执行 model 的 cost 分类映射为 PAID/LOCAL_FREE） |
| actual invocation（fallback） | paid_fallback_runtime.json（paid invocation 真实发生后才持久化，attempted 恒真）；fallback_runtime.json used=true（free invocation 发生且被接受） | USED_PAID / USED_FREE + A5 final actual model |
| final / fallback outcome | gate AUTHORIZED 无 paid runtime -> NOT_USED（授权 != 执行，绝不 USED_PAID） | fallback 列 |
| BLOCKED | 仅 guard BLOCKED_COST_APPROVAL（权威阻断证据，Hermes 未执行） | Cost Class = BLOCKED（Requirement 15） |
| 缺失 / 损坏 | 任一 evidence 缺失/损坏 | UNKNOWN / NOT_USED，fail-soft 不崩溃 |

- actual model/provider 只由 post-invocation 证据填充：A5 final actual ->
  observation（<agent>_result.md valid 时）-> 否则 UNKNOWN；**guard model /
  routing routed_model 绝不进入 actual model/provider**（Requirement 5/8/12）。
- WorkBuddy / Codex 应用同一 truth rule（Requirement 13）：routing winner /
  observation 单独存在（workbuddy_result.md / codex_result.md 未证）-> Actual
  UNKNOWN + Planned 标签；invocation 已证后才显示 routed model / obs / FREE。
- guard ALLOWED_AUTHORIZED_PAID 单独存在绝不渲染 PAID（Requirement 6/18-A）；
  guard ALLOWED_FREE 单独存在绝不渲染 FREE/LOCAL_FREE（Requirement 7/18-B）；
  routing candidate 单独存在绝不渲染 actual model/cost（Requirement 8/18-C）。
- 语义不变项：BLOCKED 只来自权威 guard 阻断（Requirement 15）；gate AUTHORIZED
  无执行证据不 USED_PAID（Requirement 12/14/18-G）；fallback USED_* 需真实
  fallback invocation（Requirement 14/18-H/I）；缺失/损坏 artifact fail-soft
  （Requirement 16/17）。

## 3. 实现（最小 UI 变更）

- `bridge/cost_visibility.py`：
  - 新增 actual-invocation 证据判定：`read_result_md`（只读
    `<agent>_result.md` 头部，fail-soft）+ `_result_md_is_valid`（与 runner
    `_result_is_valid` 同语义）。
  - `CostRow` 新增 `planned: str = ""` 字段（planned/authorized compact 文本，
    如 `deepseek-v4-flash / PAID / AUTHORIZED`、`qwen3:4b / LOCAL_FREE /
    ALLOWED_FREE`、`hy4-preview / FREE / ROUTED (free promo)`）；仅 actual 不
    可证且存在 guard/routing 证据时出现。
  - `derive_hermes_row` / `derive_workbuddy_row` / `derive_codex_row` 支持
    `result_md` 注入（未注入时从 output_dir 只读加载），actual model/provider/
    cost class 全部以 `result_valid`（invocation 已证）为门槛；guard/routing
    移入 planned 文本。
  - `_hermes_detail` reason 语义收紧（actual PAID detail =
    "authorized paid invocation"——仅在 invocation 已证时出现；guard 单独存在时
    不再生成 "explicitly authorized paid" 等误导 detail）。
  - `render_row_line` 在 planned 存在时附加 `| Planned: ...`（显式标签）。
- `bridge/status_window.py`：`_render_cost_rows` 灰字行支持 planned——actual 不
  可证时以 "Planned: ..." 前缀标签显示，与 actual 列（主行）视觉区分；
  actual 可证时维持既有 detail 渲染。改动最小（无新 dashboard / 无 layout
  重构）；bridge/main.py 零修改。

## 4. 测试证据（Executor 实测）

- 新增/改写聚焦测试 `tests/test_cost_visibility.py` **49 passed**（FIX-001
  Requirement 18 A–K 全矩阵）：
  - A guard AUTH_PAID 无 invocation -> UNKNOWN not PAID（含 FRAMEWORK_ERROR
    result 边界 + Planned 标签断言）
  - B guard ALLOWED_FREE 无 invocation -> UNKNOWN not FREE/LOCAL_FREE
  - C routing candidate（A3 hermes + A4 workbuddy）无 invocation -> UNKNOWN
  - D proven actual FREE invocation -> FREE（hermes obs + result；workbuddy
    free-promo + result）
  - E proven actual LOCAL_FREE invocation -> LOCAL_FREE（guard ALLOWED_FREE +
    result / obs 端点 + result / A3 registry + result）
  - F proven actual PAID invocation -> PAID（guard AUTH_PAID + result +
    observation）
  - G gate AUTHORIZED 无 paid runtime -> 不 USED_PAID（含 guard 存在时仍不
    PAID）
  - H paid fallback used -> USED_PAID / attempted-not-used -> FAILED
  - I free fallback used -> USED_FREE
  - J 缺失/ambiguous evidence -> UNKNOWN（含 observation 单独存在不制造 actual
    model 的防幻影断言）
  - K completed-task reopen 同 truth（guard-only 目录 reopen 保持 UNKNOWN +
    planned；完整目录 reopen 保持 actual PAID）
  - 另含：guard BLOCKED + observation 存在时 model 仍 UNKNOWN（blocked 防幻影）/
    gate BLOCKED 不误标 cost BLOCKED / fail-soft 矩阵 / 只读零突变 / 无
    subprocess·os.environ·guard 决策 import 静态锁定 / 词汇闭集 / 行序确定性 /
    Planned 渲染行格式。
- `tests/test_status_window.py`（完成态 fixture 补真实 `<agent>_result.md`
  证据——guard 单独存在不再产生 actual PAID）**53 passed**：完成态 reopen
  snapshot（guard + valid result -> actual PAID deepseek-v4-flash / wb·codex
  UNKNOWN）/ missing·corrupt artifact -> UNKNOWN 不崩溃 / no-task cost_rows 空 /
  真实 Tk 渲染（Cost / Model 标题、Hermes PAID 行、detail "authorized paid
  invocation"）/ PENDING future stage 行隐藏。合计聚焦 = 102 passed。
- 回归（Req 22/23）：Bridge/status/recovery 相关 10 文件 **173 passed**；分块
  全量 non-GUI 4-e2e-deselect **2198 passed / 1 skipped / 零失败**（616+568+
  551+463；单进程整跑命中既有 RW-029 Windows 0x80000003 GC 期环境 flake——
  按项目惯例分块隔离复跑全绿）。
- 真实运行 smoke（.aaf/AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001 自身 artifact）：
  hermes 行 = `PAID deepseek-v4-flash (deepseek)` detail「authorized paid
  invocation」（guard AUTH_PAID + valid hermes_result.md = invocation 已证）；
  构造 guard-only 目录（无 result.md）= Actual UNKNOWN + `Planned:
  deepseek-v4-flash / PAID / AUTHORIZED`（授权≠执行，诚实显示）。

## 5. 边界（不重开 / 未进入 / 未实现）

- 未实现 PH-2 concurrency / PH-3 / A6 / A4+；未构建 billing ledger / token
  accounting / dashboard platform / budget management / 新 payment
  authorization / model marketplace / 图形化 Cost Gate UX（frozen MVP
  non-MVP 列表保持）。
- 未改动：`ai_agent_framework/*` 全部模块（零 diff——零 authority 变更）；
  frozen MVP / PH-1 CLOSED / PH-2·PH-3 NOT STARTED 边界保持；routing /
  payment / fallback / Paid Guard 行为零变化。
- 显示层诚实局限保持：guard/routing 单独存在不再显示 actual model/cost——
  这是 FIX 的目标语义（planned/authorized ≠ actual invoked），非缺陷。

## 6. 变更清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `bridge/cost_visibility.py` | 修改 | truth-model 重写：actual-invocation 证据门槛 + planned 字段 + <agent>_result.md 判定 |
| `bridge/status_window.py` | 修改 | _render_cost_rows Planned 标签渲染（灰字显式区分 actual） |
| `tests/test_cost_visibility.py` | 修改 | 49 项（FIX-001 Req 18 A–K 矩阵 + 防幻影 + planned + fail-soft + 只读锁定） |
| `tests/test_status_window.py` | 修改 | fixture 补 result.md 证据 + detail 断言更新（53 passed） |
| `docs/internal/AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-001-REPORT.md` | 新增 | 本报告 |
| `docs/internal/PROJECT_STATE.md` | 修改 | Last Updated 新条目 + v0.5 段 FIX-001 条目块 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | Last Updated 新条目 |

- git：parent = cb52abdb9c944ea80812ac76856c912a51980bdb（local HEAD）；
  单一 FIX commit，未 amend，未 push；`git diff --check` 通过。
- PRE_ALLOWED_UNTRACKED 保留（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）；编辑脚本在系统 Temp / .aaf（不入 commit）。

## 7. FRESH_RUNNER_VALIDATION_REQUIRED（Requirement 24）

本任务修改 Bridge/runtime observability 的显示 truth 语义（actual = 仅 actual
invocation 证据；guard/routing 单独存在 -> UNKNOWN + Planned）。**须由独立
fresh-runner leg 验证**（全新进程、真实 Bridge/status 上下文，重点）：
1. 全新进程下状态窗口 Cost/Model 区从真实任务 dir artifact 正确重建显示——
   guard-only / crashed（FRAMEWORK_ERROR result）任务不显示 actual model/cost；
2. 已完成任务（含 valid result.md）reopen 显示 actual（PAID/LOCAL_FREE 等）；
3. 缺失/损坏 artifact 的既有任务 dir 不崩溃、区内容诚实 UNKNOWN；
4. 任务执行中 artifact 落盘后 UI ≤1s 更新、不显示 unproven actual；
5. 既有 recovery / reopen / single-launcher 行为零回归。

**本实现 run 不自行声称 final closure**——Unresolved Issues 中唯一非空项 =
required fresh-runner closure + WorkBuddy 独立验证 + Codex review（route
PENDING，不超前声称）。


## 8. Timeout Recovery & Resume（RESUME-001 追加记录，2026-09-05）

- **Timeout 事实**：本 FIX-001 的 Hermes executor stage 在 2026-09-05
  16:01:35 → 17:01:38 触发框架 `TimeoutExpired`（3600.89s），**未创建 commit**；
  working tree 全部未提交工作原样保留 = 6 个已跟踪修改（bridge/cost_visibility.py、
  bridge/status_window.py、tests/test_cost_visibility.py、tests/test_status_window.py、
  docs/internal/PROJECT_STATE.md、docs/internal/AAF_MASTER_BACKLOG.md）+ 本报告
  （untracked）。以上 §2–§7 内容与实现/测试/docs 更新全部为 timeout 前已完成的工作，
  非本恢复任务重做。
- **恢复审计（RESUME-001）**：git status/diff 全量盘点 + 父 Codex REQUEST_CHANGE
  阻断发现逐条比对 + FIX-001 snapshot/REPORT/timeout artifact（.aaf/…FIX-001/run.json、
  hermes_result.json = stage_elapsed_seconds 3600.891）核对；
  **recovery assessment = PARTIALLY_FIXED**——原 Codex blocker 的修复在 working tree
  已实质实现且语义正确（evidence classification / result_valid 门槛 / planned 标签 /
  A–K 测试矩阵），但缺少独立验证、timeout 恢复记录与 commit。
- **本恢复任务补全（最小增量）**：(a) 保留并审计全部既有正确工作，零重做、零丢弃；
  (b) 独立复跑三级测试（见下）；(c) 本 §8 记录；(d) PROJECT_STATE.md /
  AAF_MASTER_BACKLOG.md Last Updated 补 RESUME-001 条目；(e) 单一 recovery commit
  （parent = cb52abd，未 amend，未 push）。
- **测试独立复跑（RESUME-001 实测，2026-09-05）**：聚焦 102 passed（
  tests/test_cost_visibility.py 49 + tests/test_status_window.py 53，1.34s）；
  Bridge/status/recovery 10 文件 173 passed（26.32s）；分块全量 non-GUI（4 个
  *_e2e.py 排除，4 块 689+508+508+493）**2198 passed / 1 skipped / 9 deselected
  （gui_e2e marker）零失败**——与原 §4 记录数字一致（独立分块分布不同但总和相同，
  交叉验证 suite 无遗漏）。`git diff --check` 通过。
- **遗留（如实）**：FRESH_RUNNER_VALIDATION_REQUIRED（§7）保持 mandatory 且未执行；
  WorkBuddy 独立验证 + Codex review = route PENDING——本实现/恢复 run 不自行声称
  route verdicts；无其他 unresolved implementation blocker。
