# AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002 REPORT

Task: Extend WorkBuddy economic routing to MEDIUM risk
Baseline HEAD: dfe0e01e6f96fb2731dc58da930433bc559b2711（parent = AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-001-FIX-001）
Route: Hermes -> WorkBuddy -> Codex
A4 Status: **STARTED**（保持不变；本 slice = LOW + MEDIUM WorkBuddy economic active routing）

## 1. 结论

MEDIUM WorkBuddy economic active routing 已交付：active-routing risk 域从
explicit LOW 扩展到 **explicit LOW + MEDIUM**，使用**同一** A4-001 + FIX-001
已接受的权威决策链（A2 selector capability+qualification / A1 registry+risk /
A4 economic fact layer / >=2 可信候选 gate / Auto fail-closed / artifact /
no-fallback），未创建第二套 routing 路径、未复制 eligibility 逻辑。MEDIUM
复用既有 selector capability floor（risk_contract `RISK_FLOORS[MEDIUM].validator`
= T3）——当前真实 WorkBuddy 候选 capability_tier=T4 < T3 → 真实 runtime 下
MEDIUM 任务如实 CodeBuddy Auto（0 eligible，INSUFFICIENT_ELIGIBLE_CANDIDATES），
**真实数据不被人为放宽/伪造**（Requirement 15）。受控 MEDIUM 两可信 fixture
（fixture/evidence injection 仅存在于 fresh-runner wrapper，production 代码
零 hook）证明 routed 分支仍正确执行：routing_applied=true /
winner=med-free / 真实 WorkBuddy argv 精确 `-p --output-format text -y
--model med-free`（恰好一个 --model，无 --effort），artifact 与真实 invocation
一致。LOW 行为零变化。HIGH/CRITICAL 在 active slice 之外 → 新 reason token
`RISK_OUTSIDE_ACTIVE_SLICE`（显式区别于 missing 的 `RISK_UNAVAILABLE`；A3
Hermes active_routing 自身 token 零改动）。全量 non-GUI 4-file-deselect
**1815 passed / 1 skipped / 38 deselected** = stash 同命令 HEAD（dfe0e01）基线
**1794 + 21 精确零回归**；fresh-runner N+1 **6/6**；既有 A4/A3 fresh-runner
驱动全部复跑全绿。

## 2. Requirement 对账

1. ✅ **复用现有实现**（Req 1）：只改 `workbuddy_routing.decide_workbuddy_route`
   的 risk gate（`risk_class not in (RISK_LOW, RISK_MEDIUM)`）+ 文案；selector、
   economics 事实层、artifact、env 机制全部原样复用；无第二套 routing 路径。
2. ✅ **risk 域扩展**（Req 2）：explicit LOW + MEDIUM 均可 active route。
3. ✅ **missing Risk 非权威**（Req 3）：RISK_UNAVAILABLE → Auto（missing ≠
   LOW/MEDIUM）。
4. ✅ **HIGH/CRITICAL 在 slice 外**（Req 4）：新 token `RISK_OUTSIDE_ACTIVE_SLICE`
   → Auto；即使提供可路由的受控候选也只因 risk gate 阻断（测试 I/J 证明）。
5. ✅ **MEDIUM 用既有 risk contract / selector floor**（Req 5）：selector
   `select_shadow_candidate(RISK_MEDIUM, ...)` 自动消费
   `RISK_FLOORS[MEDIUM].validator = T3`；测试 E 直接对比 T4 候选 LOW eligible /
   MEDIUM CAPABILITY_INSUFFICIENT；无单独放宽/硬编码。
6. ✅ **gate 顺序不变**（Req 6）：capability → qualification → trustworthy
   economics → economically_trustworthy >= 2 → economic winner selection
   （测试 A/B/C/D/E/F 覆盖每一级）。
7. ✅ **经济学语义不变**（Req 7）：FRESH / 完整 / 一致 / fail-closed 原样；
   workbuddy_economics.py 零修改。
8. ✅ **候选数语义不变**（Req 8）：<2 可信 → routing_applied=false /
   routed_model=None / fallback_used=false / Auto（测试 B/C/D）。
9. ✅ **LOW 零变化**（Req 9）：测试 G（LOW 受控 routed 保持）+ H（LOW 真实
   facts Auto 保持）+ fresh-runner N2a/N2b 回归 + 既有 A4/A3 驱动复跑全绿。
10. ✅ **MEDIUM routed 恰好一个 --model**（Req 10）：真实 argv 断言
    `--model` count == 1（测试 A / fresh-runner N1b / N4）。
