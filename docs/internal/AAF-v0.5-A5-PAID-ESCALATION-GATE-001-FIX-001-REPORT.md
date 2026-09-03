# AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001 — Implementation Report

> Task: Normalize contradictory paid-gate audit fail-closed state
> （修复 AAF-v0.5-A5-PAID-ESCALATION-GATE-001 的唯一 Codex blocker：
> malformed / contradictory A0 authorization record 被判 FAIL_CLOSED 后，
> 仍必须生成、验证并持久化自洽的 authoritative paid_escalation_gate.json）
> Executor: Hermes（AAF Executor stage）2026-09-03
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Parent commit: `32c4bbe`（未 amend、未 push；新 fix commit = 本任务产物）
> A5 保持 STARTED / NOT CLOSED / COMPLETE（REQUIRED_BEFORE_A5_CLOSE 9 项不重写；
> paid INVOCATION = 后续 A5 任务 scope；零 paid invocation / 无 paid fallback 实现）

## 1. 结论（先给结论）

1. ✅ **Codex blocker 已消除（Requirement 1/3/7）**：malformed / contradictory /
   unknown / internally inconsistent 的 A0 authorization record 被
   `interpret_guard` 判 FAIL_CLOSED 后，现在**总是**产出 validator-valid、
   可持久化的权威 `paid_escalation_gate.json`（此前五种形状组装即抛
   ValueError——见 §2 根因与复现；runtime 只 surface `paid_gate_error`、
   artifact 不落盘，违反 Requirement 7「malformed/contradictory authorization
   仍必须产生 machine-readable validated authoritative fail-closed audit」）。
2. ✅ **raw/source 与 normalized 语义分层（Requirement 2/4/6）**：audit record
   新增 clearly-named raw/source 字段 **`source_guard_record`**（原始 A0
   record 的保真快照）。raw 矛盾证据（decision token、authorization flags、
   scope、notes 原样）完整可观察、可用于 provenance/debugging，但**绝不覆盖**
   normalized authoritative 字段——修复后任何 FAIL_CLOSED record 都不会再出现
   `gate_decision=FAIL_CLOSED + authorization_matched=true` 或
   `FAIL_CLOSED + in-scope ALLOWED_AUTHORIZED_PAID` 这类内部矛盾形状
   （Requirement 5 自洽性）。
3. ✅ **FAIL_CLOSED normalized 语义恒自洽（Requirement 3/5）**：
   - `authorization_present / matched / consumed` 在 FAIL_CLOSED 下恒 False
     （raw flags——包括 matched=True——只存在于 `source_guard_record`）；
   - in-scope 的 `ALLOWED_AUTHORIZED_PAID` token 绝不进入 normalized
     `guard_decision`（与 FAIL_CLOSED 互斥；validator 不变量
     exact-scope authorized ⟹ AUTHORIZED 保持），out-of-scope（scope
     integrity）的 token 按既有已接受行为保留（既有测试
     `test_guard_authorized_for_other_model_fail_closed_record` 语义不变）；
   - `guard_model / provider / cost_class / required_scope` 只做类型安全 echo
     （畸形值如 `42` / 空串 → None，原文留在 source）——任何 parsed A0 record
     的 FAIL_CLOSED 都组装出 validator-clean record；
   - 新增 malformed-scope 收口：`ALLOWED_AUTHORIZED_PAID` + flags 全 True 但
     `required_scope` 畸形（None / 非 str）→ FAIL_CLOSED（此前会组出
     AUTHORIZED record 然后被 validator 拒绝、不落盘——同一 blocker 家族）；
   - notes 非 str 畸形项不进入 record（`_safe_str_list`），raw 原文保留在
     source。
4. ✅ **validator 零削弱 + 新 source 不变量（Requirement 3/5/7）**：既有
   normalized 互洽不变量全部保持（`matched=True ⟹ AUTHORIZED`、
   exact-scope `ALLOWED_AUTHORIZED_PAID` ⟹ `AUTHORIZED`、guard token
   whitelist、unknown-field 拒绝等——防御纵深测试证明即使有人手造矛盾
   FAIL_CLOSED record 仍被拒）。新增：`source_guard_record` 必须 dict/None 且
   JSON 可序列化（raw 证据形状绝不允许使 authoritative audit 无法持久化）。
