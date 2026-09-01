# AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001 — Implementation Report

> Task: Enforce two-candidate economic routing gate（修复 A4-001 唯一已知 blocker：
> WorkBuddy active economic routing 的两候选最小数量 gate 必须作用于
> capability + qualification + trustworthy economics **全部**过滤之后）
> Executor: Hermes（AAF Executor stage）2026-09-02
> Status: **IMPLEMENTED**（Codex Requirement 5 blocker 完全消除）；**A4 保持
> STARTED**；broader MEDIUM/HIGH/multi-agent 路由 = 未来 A4 工作（NOT
> IMPLEMENTED）；A5/A6 未进入
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex 审查为接受前置条件）
> Parent: AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001（commit 6ca78d94ed391bf629febf190669f8a19fdc12ef，
> 未 amend 未 push；本 FIX = 新建 commit）

## 1. 结论（先给结论）

1. ✅ **Codex Requirement 5 blocker 完全消除**：两候选最小数量 gate 现在作用于
   **全部过滤链之后**——`len(economically_trustworthy) >= 2` 才允许 economic
   winner selection。经济过滤后只剩 1 个可信候选 → `routing_applied=false` /
   `routed_model=None` / `fallback_used=false` / CodeBuddy Auto；0 个 → 既有
   `NO_TRUSTWORTHY_ECONOMIC_WINNER` 保持。已知 fresh-runner 反例（eligible=
   deepseek-v4-flash+hy4-preview、economically_trustworthy=[hy4-preview]、
   routing_applied=true）已翻转：真实 facts 下现在正确得到 routing_applied=false。
2. ✅ **显式 no-route reason 区分**（Requirement 3/4）：新 reason token
   `INSUFFICIENT_ECONOMIC_CANDIDATES` 专用于「经济过滤后只剩 1 个可信候选」；
   **绝不**与 capability 不足的 `INSUFFICIENT_ELIGIBLE_CANDIDATES` 混用
   （测试锁定两个 token 不同且场景不串）。
3. ✅ **真实 runtime 不伪造**（Requirement 13）：fresh-runner N1 用**真实**
   baseline economic facts（deepseek-v4-flash freshness UNKNOWN → 经济过滤后
   仅 hy4-preview 一个可信）证明 Auto——`routing_applied=false`、fake codebuddy
   argv 精确 `-p --output-format text -y`（无 --model）、reason =
   INSUFFICIENT_ECONOMIC_CANDIDATES、全链 SUCCESS。没有为让 N1 active route
   而伪造第二个可信候选。
4. ✅ **受控两候选分支仍工作**（Requirement 14）：新增受控 deterministic
   scenario（`AAF_TEST_ECON_FACTS_MODE=two_trustworthy` fixture/evidence
   injection，wrapper = `tests/fresh_runner_a4_wb_econ_fix001_wrapper.py`，
   生产代码零 test hook）——full-runner fresh-process N1b：
   `routing_applied=true` / selected=hy4-preview（rank 0 权威免费 outranks
   rank 1 FRESH discount）/ `economically_trustworthy=[hy4-preview,
   deepseek-v4-flash]` / fake codebuddy argv 精确 `-p --output-format text -y
   --model hy4-preview`（恰好一个 --model，无 --effort）/ artifact 与真实
   invocation 一致；与真实 N1 明确区分（不同 wrapper、不同场景目录、
   fixture source 显式标注 test-only）。
5. ✅ **既有 gate 与策略零变化**（Requirement 5/6/7）：capability/qualification
   gate（`MIN_ELIGIBLE_CANDIDATES=2` + INSUFFICIENT_ELIGIBLE_CANDIDATES）原样；
   economic trustworthiness 定义（FRESH + 完整 + 一致 + fail-closed，消费
   cheapness_rank ∈ {0,1}）原样；经济排序策略（(cheapness_rank, multiplier,
   model_id) 确定性选择 + tie-break）原样——只是在 trustworthy candidates
   >= 2 时才运行 winner selection。