11. ✅ **MEDIUM 不路由时 Auto 无 --model**（Req 11）：真实 argv 断言（测试
    B/C/D/I/J/K / fresh-runner N1/N3）。
12. ✅ **不添加 --effort / provider override / fallback / retry escalation**
    （Req 12）：invocation 断言无 --effort / 无 --provider；fallback_used 恒
    false；transport retry 复用同一 routed args（测试 M / N4）。
13. ✅ **无 silent fallback**（Req 13）：routing 后失败按既有异常语义如实
    FRAMEWORK_ERROR；无 Auto 退回 / 无第二模型尝试（N4 fresh-process 证明）。
14. ✅ **artifact 支持 MEDIUM 不改 authority 语义**（Req 14）：risk_class=MEDIUM
    + risk_source 记录、authoritative=true、selected==routed_model、
    Auto 不声称 routed_model、validate fail-closed（测试 artifact authority
    两条 + runner 集成）。
15. ✅ **真实数据不伪造**（Req 15）：MEDIUM 真实 registry → 0 eligible → Auto
    （INSUFFICIENT_ELIGIBLE_CANDIDATES），fresh-runner N1 + 测试
    test_medium_real_registry_auto_via_capability_floor 证明。
16. ✅ **Req 16 A–M 全矩阵**：见 §3.1。
17. ✅ **Hermes A3 路由零修改**（Req 17）：active_routing.py / test_active_routing.py
    零改动；A3 / A3-FIX-001 fresh-runner 驱动复跑全绿。
18. ✅ **Codex 路由零修改**（Req 18）：零改动。
19. ✅ **不实现 HIGH/CRITICAL**（Req 19）：HIGH/CRITICAL 保持 Auto。
20. ✅ **PROJECT_STATE / backlog 最小更新**（Req 20）：A4 保持 STARTED；LOW +
    MEDIUM 已实现；HIGH / broader multi-agent 仍未来 A4 工作（见 §5）。

## 3. 测试

### 3.1 新增 `tests/test_a4_workbuddy_routing_medium.py`（21 项，Req 16 A–M + 附加）

- A. MEDIUM + 2 T3-qualified + 2 trustworthy economics → routing_applied=true /
  确定性经济 winner（rank 0 权威免费 outranks rank 1）/ 真实 argv 恰好一个
  --model / 无 --effort；经济平局 → model_id 字典序 tie-break。
- B. MEDIUM + 2 qualified 但只有 1 个 trustworthy → Auto（INSUFFICIENT_ECONOMIC）。
- C. MEDIUM + 0 trustworthy（STALE + UNKNOWN）→ Auto（NO_TRUSTWORTHY_ECONOMIC_WINNER）。
- D. MEDIUM + 只有 1 个 capability-qualified → Auto（INSUFFICIENT_ELIGIBLE）。
- E. MEDIUM capability-insufficient 候选（T4 vs floor T3）经济前排除；同一候选
  LOW eligible → 证明差异来自 selector floor；经济层不消费被排除候选。
- F. MEDIUM qualification-unknown 候选经济前排除（QUALIFICATION_UNKNOWN）。
- G. LOW 受控两可信 routed 保持（winner=low-free，reason 含 explicit Risk=LOW）。
- H. LOW 真实 baseline facts Auto 保持（trustworthy=1 → INSUFFICIENT_ECONOMIC）。
- I/J. HIGH / CRITICAL → Auto（RISK_OUTSIDE_ACTIVE_SLICE；受控可路由候选下
  仍 Auto → 证明是 risk gate 阻断）。
- K. missing Risk → Auto（RISK_UNAVAILABLE；受控可路由候选下仍 Auto）。
- L. 输入顺序无关（registry + facts dict 反转 → 同决策同 winner）。
- M. 无 --effort / 无 fallback（fallback_used=false；validate 拒绝 True）。
- 附加：MEDIUM + 3 eligible、economics 后剩 2 → routed（FIX-001 gate 同效）；
  MEDIUM routed artifact authority（risk_class=MEDIUM + risk_source +
  authoritative + roundtrip）；MEDIUM Auto artifact（不声称 routed_model）；
  MEDIUM env apply/restore（含旧值还原）；runner 集成三条（MEDIUM 受控全链
  routed + env 可见/还原 + stage ref / MEDIUM 真实 registry Auto + env 未触碰 /
  HIGH control 受控可路由候选下仍 Auto）。