5. ✅ **A5-003 全部已接受行为保持（Requirement 9）**：exact valid auth →
   AUTHORIZED 但零 paid invocation（fresh-runner F3 + 既有测试）；absent /
   mismatched auth → BLOCKED（既有测试 + parent fresh-runner 复跑 5/5）；
   FREE fallback 优先级不变（fresh-runner F4 + parent N5）；unqualified
   candidate 永不达 Cost Gate；无第二付费授权系统；无 silent paid execution；
   本任务无 paid fallback 实现；`fallback_runtime.py` / `runner.py` /
   `cost_guard.py` / `fallback_contract.py` / `active_routing.py` /
   `workbuddy_routing.py` / `adapters.py` / `model_registry.py`
   **byte-identical 零修改**（修复单元 = `fallback_paid_gate.py` only）。
6. ✅ **测试（Requirement 8/10）**：14 项新聚焦回归
   （tests/test_a5_paid_escalation_gate.py，38 → 52）——解释器 normalized
   FAIL_CLOSED 全矩阵（incomplete flags 含 matched=True / BLOCKED+matched /
   未知 token / required_scope 畸形 / scope-mismatch token+source 保持）+
   runtime 矛盾 A0 record 参数化 6 形状（含 {}）全落盘复验 + scope-unknown
   组合 + validator source 不变量与 FAIL_CLOSED 矛盾形状防御纵深；每项断言
   FAIL_CLOSED + validator-valid + artifact 持久化 + raw source 可观察 +
   fallback_attempted/used 恒 False + 零 paid invocation（calls==0）。
   Canonical 全量回归 **2115 passed / 1 skipped / 16 deselected（0 failed）**
   = HEAD 32c4bbe 基线 **2101 + 14 精确零回归**。
7. ✅ **fresh-runner closure（Requirement 11）5/5（全新进程）**：F1 矛盾
   ALLOWED_AUTHORIZED_PAID+incomplete flags → FAIL_CLOSED + artifact 存在/
   valid + source 中 raw matched=True 可观察 + normalized matched=False + 恰
   1 次 invocation（无 paid）+ WAITING + env 还原；F2 BLOCKED+matched →
   FAIL_CLOSED（同上）；F3 real A0 exact auth → AUTHORIZED 行为不变（仍零
   paid invocation、A0 消费 marker 存在）；F4 FREE fallback 行为不变（恰一次
   zzz-fb、无 gate artifact、SUCCESS）；F5 malformed {} → FAIL_CLOSED +
   source={}。证据：`.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001/
   fresh-runner-validation/`（不提交）。
8. ✅ **范围纪律（Requirement 12/13）**：新 commit（parent 32c4bbe 未 amend）；
   文档更新仅追加（PROJECT_STATE Last-Updated 链 + A5 实现状态 FIX-001
   bullet；backlog CAP-003 行同步）——A5 保持 STARTED / NOT CLOSED /
   COMPLETE；无 paid model invocation；无无关清理；
   PRE_ALLOWED_UNTRACKED（`AAF_TASK004_PROCESS_CHECK.txt` /
   `scripts/start_bridge_hidden.vbs` 等）保留；未 push。

## 2. 根因与修复设计（Codex blocker 复现）

复现（修复前，.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001/scratch_repro.py）：
五种 contradictory/malformed A0 形状经 interpret_guard → FAIL_CLOSED →
assemble_paid_gate_record 全部 ValueError（validator 拒绝）：
- `ALLOWED_AUTHORIZED_PAID` + flags 不齐 →「exact A0 ALLOWED_AUTHORIZED_PAID
  result (with exact candidate scope) must map to gate_decision=AUTHORIZED」；
