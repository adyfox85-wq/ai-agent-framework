# AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-002 — Implementation Report

> Task: Validate paid fallback evidence before displaying actual paid usage
> （修复 Codex 确认的唯一剩余 blocker：损坏/字段不完整/非权威 paid fallback
> artifact 不能被 Cost Visibility 当成真实 paid invocation evidence）
> Executor: Hermes（AAF Executor stage）2026-09-05
> Parent: AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-001-RESUME-001（68cbf6a）
> Route: Hermes -> WorkBuddy -> Codex（final route acceptance = PENDING——本
> 实现 run 不自行声称 route verdicts；FRESH_RUNNER_VALIDATION_REQUIRED 已记录）

## 1. 结论（先给结论）

修复父 leg（FIX-001-RESUME-001）Codex REQUEST_CHANGE 确认的唯一剩余 blocker：
**display 层不再把「fb_paid 存在」当作真实 paid invocation evidence**。损坏、
字段不完整或不符合权威 schema 的 paid fallback artifact（`{}`、缺 required
字段、wrong decision_kind、`fallback_attempted=false`、矛盾字段、其他 schema
违例）一律 fail-soft 降级为 UNKNOWN / 无 actual paid usage，绝不产生 PAID /
USED_PAID；只有经既有权威 validator
（`ai_agent_framework.fallback_runtime.validate_paid_fallback_runtime_record`，
fail-closed）接受的 schema-valid authoritative record 才渲染 PAID / USED_PAID
/ FAILED（attempted-not-used）。**零 authority 变更**：`ai_agent_framework/*`
全部零修改（router / runner / adapters / cost_guard / fallback_contract /
fallback_runtime / fallback_paid_gate / model_registry / model_observation /
active_routing / workbuddy_routing / report 保持）——不改 routing、payment、
billing；不扩展 PH-2、PH-3 或新 cost authority。display-only 架构保持。

## 2. 阻断发现（Codex blocker 原文要点）与修复语义

- Codex：`bridge/cost_visibility.py` 多处仅以 `fb_paid is not None` 判断真实
  paid invocation；`read_json()` 对 `{}` 或字段不完整但合法的 JSON 返回 dict，
  实现未验证 `decision_kind == "paid_fallback_runtime_audit"`、
  `fallback_attempted is True`，也未调用既有
  `validate_paid_fallback_runtime_record()`。
- Codex 探针（修复前）：`derive_hermes_row(fb_paid={})` -> `cost_class='PAID'`,
  `fallback='FAILED'`；`fb_paid={'fallback_attempted': False, 'fallback_used':
  False}` -> 同样 `PAID`。权威 schema（fallback_runtime.py:1210 validator
  不变量）明确要求该 artifact 的 `fallback_attempted` 必须为 true——上述输入
  属于损坏/非权威 evidence，应降级 UNKNOWN 而非证明付费调用。

FIX-002 语义（bridge/cost_visibility.py 模块 docstring + 实现）：

| evidence 类 | 判定 | 显示 |
|---|---|---|
| schema-valid authoritative paid runtime record | 经既有权威 validator fail-closed 接受（decision_kind=paid_fallback_runtime_audit、authoritative=true、fallback_attempted=true、全 required 字段、AUTHORIZED gate + exact scope + authorization flags、candidates/final/outcome 一致性） | used=true -> PAID + USED_PAID；attempted-not-used -> PAID + FAILED（真实 paid attempt、不捏造成功 usage） |
| 可解析但损坏/非权威 paid artifact | `{}` / 缺字段 / wrong decision_kind / attempted=false / 矛盾 / schema 违例 | UNKNOWN / 无 actual paid usage（fallback 按既有 gate/guard 证据诚实呈现；绝不 crash UI） |
| 其余 paid 证据路径 | guard / `<agent>_result.md` / gate 等（FIX-001 truth rule） | 零变化（planned/authorized ≠ actual invocation；gate AUTHORIZED 无 runtime -> NOT_USED） |

- Requirement 2：**复用既有权威 validator**——`_validated_paid_runtime` 延迟
  import `fallback_runtime` 并调用 `validate_paid_fallback_runtime_record`
  （纯只读 fail-closed schema 检查）；Bridge 不重实现第二份 paid schema。
- 单点 gate：`derive_hermes_row` 加载/injection `fb_paid` 后立即归一
  （invalid -> None），全部内部 helper（actual model/provider、cost class、
  fallback、planned、detail）只消费 validated record——不存在第二条判断路径。

## 3. 实现（最小 UI 变更）