### 3.2 既有测试同步（零净变化）

- `tests/test_a4_workbuddy_routing.py`：`test_non_low_risk_auto`
  （MEDIUM/HIGH/CRITICAL）→ `test_outside_slice_risk_auto`（HIGH/CRITICAL，
  token 改为 REASON_RISK_OUTSIDE_SLICE）+ 新增
  `test_medium_real_registry_auto_via_capability_floor`（真实 registry 下
  MEDIUM → 0 eligible → Auto）；`test_runner_high_preserves_auto` token 同步；
  docstring 边界更新。
- `tests/test_a4_workbuddy_routing_fix001.py`：docstring 边界更新（仅注释）。

### 3.3 结果数字

- 定向 A4 聚焦（routing + fix001 + medium + economics + economics-fix001 +
  second_candidate + qualification + discovery + shadow_routing）：**226 passed**。
- 全量 non-GUI 4-file-deselect（与既往同一排除约定）：
  `python -m pytest -q --deselect tests/test_phase_e_cancel_ui_e2e.py --deselect tests/test_phase_e_e2e.py --deselect tests/test_phase_e_force_e2e.py --deselect tests/test_phase_f_e2e.py`
  → **1815 passed / 1 skipped / 38 deselected**；
  stash 同命令 HEAD（dfe0e01）基线 = **1794 passed / 1 skipped / 38 deselected**；
  1815 − 1794 = **+21 精确零回归**。

## 4. Fresh-Runner N+1（`tests/fresh_runner_a4_wb_econ_medium_validation.py`，6/6）

- **N1（Risk: MEDIUM，真实 facts/registry，wrapper 零注入）**：全新进程真实
  runner 全链 hermes -> workbuddy -> codex SUCCESS；`workbuddy_active_routing.json`
  risk_class=MEDIUM / routing_applied=false / selected=None / routed_model=None /
  eligible=[] / fallback_used=false / reason=INSUFFICIENT_ELIGIBLE_CANDIDATES；
  fake codebuddy 真实子进程 argv 精确 = `-p --output-format text -y`（无
  --model）。**当前真实数据不被人为放宽/伪造（Req 15）——真实 WorkBuddy 候选
  T4 < MEDIUM floor T3。**
- **N1b（Risk: MEDIUM，受控 medium_two_trustworthy，wrapper +
  AAF_TEST_ECON_FACTS_MODE=medium_two_trustworthy）**：真实 registry 基础上
  新增两个 MEDIUM-eligible（T3+QUALIFIED）候选 med-free（FRESH free rank 0）/
  med-discount（FRESH discount rank 1）→ routing_applied=true / selected=
  routed_model=med-free / economically_trustworthy=[med-free, med-discount] /
  fallback_used=false；fake codebuddy argv 精确 = `-p --output-format text -y
  --model med-free`（恰好一个 --model，无 --effort）；artifact 与真实
  invocation 一致（artifact_matches_invocation=true）；validator PASS、全链
  SUCCESS。**受控 fixture/evidence injection，与真实 N1 明确区分（Req 16A）——
  证明 MEDIUM active route 分支真实执行。**
- **N2a（Risk: LOW，真实 facts）**：LOW 回归 —— routing_applied=false /
  INSUFFICIENT_ECONOMIC_CANDIDATES（trustworthy=1）/ argv 精确 Auto。
- **N2b（Risk: LOW，受控 two_trustworthy）**：LOW 回归 routed 分支 ——
  routing_applied=true / winner=hy4-preview / argv 精确 `-p --output-format
  text -y --model hy4-preview`（LOW 行为零变化，Req 9）。
- **N3（Risk: HIGH，control）**：全链 SUCCESS；routing_applied=false /
  routed_model=None / reason=RISK_OUTSIDE_ACTIVE_SLICE / argv 精确 Auto。
- **N4（fresh-process，`fresh_runner_a4_wb_econ_medium_check.py`，28 项断言）**：
  MEDIUM 真实 → Auto（capability floor T3）；MEDIUM 受控 → routed + env apply
  后真实 args 恰好一个 --model med-free + retry 复用同一 args（无 silent
  fallback / 无第二模型）；LOW 真实 Auto + 受控 routed hy4-preview 回归；
  HIGH/CRITICAL/missing → Auto（即使受控可路由候选）；validate fail-closed
  （fallback_used=True 拒绝 / Auto 声称 routed_model 拒绝 / 非 applied apply
  拒绝）；env apply/restore 精确还原。