- `BLOCKED_COST_APPROVAL` + matched=True →「authorization_matched=true requires
  gate_decision=AUTHORIZED」；
- `ALLOWED_FREE` + matched=True → 同上；
- 未知 decision token →「guard_decision must be an A0 Paid Guard token」；
- scope-mismatch + 未知 token → 同上。

根因：`interpret_guard()` 的 FAIL_CLOSED 分支以 `interp.update(base)` 把 raw
A0 字段（authorization flags / guard token / required_scope 原值）整体回写
normalized 字段——`fail_closed_interpretation` 的 fail-closed 语义（flags 恒
False、guard 字段 None）随即被 raw 值覆盖；validator 正确地拒绝自相矛盾的
record → assembly 抛异常 → 不落盘 → runtime 只 surface `paid_gate_error`。

修复（只改 `ai_agent_framework/fallback_paid_gate.py`）：
1. 模块级 A0 token whitelist 常量 `_A0_GUARD_DECISIONS`（validator 与
   FAIL_CLOSED echo 共用，消除本地重复定义）；
2. 类型安全 helpers：`_echo_optional_str`（非空 str 或 None）、
   `_safe_str_list`（notes 只留 str）；
3. `_fail_closed_fields`：FAIL_CLOSED 的 normalized guard 字段——
   authorization_* 恒 False；guard token 只在 ∈ A0 whitelist 且不隐含「本
   候选已授权」（in-scope ALLOWED_AUTHORIZED_PAID）时 echo，否则 None；
   guard model/provider/cost_class/required_scope 类型安全 echo；
4. `_parsed_fail_closed`：parsed-but-contradictory A0 → FAIL_CLOSED +
   normalized 字段 + raw 证据进 `source_guard_record` + notes 带 reason；
5. `fail_closed_interpretation(reason, source_guard_record=None)`：无 parsed
   record（guard 抛异常 / 非 dict / flags 非 bool）→ guard 字段全 None +
   source 快照（dict 时）；
6. `interpret_guard`：所有 FAIL_CLOSED 路径统一走上述归一化（不再
   `interp.update(base)`）；AUTHORIZED 分支新增 required_scope 非空 str
   前置校验（畸形 → FAIL_CLOSED）；BLOCKED / AUTHORIZED 的 notes 也经
   `_safe_str_list`；
7. audit schema：`_REQUIRED_KEYS` + assemble 增加 `source_guard_record`；
8. validator：新增 source 不变量（dict/None + JSON 可序列化）；其余不变量
   零改动（token whitelist 引用常量）。

设计纪律（Requirement 1）：不重设计 A5-003——三态语义、AUTHORIZED/BLOCKED
字段转述、scope integrity、A0 唯一授权 authority、零执行语义全部未动；改动
只消除「raw 覆盖 normalized」这一矛盾源并把 raw 证据放入 clearly-named
source 字段。

## 3. Requirements → 实现映射（本 FIX 范围）