- `bridge/cost_visibility.py`：
  - 模块 docstring 新增 FIX-002 evidence-validation 段（fb_paid 存在 ≠ paid
    invocation 证据；schema-valid authoritative record 才可产生 PAID /
    USED_PAID / FAILED；损坏/非权威 -> UNKNOWN fail-soft；truth rule 零变化）。
  - 新增 `_validated_paid_runtime(fb_paid)`：单点权威 evidence gate——复用
    既有 `fallback_runtime.validate_paid_fallback_runtime_record`（延迟
    import，纯只读）；任何 schema 违例 -> None（fail-soft，绝不抛异常）。
  - `derive_hermes_row` 在 fb_paid 加载后立即过 gate；`_hermes_actual_model_
    provider` / `_hermes_actual_cost_class` / `_hermes_fallback` docstring 补
    FIX-002 语义说明（helper 只收到 schema-valid record）。
- `bridge/status_window.py`、`bridge/main.py`、`ai_agent_framework/*` 零修改。

## 4. 测试证据（Executor 实测）

- `tests/test_cost_visibility.py` **63 passed**（49 FIX-001 + 14 FIX-002 新增）：
  - FIX-002 Requirement 11 A–H 矩阵：
    - A `fb_paid={}` -> UNKNOWN / NOT_USED，绝不 PAID / USED_PAID（injection +
      output_dir `paid_fallback_runtime.json = {}` 文件路径）
    - B 缺 required 字段（authority / no_silent_paid_evidence /
      paid_required_scope / decision_kind 逐项删除）-> UNKNOWN（含 output_dir
      合法但字段不全的 JSON record 文件）
    - C wrong decision_kind（改为 fallback_runtime_audit）-> UNKNOWN
    - D `fallback_attempted=false`（used=false + outcome=failed）-> 不 PAID /
      USED_PAID（含与 guard AUTH + gate AUTHORIZED 组合仍不 USED_PAID）
    - E schema-invalid 矛盾 record -> UNKNOWN（used↔outcome 矛盾 / gate 非
      AUTHORIZED / authorization_consumed=false / authoritative=false /
      final_actual_model ≠ paid candidate）
    - F schema-valid paid used -> PAID + USED_PAID（injection + output_dir；
      model glm-5.2 / provider zhipu / planned 空）
    - G schema-valid attempted-not-used -> FAILED（detail「attempted but not
      accepted」——不捏造成功 usage）
    - H gate AUTHORIZED 无 paid runtime（None 或损坏 `{}`）-> 不 USED_PAID
      （NOT_USED + detail「not USED_PAID」）
  - 另含：损坏 paid 文件（broken JSON / 非 dict / 空文件）build_cost_rows
    fail-soft 不 crash + 权威 validator 复用静态锁定（display 源码引用
    `validate_paid_fallback_runtime_record` + 独立于显示层的 validator 拒绝
    语义断言）。
  - valid-case fixture 改为经既有权威组装器 `assemble_paid_runtime_audit_
    record` 产生（与真实 paid fallback 落盘 record 同构——display 测试不重
    实现 schema）。
- `tests/test_status_window.py` 53 passed（零修改——回归确认）。
- 聚焦合计 = 116 passed（0.49s + 1.87s）。
- 回归（Req 13/14）：Bridge/status/recovery 10 文件（test_status_window +
  test_bridge_ui_headless + test_bridge_state_recovery +
  test_bridge_state_recovery_exited_window + test_bridge_launcher +
  test_bridge_tray + test_bridge_config + test_bridge_task_io +
  test_bridge_handoff + test_phase_e_cancel_ui）**173 passed**（26.12s）。
- 全量回归（Req 15）：分块全量 non-GUI（4 个 *_e2e.py 排除，4 块
  689+544+509+499）**2241 passed / 1 skipped / 9 deselected（gui_e2e
  marker）零失败**——覆盖全部 87 个被收集测试模块（2242 selected 全绿）。
- 真实 probe（修复前 Codex 输入，修复后实测）：
  - `derive_hermes_row(fb_paid={})` -> `UNKNOWN` / `NOT_USED`（修复前 PAID /
    FAILED）
  - `fb_paid={'fallback_attempted': False, 'fallback_used': False}` ->
    `UNKNOWN` / `NOT_USED`（修复前 PAID）
  - valid used=True -> `PAID` / `USED_PAID`；valid used=False -> `PAID` /
    `FAILED`（valid case 保持）

## 5. 边界（不重开 / 未进入 / 未实现）

- 未实现 PH-2 concurrency / PH-3 / A6 / A4+；未构建 billing ledger / token
  accounting / dashboard platform / 新 payment authorization / 新 cost
  authority（frozen MVP non-MVP 列表保持）。
- 未改动：`ai_agent_framework/*` 全部模块（零 diff——零 authority 变更）；
  routing / payment / fallback / Paid Guard 行为零变化；FIX-001 truth rule
  （planned/authorized ≠ actual invocation）零变化。
- 未新增 paid runtime schema：Bridge 只复用既有权威 validator（延迟 import）。
- 损坏 paid artifact 的显示 = UNKNOWN / 无 actual paid usage（fallback 列按
  既有 gate/guard/free 证据诚实呈现）——这是 FIX 的目标语义，非缺陷。