6. ✅ **不 hard-code**（Requirement 8）：新增测试全部使用 generic 候选 id
   （cand-a/cand-b/zeta/alpha 等），断言只依赖经济 rank 语义；唯一使用真实
   model id 的是「真实 baseline facts」场景（断言的是「1 个可信 → Auto」的
   gate 语义，不是模型特判）。
7. ✅ **no silent fallback 保持**（Requirement 10）：fallback_used 恒 false
   （fixed semantic + validate fail-closed）；transport retry 复用同一 routed
   args；N3 fresh-process 证明真实 facts → Auto + 受控 routed 分支 +
   无隐藏 Auto 路径。
8. ✅ **artifact 准确**（Requirement 11）：Auto 场景 artifact 如实记录 eligible /
   economically_trustworthy / routing_applied=false / routed_model=None /
   no-route reason（INSUFFICIENT_ECONOMIC_CANDIDATES）/ fallback_used=false；
   save/load roundtrip 测试锁定。
9. ✅ **Hermes A3 / Codex 路由零修改**（Requirement 15/16/17）：变更只在
   workbuddy_routing.py 决策逻辑 + runner 注释同步 + 测试；A3 fresh-runner
   驱动复跑全绿（Hermes routing 零变化）；Codex 无改动。
10. ✅ **测试 + fresh-runner 全绿**：17 项新增聚焦测试
    （tests/test_a4_workbuddy_routing_fix001.py，Req 12 A–G 全矩阵）+ 父测试
    文件 8 项 bug 语义测试翻转 = 定向 A4 聚焦 **155 passed**；全量 non-GUI
    4-file-deselect **1794 passed / 1 skipped / 38 deselected**（stash 同命令
    HEAD 基线 **1777 + 17 精确零回归**）；fresh-runner N+1 **4/4**；既有 4 个
    A4 prerequisite fresh-runner 驱动（N1 LOW 期望同步回 Auto 形状）复跑全绿
    + A3 / A3-FIX-001 驱动复跑全绿。

## 2. 实现

### 2.1 `ai_agent_framework/workbuddy_routing.py`（核心修复）

- 新增常量：
  - `MIN_ECONOMIC_CANDIDATES = 2`——两候选 gate 作用于 capability +
    qualification + trustworthy economics **全部**过滤之后（Requirement 1/2）。
  - `REASON_INSUFFICIENT_ECONOMIC = "INSUFFICIENT_ECONOMIC_CANDIDATES"`——
    显式区别于 `INSUFFICIENT_ELIGIBLE_CANDIDATES`（Requirement 4）。
- `decide_workbuddy_route` 经济块改为三路：
  - `len(economically_trustworthy) == 0` → 既有
    `NO_TRUSTWORTHY_ECONOMIC_WINNER`（0 个可信，无确定性 winner）；
  - `len(economically_trustworthy) == 1` → **新**
    `INSUFFICIENT_ECONOMIC_CANDIDATES`（capability+qualification 通过、
    经济信任度通过，但只剩 1 个可比较候选 → 禁止路由，CodeBuddy Auto）；
  - `len(economically_trustworthy) >= 2` → 既有确定性 winner selection
    （排序键不变，Requirement 7）。
- 模块 docstring / AUTHORITY_STATEMENT / reason 注释同步（两候选 gate 语义、
  new reason token、与 eligible gate 的区别）。
- validate / save / load / env apply-restore 零变化（决策语义已正确，校验
  契约无需改动；Auto 记录 selected/routed_model=None 由既有 validate 强制）。

### 2.2 `ai_agent_framework/runner.py`（注释同步，零逻辑变化）

- workbuddy stage 注释块更新：明确「两候选 gate 作用于全部过滤之后；
  economically_trustworthy >= 2；只剩 1 个 → INSUFFICIENT_ECONOMIC_CANDIDATES
  → Auto」。runner 调用点（facts=None → baseline）零改动。

## 3. 测试

### 3.1 新增 `tests/test_a4_workbuddy_routing_fix001.py`（17 项，Req 12 A–G）

- A. 2 eligible + 1 trustworthy → Auto（generic 候选 + 真实 baseline facts
  双场景；后者 = 「当前真实 facts 不伪造」的聚焦断言）。