| Req | 验收 | 证据 |
|---|---|---|
| 1 | 只修 blocker，不重设计 A5-003 | 修复单元 = fallback_paid_gate.py（interpret/assemble/validate/schema）；runtime/runner/A0/contract 零修改 |
| 2 | raw/source 与 normalized 分层 | audit record 新字段 `source_guard_record`（A0 record 保真快照）；interpret_guard docstring + 模块 docstring |
| 3 | 任意 malformed/contradictory/unknown → FAIL_CLOSED + 自洽可持久化 | test_contradictory_a0_record_fail_closed_audit_persisted（6 形状参数化）+ fresh-runner F1/F2/F5 |
| 4 | raw 矛盾证据不覆盖 normalized | 解释器测试断言 normalized flags 恒 False + guard token 归一化；source == raw（含 matched=True） |
| 5 | normalized 自洽（AUTHORIZED/BLOCKED/FAIL_CLOSED 定义不变；flags 与 gate 一致） | 新增 test_gate_validator_still_rejects_contradictory_fail_closed_shapes（防御纵深）；既有 mutation 矩阵全绿 |
| 6 | raw 矛盾证据可审计 | source_guard_record 含 raw decision/flags/scope/notes；runtime + fresh-runner 落盘复验断言 |
| 7 | assemble+validator+persistence 对矛盾输入成功 | 复现脚本修复前后对比（5 形状 ValueError → 全过）；6 形状 runtime 测试 + F1/F2/F5 全落盘 |
| 8 | 聚焦回归（四类 + FAIL_CLOSED + valid audit + persisted + raw observable + attempted/used False + 零 invocation） | 14 项新测试（见 §1.6/§4.2） |
| 9 | 既有 A5-003 行为保持 | canonical 2115 零回归 + parent fresh-runner 复跑 5/5 + F3/F4 行为保持场景 |
| 10 | focused + canonical 回归 | §4.1/§4.2 |
| 11 | fresh-runner closure（新进程） | §4.3（F1–F5 5/5） |
| 12 | 新 fix commit，不 amend | §5 |
| 13 | 无无关清理 / PRE_ALLOWED_UNTRACKED 保留 / no push | §5 |

## 4. 验证证据

### 4.1 修复前复现 → 修复后通过（scratch，不提交）
```
python .aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001/scratch_repro.py
```
修复前：5 形状 ASSEMBLY FAILED（validator ValueError）；修复后：5 形状
ASSEMBLY OK（gate=FAIL_CLOSED，matched=False，guard token 归一化，可持久化）。

### 4.2 聚焦 + canonical 回归（Requirement 8/10）
```
python -m pytest tests/test_a5_paid_escalation_gate.py -q            # 52 passed
python -m pytest tests/test_a5_paid_escalation_gate.py tests/test_a5_fallback_runtime.py tests/test_a5_fallback_contract.py -q  # 261 passed
python -m pytest -m "not gui_e2e" --deselect tests/test_phase_e_cancel_ui_e2e.py -q
# 2115 passed / 1 skipped / 16 deselected = HEAD 32c4bbe 基线 2101 + 14 精确零回归
```
新聚焦（+14）：
- Section 1（解释器）：test_interpret_contradictory_paid_flags_normalized_
  fail_closed / test_interpret_blocked_matched_normalized_fail_closed /
  test_interpret_unknown_token_normalized_guard_none_source_preserved /
  test_interpret_authorized_invalid_scope_evidence_fail_closed /
  test_interpret_scope_mismatch_keeps_token_and_source
- Section 2（runtime 编排 + 持久化）：test_contradictory_a0_record_fail_closed_
  audit_persisted（6 参数形状：allowed-incomplete-flags /
  allowed-matched-true-not-consumed / blocked-matched-true / unknown-token /
  authorized-invalid-required-scope / missing-required-keys）+ 
  test_contradictory_scope_evidence_unknown_token_fail_closed_persisted；
  既有 test_guard_evaluation_failure_fail_closed / test_malformed_guard_record_
  fail_closed 强化（artifact 落盘 + source 断言）
- Section 3（validator）：test_gate_validator_rejects_source_guard_record_
  invariants / test_gate_validator_still_rejects_contradictory_fail_closed_shapes
- 既有 test_guard_authorized_for_other_model_fail_closed_record 强化（source
  raw matched=True 可观察断言）

### 4.3 fresh-runner closure（Requirement 11；新进程；5/5）
```
python tests/fresh_runner_a5_paid_escalation_gate_fix001_validation.py   # 退出码 0
```
- F1（矛盾 ALLOWED_AUTHORIZED_PAID + matched=True/consumed=False）：gate
  FAIL_CLOSED、paid_escalation_gate.json 存在且 validator 通过、normalized
  matched=False、guard_decision=None、source_guard_record 原样保留 raw
  decision/matched=True、marker 恰 1 行 aaa-orig@custom（零 paid）、无 A0
  消费 marker、WAITING、无 chain、env probe 全 -none-