- 证据：`.aaf/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002/fresh-runner-validation/`
  （scenario_record.json 含逐场景字段；不提交）。

既有驱动复跑（全部绿色，Hermes A3 / Codex 路由零变化）：
- A4-001 `fresh_runner_a4_wb_economic_routing_validation.py` 4/4；
- A4-001-FIX-001 `fresh_runner_a4_wb_econ_fix001_validation.py` 4/4；
- SECOND-CANDIDATE 3/3；QUALIFICATION 3/3；ECONOMICS 2/2；
- A3 `fresh_runner_a3_validation.py` 2/2；A3-FIX-001 2/2。

## 5. 文档状态同步

- `docs/internal/PROJECT_STATE.md`：Last Updated 链 + 新增「A4 MEDIUM Active
  Economic Routing Delivered（002）」小节；A4 保持 STARTED（LOW + MEDIUM
  WorkBuddy economic routing implemented；HIGH / broader multi-agent 仍未来
  A4 工作，Req 19/20），A5/A6 未进入。
- `docs/internal/AAF_MASTER_BACKLOG.md`：Last Updated 链 + CAP-002 Current
  Implementation 追加 002 记录 + CAP-003 Current Implementation 追加 A4
  slice 部分实现注记（HIGH/CRITICAL / multi-agent / A5 / A6 仍 NOT
  IMPLEMENTED）。

## 6. Changed Files

- `ai_agent_framework/workbuddy_routing.py`（核心：risk gate LOW -> LOW+MEDIUM；
  新 reason token `REASON_RISK_OUTSIDE_SLICE` = `RISK_OUTSIDE_ACTIVE_SLICE`
  （HIGH/CRITICAL，显式区别于 missing 的 RISK_UNAVAILABLE）；applied reason
  动态反映 risk_class；docstring / AUTHORITY_STATEMENT / boundaries 同步）
- `ai_agent_framework/runner.py`（workbuddy stage 注释块同步：Risk: LOW 或
  MEDIUM + floor T3 说明；零逻辑变化）
- `tests/test_a4_workbuddy_routing.py`（HIGH/CRITICAL token 同步 +
  MEDIUM 真实 registry Auto 新测试 + docstring）
- `tests/test_a4_workbuddy_routing_fix001.py`（docstring 边界更新）
- `tests/test_a4_workbuddy_routing_medium.py`（新增 21 项，Req 16 A–M + 附加）
- `tests/fresh_runner_a4_wb_econ_medium_wrapper.py`（新增：MEDIUM 受控 registry
  + facts 注入 wrapper，env-gated，production 代码零 hook）
- `tests/fresh_runner_a4_wb_econ_medium_check.py`（新增：fresh-process 28 项断言）
- `tests/fresh_runner_a4_wb_econ_medium_validation.py`（新增：N+1 驱动 6 场景）
- `docs/internal/AAF-v0.5-A4-WORKBUDDY-ECONOMIC-ROUTING-002-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`（状态同步）

未修改：model_registry.py / workbuddy_economics.py / adapters.py /
shadow_routing.py / active_routing.py / cost_guard.py / context_packet.py
（源码级零变化；A3 Hermes token REASON_RISK_NOT_LOW 与 test_active_routing.py
保持原样，Req 17）。

## 7. 边界（Boundaries）

无 HIGH/CRITICAL active routing（保持 Auto）、无 effort routing、无
automatic fallback、无 Cost Gate UX、无 health/quarantine、无 runtime
requalification loop、无 Hermes（A3）路由变更、无 Codex 路由变更、无 A5/A6、
无 broader multi-agent routing。经济事实层（workbuddy_economics.py）零修改；
registry（model_registry.py）零修改；MEDIUM eligibility 完全由既有 selector
floor（T3）决定。

## 8. 未完成项 / 问题

- Unresolved Issues = None（本 TASK scope 内）。
- 已知依赖（与 FIX-001 相同性质）：N1 的 MEDIUM Auto 结论依赖真实 registry
  中 WorkBuddy 候选 capability_tier=T4（LOW probe 证据）——未来若有候选获得
  MEDIUM floor（T3）资格化证据（真实 MEDIUM probe），MEDIUM 任务会如实进入
  经济 gate（这是 registry 事实变化，不是本实现失败）；N1b 受控 fixture 永远
  稳定。真实 economic facts 下（即便候选满足 T3）trustworthy < 2 时 MEDIUM
  同样如实 Auto（测试 B 覆盖该 gate 语义）。