- B. 2 eligible + 2 trustworthy → routed + 真实 argv 恰好一个 --model +
  无 --effort。
- C. 3 eligible，economics 后剩 2 个 → routed（1 个 rank 2 被排除）。
- D. 2 eligible，economics 后剩 0 个（STALE + UNKNOWN）→ Auto。
- E. 1 eligible → Auto（economics 不能救活不足两个 eligible）。
- F. STALE / UNKNOWN / incomplete / contradictory 不能凑满两候选
  （parametrize 4 态 + 3-eligible-2-bad 扩展）。
- G. 输入顺序无关（registry 插入顺序 + facts dict 顺序反转 → 同一决策，
  routed 与 Auto 两分支）。
- 附加：reason token 区分（两个 token 不同 + 场景不串 + reason 说明
  「fewer than two」可信候选）；不 hard-code（generic 候选）；Auto artifact
  save/load roundtrip 准确性（eligible/economically_trustworthy/routing_
  applied/routed_model/reason/fallback_used/authoritative）；capability gate
  优先于 economics 不回归。

### 3.2 父文件 `tests/test_a4_workbuddy_routing.py` 翻转（8 项 bug 语义测试）

- `test_low_two_qualified_fresh_economics_routes_to_hy4_preview` →
  `test_low_two_eligible_one_trustworthy_economics_auto`（真实 facts → Auto +
  INSUFFICIENT_ECONOMIC_CANDIDATES）。
- `test_selected_is_economic_winner_not_selector_default` → 受控两可信 fixture
  → routed + selected=经济 winner ≠ selector 默认。
- `test_contradictory_economics_auto` → `test_contradictory_economics_never_
  enters_ordering`（增加第二个可信候选使路由生效，矛盾候选被排除且永不获胜）。
- `test_no_effort_anywhere` / `test_no_fallback_semantics` /
  `test_artifact_authority_semantics` / `test_env_apply_restore` →
  改用受控两可信 fixture（保持原断言语义）。
- `test_runner_low_writes_workbuddy_routing_artifact_and_env` → runner 测试
  wrapper 支持 facts 注入（仅测试；生产 runner 恒 facts=None），LOW 全链
  routing_applied=true + env apply/restore + stage ref。
- 新增共享 helper `_two_trustworthy_facts()`（deepseek-v4-flash → FRESH
  discount rank 1；hy4-preview → FRESH free rank 0；winner=hy4-preview）。

## 4. Fresh-Runner N+1（`tests/fresh_runner_a4_wb_economic_routing_validation.py`，4/4）

- **N1（Risk: LOW，真实 facts，wrapper = fresh_runner_wrapper.py 零注入）**：
  全新进程真实 runner 全链 hermes -> workbuddy -> codex SUCCESS；
  `workbuddy_active_routing.json` routing_applied=false / selected=None /
  routed_model=None / fallback_used=false / economically_trustworthy=
  [hy4-preview] / reason=INSUFFICIENT_ECONOMIC_CANDIDATES；fake codebuddy
  真实子进程 argv 精确 = `-p --output-format text -y`（无 --model）。
  **当前真实 facts 不被人为伪造成可路由（Req 13）。**
- **N1b（Risk: LOW，受控 two_trustworthy，wrapper =
  fresh_runner_a4_wb_econ_fix001_wrapper.py + AAF_TEST_ECON_FACTS_MODE=
  two_trustworthy）**：routing_applied=true / selected=hy4-preview /
  routed_model=hy4-preview / economically_trustworthy=[hy4-preview,
  deepseek-v4-flash]；fake codebuddy argv 精确 = `-p --output-format text -y
  --model hy4-preview`（恰好一个 --model，无 --effort）；artifact 与真实
  invocation 一致。**受控 fixture/evidence injection，与真实 N1 明确区分
  （Req 14）——证明 active route 分支仍正确执行。**
- **N2（Risk: HIGH，control）**：全链 SUCCESS；routing_applied=false /
  routed_model=None；argv 精确 Auto 无 --model。