- F2（BLOCKED_COST_APPROVAL + matched=True）：FAIL_CLOSED、artifact valid、
  normalized matched=False、guard token BLOCKED 保留、source matched=True
  可观察、零 paid、WAITING、env 还原
- F3（real A0 + exact AAF_COST_AUTH）：AUTHORIZED 行为不变（present/matched/
  consumed=true、A0 一次性消费 marker 存在、marker 仍恰 1 行——授权 ≠ 执行）、
  source 快照存在、WAITING、env 还原
- F4（pg_free_intact + real A0）：FREE fallback 行为不变（恰一次 zzz-fb
  used=true final=zzz-fb、gate artifact 不存在、SUCCESS）
- F5（malformed {}）：FAIL_CLOSED、artifact valid、source={} 保真、恰 1 行、
  WAITING、env 还原

### 4.4 parent fresh-runner 驱动复跑（A5-003 行为保持）
```
python tests/fresh_runner_a5_paid_escalation_gate_validation.py   # 退出码 0（5/5）
```

## 5. 改动清单 / 范围纪律 / 遗留

改动（tracked + 新文件，全部在 WORKSPACE 内）：
- 改：`ai_agent_framework/fallback_paid_gate.py`（修复单元：raw/source 分层
  + FAIL_CLOSED normalization + source_guard_record schema/validator +
  malformed-scope 收口）
- 改：`tests/test_a5_paid_escalation_gate.py`（+14 项聚焦；3 项既有测试强化）
- 新：`tests/fresh_runner_a5_paid_escalation_gate_fix001_wrapper.py` /
  `tests/fresh_runner_a5_paid_escalation_gate_fix001_validation.py`
- 新：本报告 `docs/internal/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001-REPORT.md`
- 改：`docs/internal/PROJECT_STATE.md`（Last Updated 链 + A5 实现状态 FIX-001
  bullet——A5 保持 STARTED / NOT CLOSED / COMPLETE，REQUIRED_BEFORE_A5_CLOSE
  9 项不重写）
- 改：`docs/internal/AAF_MASTER_BACKLOG.md`（CAP-003 A5 行追加 FIX-001 同步；
  历史行不重写）

范围纪律（Requirement 13）：
- 零 paid model invocation；无 paid fallback 实现；A0 Paid Guard /
  fallback_contract / fallback_runtime / runner / active_routing /
  workbuddy_routing / adapters / model_registry **零修改**（byte-identical）；
  A3/A4/A6/A4+ 不进入；
- PRE_ALLOWED_UNTRACKED（`AAF_TASK004_PROCESS_CHECK.txt` /
  `scripts/start_bridge_hidden.vbs` / `.aaf/` 运行证据）保留不动；无无关清理；
- 未 push（commit 后待 WorkBuddy 独立验证 + Codex APPROVE）；
- 遗留（非代码）：scratch 复现脚本与 fresh-runner 证据目录留在
  `.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-001/`（untracked，不提交，
  可随时人工删除）。

## 6. 验收对照

- [x] Codex blocker 已消除（矛盾 A0 → FAIL_CLOSED + 自洽 record + 持久化）
- [x] malformed/contradictory A0 authorization 恒 fail closed
- [x] 权威 paid gate audit machine-readable、validator-valid、持久化
- [x] normalized gate 语义内部自洽（flags/token 与 gate_decision 一致）
- [x] raw/source 矛盾证据可审计（source_guard_record）
- [x] 零 paid invocation（marker / evidence / attempted-used 三重证明）
- [x] 既有 valid authorization 行为保持（AUTHORIZED 仍零 invocation；BLOCKED 语义不变）
- [x] FREE fallback 行为保持（聚焦 + canonical + parent fresh-runner 复跑 + F4）
- [x] focused tests 52/52（+14）；canonical 2115 passed 零回归
- [x] fresh-runner closure 5/5（fix001 驱动，新进程）
- [ ] WorkBuddy 独立验证（route 阶段）
- [ ] Codex APPROVE（route 阶段）
- [x] Unresolved Issues = None（实现侧）
- [x] no push