## 6. 变更清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `bridge/cost_visibility.py` | 修改 | FIX-002 evidence gate：`_validated_paid_runtime`（复用既有权威 validator，延迟 import）+ `derive_hermes_row` 单点归一 + 模块/helper docstring 语义说明 |
| `tests/test_cost_visibility.py` | 修改 | 63 项（FIX-002 Req 11 A–H 矩阵 + output_dir 损坏文件路径 + validator 复用锁定；valid fixture 改走权威组装器） |
| `docs/internal/AAF-v0.5-UX-COST-VISIBILITY-IMPLEMENT-001-FIX-002-REPORT.md` | 新增 | 本报告 |
| `docs/internal/PROJECT_STATE.md` | 修改 | Last Updated 新条目 + v0.5 段 FIX-002 条目块 |
| `docs/internal/AAF_MASTER_BACKLOG.md` | 修改 | Last Updated 新条目 |

- git：parent = 68cbf6ac711cde668daa5912f9cffa94e511bea2（local HEAD）；
  单一 FIX commit，未 amend，未 push；`git diff --check` 通过。
- PRE_ALLOWED_UNTRACKED 保留（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）；编辑/验证脚本在 .aaf（不入 commit）。
- EOL：PROJECT_STATE.md 维持 CRLF、AAF_MASTER_BACKLOG.md 维持 LF、本报告 = LF
  （与 FIX-001 REPORT 同惯例）。

## 7. FRESH_RUNNER_VALIDATION_REQUIRED

本任务修改 Bridge display 层的 paid fallback evidence 判定（fb_paid 存在 ≠
paid invocation；只有 schema-valid authoritative record 才 PAID / USED_PAID /
FAILED）。**须由独立 fresh-runner leg 验证**（全新进程、真实 Bridge/status
上下文，重点）：
1. 全新进程下损坏/字段不全/attempted=false 的 paid_fallback_runtime.json 任务
   dir 不显示 actual PAID / USED_PAID（UNKNOWN 诚实降级、不 crash）；
2. schema-valid paid runtime artifact 的任务 dir 仍正确显示 PAID / USED_PAID /
   FAILED（valid case 无回归）；
3. 零第二经济 authority：显示层只读回显既有 artifact token + 复用既有
   validator，无新 schema / 新决策路径；
4. FIX-001 truth rule（planned/authorized ≠ actual invocation）在全部既有
   reopen / crashed / guard-only 场景无回归。

**本实现 run 不自行声称 final closure**——Unresolved Issues 中唯一非空项 =
required fresh-runner closure + WorkBuddy 独立验证 + Codex review（route
PENDING，不超前声称）。

## 8. 验收对照（Requirements 1-20）

- Req 1（阅读父 Codex result / cost_visibility.py / fallback_runtime.py /
  既有 validator / tests）✅ 全文读取（codex_result.md + validator 全字段 +
  测试矩阵）
- Req 2（复用既有权威 validator，优先 validate_paid_fallback_runtime_record，
  不重实现 schema）✅ 单点 gate 延迟 import 复用；零第二 schema
- Req 3（evidence 权威条件：decision_kind / required 字段 / attempted=true /
  validator 接受）✅ validator fail-closed 全量保证
- Req 4（可解析 JSON dict ≠ 证据）✅（`{}` 测试 A + 探针）
- Req 5（{} / 缺字段 / wrong decision_kind / attempted=false / 矛盾 /
  schema-invalid -> UNKNOWN / 无 actual paid usage）✅ 测试 A–E
- Req 6（损坏/无效 artifact 绝不产生 PAID / USED_PAID）✅
- Req 7（valid case 保持：attempted-not-used / used / free fallback /
  authorized-not-invoked / no fallback）✅ 测试 F–H + 既有 49 项零回归
- Req 8（planned/authorized ≠ actual invocation 保持）✅ FIX-001 测试零回归
- Req 9/10（不改 routing/payment authority；不改经济行为）✅
  ai_agent_framework/* 零 diff
- Req 11（A–H 聚焦回归）✅ 14 项新增
- Req 12（fail-soft UI）✅ 损坏文件不 crash 测试 + build_cost_rows 行级兜底
- Req 13/14/15（聚焦 + Bridge/status/recovery + 全量回归）✅ 116 / 173 /
  2241+1 skipped 零失败
- Req 16（恰一个 FIX commit on 68cbf6a；no amend；no push）✅
- Req 17（PRE_ALLOWED_UNTRACKED 保留）✅
- Req 18（FRESH_RUNNER_VALIDATION_REQUIRED 记录）✅ 本报告 §7
- Req 19/20（WorkBuddy 独立验证 + Codex review）= route PENDING——按 route
  阶段执行，不超前声称
- Unresolved（executor-side）= none；remaining = fresh-runner closure + route
  verdicts（PENDING）