- **N3（fresh-process，`fresh_runner_a4_wb_economic_routing_check.py`，
  23 项断言）**：真实 facts → Auto（INSUFFICIENT_ECONOMIC_CANDIDATES）；
  受控两可信 → routing_applied=true + winner 确定性 + env apply 后
  run_agent 真实 args 恰好一个 --model + retry 复用同一 args；HIGH → Auto；
  validate fail-closed（Auto 不声称 routed_model / fallback_used=True 违规 /
  非 applied apply 拒绝）；retry 层无第二套 invocation 构造。

既有驱动复跑：
- QUALIFICATION / SECOND-CANDIDATE / ECONOMICS / ECONOMICS-FIX-001：N1 LOW
  期望**同步回 Auto 形状**（父任务曾把 N1 同步为 routed 形状；本 FIX 的真实
  facts 行为恢复 Auto，驱动期望随之还原）→ 复跑全绿。
- A3 / A3-FIX-001 复跑全绿（Hermes 路由零变化）。

## 5. 结果数字

- 定向聚焦测试：**155 passed**（test_a4_workbuddy_routing_fix001.py 17 新增 +
  test_a4_workbuddy_routing.py 34 + economics / economics-fix001 / second_
  candidate / qualification / discovery 全部）。
- 全量 non-GUI（4-file-deselect，与既往同一排除约定）：
  **1794 passed / 1 skipped / 38 deselected**；stash 反证同命令 HEAD
  （6ca78d9）基线 = **1777 passed / 1 skipped / 38 deselected**；
  1794 − 1777 = **+17 精确零回归**。
- fresh-runner N+1：本任务 4/4；既有 4 个 A4 prerequisite 驱动 + 2 个 A3
  驱动复跑全绿。
- git：本任务新建 FIX commit，未 amend parent，未 push（review 后同步）。

## 6. Changed Files

- `ai_agent_framework/workbuddy_routing.py`（核心修复：两候选 gate 移到
  经济过滤后 + 新 reason token + docstring/authority 同步）
- `ai_agent_framework/runner.py`（workbuddy stage 注释同步，零逻辑变化）
- `tests/test_a4_workbuddy_routing.py`（8 项 bug 语义测试翻转 + 受控 fixture
  helper + runner 测试 facts 注入）
- `tests/test_a4_workbuddy_routing_fix001.py`（新增 17 项，Req 12 A–G 全矩阵）
- `tests/fresh_runner_a4_wb_economic_routing_validation.py`（N1 翻转 Auto +
  新增 N1b 受控场景 + N2/N3 保持）
- `tests/fresh_runner_a4_wb_economic_routing_check.py`（真实 facts Auto +
  受控 routed 分支 + no-silent-fallback，23 项）
- `tests/fresh_runner_a4_wb_econ_fix001_wrapper.py`（新增：受控两可信 fixture
  wrapper，env-gated，生产代码零 hook）
- `tests/fresh_runner_a4_wb_qualification_validation.py` /
  `tests/fresh_runner_a4_wb_second_candidate_validation.py` /
  `tests/fresh_runner_a4_wb_econ_validation.py` /
  `tests/fresh_runner_a4_wb_econ_fix001_validation.py`（N1 LOW 期望同步回
  Auto 形状）
- `docs/internal/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（状态同步）

## 7. 边界（Boundaries）

无 MEDIUM/HIGH active routing、无 effort routing、无 automatic fallback、
无 Cost Gate UX、无 health/quarantine、无 runtime requalification loop、
无 Hermes（A3）路由变更、无 Codex 路由变更、无 A5/A6、无 broader
multi-agent expansion。经济事实层（workbuddy_economics.py）零修改
（trustworthiness 定义与 fail-closed 契约保持，Requirement 6）。

## 8. 未完成项 / 问题

- Unresolved Issues = None（本 FIX scope 内）。
- 已知依赖：N1 的 Auto 结论依赖真实 facts 中 deepseek-v4-flash freshness
  UNKNOWN（daily-only 夜间折扣无日期窗口）——事实层刷新若给 deepseek-v4-flash
  提供 FRESH 窗口，N1 会如实变为可路由（这是事实层变化，不是本 gate 失败）；
  N1b 受控 fixture 永远稳定。
