# AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002 — Implementation Report

> Task: Enforce exact paid authorization scope
> （修复 AAF-v0.5-A5-PAID-ESCALATION-GATE-001 的唯一剩余 Codex blocker：
> paid escalation Cost Gate 对 ALLOWED_AUTHORIZED_PAID 必须验证
> **exact task/stage/model/provider scope**——required_scope 必须精确等于
> 当前 task/stage/model/provider 的 canonical expected scope（既有 A0
> `cost_guard.scope_string` 单一 scope authority）；任何 scope mismatch /
> malformed / contradictory evidence 必须 FAIL_CLOSED，不能被授权）
> Executor: Hermes（AAF Executor stage）2026-09-03
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Parent commits: `32c4bbe`（A5-003）、`4c2ebf9`（FIX-001）——均未 amend；新 fix commit = 本任务产物
> A5 保持 STARTED / NOT CLOSED / COMPLETE（REQUIRED_BEFORE_A5_CLOSE 9 项不重写；
> paid INVOCATION = 后续 A5 任务 scope；零 paid invocation / 无 paid fallback 实现）

## 1. 结论（先给结论）

1. ✅ **Codex 唯一 blocker 已消除（Requirement 1/3/4/5）**：`interpret_guard()`
   现在校验 A0 `ALLOWED_AUTHORIZED_PAID` record 的 `required_scope` 是否
   **精确等于** canonical expected scope（= 既有 A0 scope authority
   `cost_guard.scope_string(task_id, stage, model, provider)`，由 gate 上下文
   的 task_id / stage 与 candidate model / provider 重建——**单一 scope 格式、
   复用 A0 authority，未创建第二套 scope/授权机制**，Requirement 2）。wrong
   task / wrong stage / wrong model / wrong provider / missing-malformed scope
   任一维度 → **FAIL_CLOSED（scope mismatch），绝不映射 AUTHORIZED**；raw 矛盾
   scope 证据只保留于 `source_guard_record`（FIX-001 raw/source 分层保持）。
2. ✅ **gate 已知 expected scope 四要素（Requirement 3）**：
   `interpret_guard` 新增 keyword-only 参数 `task_id` / `stage`（runtime 以与
   A0 `cost_guard.evaluate` 同源的 `task_id` / `stage_agent` 调用）——
   candidate model / provider 为既有参数。canonical expected scope =
   `scope_string(task_id, stage, model, provider)`。
3. ✅ **exact canonical scope 仍 AUTHORIZED（Requirement 4/9）**：task /
   stage / model / provider 全部精确匹配时行为零变化——gate AUTHORIZED 且
   **零 paid invocation**（authorization-evaluation-only 语义保持；A5-003
   已接受行为不变）。
4. ✅ **validator 独立 enforcing（Requirement 8，零削弱）**：validator 从
   authoritative record 自身的 task_id / stage_agent / paid_candidate_model /
   provider 重建 canonical expected scope，`gate_decision=AUTHORIZED` 时
   required_scope 必须精确等于它——手造 AUTHORIZED record（required_scope
   指向别的 task/stage/model/provider，或 task_id/stage_agent 字段被改而
   required_scope 未改）被 validator **独立拒绝**（ValueError → 不落盘）。
5. ✅ **FIX-001 normalized/raw 分离保持（Requirement 6/7）**：scope-mismatch
   FAIL_CLOSED 的 normalized 字段恒自洽（authorization_* 恒 False、
   guard_decision None——in-scope ALLOWED_AUTHORIZED_PAID 不 echo、required_scope
   类型安全 echo wrong 值原文），raw A0 record（decision /
   matched=True / wrong scope 原文）完整保留于 source_guard_record 可审计；
   权威 paid_escalation_gate.json **validator-valid + 原子落盘 + reload 复验**；
   fallback_attempted/used 恒 False；零 paid invocation（calls==0）；无 A0
   消费 marker（scripted guard 未 claim）。
6. ✅ **改动范围最小（Requirement 1/14）**：`ai_agent_framework/fallback_paid_gate.py`
   （修复单元：interpret_guard 签名 + exact-scope 校验 + validator canonical
   equality；`fallback_runtime.py` 仅 1 个调用点透传 task_id/stage_agent）；
   `runner.py` / `cost_guard.py`（A0 scope authority 零修改——`scope_string`
   原样复用）/ `fallback_contract.py` / `active_routing.py` /
   `workbuddy_routing.py` / `adapters.py` / `model_registry.py`
   **byte-identical 零修改**。A5-003 / FIX-001 全部已接受行为保持（见 §6）。
7. ✅ **测试（Requirement 9/11）**：聚焦测试 tests/test_a5_paid_escalation_gate.py
   **52 → 60（+8 项新聚焦 + 3 处既有断言增强）**——wrong task / wrong stage /
   wrong model-provider（required_scope 维度）/ expected-scope-is-gate-context /
   source 可审计 5 项纯解释器 + 2 项 live runtime（wrong task / wrong stage →
   FAIL_CLOSED + 落盘复验 + raw 可观察 + 零 invocation）+ 1 项 validator
   手造 AUTHORIZED out-of-canonical-scope 拒绝矩阵；**stash 反证：9 项（含
   增强的既有测试）对修复前代码确定性 FAIL**（旧 interpret 对 wrong-task
   record 直接 AUTHORIZED、旧 validator 接受 out-of-scope AUTHORIZED——
   Codex blocker 复现）。Canonical 回归见 §4.2。
8. ✅ **fresh-runner closure（Requirement 12）5/5（全新进程）**：P1 wrong task
   scope → FAIL_CLOSED（scope mismatch）+ artifact 存在/valid + raw wrong-scope
   source 可观察 + 恰 1 次 invocation（无 paid）+ WAITING + env 还原；P2 wrong
   stage scope → FAIL_CLOSED（同上）；P3 real A0 + exact auth → AUTHORIZED
   但零 paid invocation（A0 消费 marker 存在）；P4 FREE fallback 行为保持
   （恰一次 zzz-fb、used=true、无 gate artifact、SUCCESS）；P5 脚本化 canonical
   exact scope → AUTHORIZED（零 paid invocation、无消费 marker）。证据：
   `.aaf/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002/fresh-runner-validation/`
   （不提交）。parent fresh-runner 驱动（FIX-001 F1–F5 + A5-003 N1–N5）复跑
   全绿。
9. ✅ **范围纪律（Requirement 13/14）**：新 fix commit（4c2ebf9 / 32c4bbe 未
   amend）；无 paid model invocation；无无关清理；PRE_ALLOWED_UNTRACKED
   （`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`）
   保留；未 push。A5 保持 STARTED（REQUIRED_BEFORE_A5_CLOSE 9 项不重写）。

## 2. 根因与修复设计（Codex blocker 复现）

Codex 定位（Context）：`interpret_guard()` / validator 没有校验 required_scope
是否**精确等于**当前 task/stage/model/provider 的 expected scope。此前
interpret_guard 只校验：guard 解析 model/provider == candidate（model/provider
维度）+ flags 全 True + required_scope 非空 str（任何字符串都过）——
一个 model/provider 维度正确但 required_scope 编码**别的 task**（如
`<other-task>|hermes|zzz-paid|remote-api`）或**别的 stage** 的手造/误归属 A0
record 会被 gate 判 AUTHORIZED；validator 的 AUTHORIZED 一致性检查同样只要求
required_scope 非空 → 手造 AUTHORIZED record 可落盘。task / stage 维度在
required_scope 整串证据上缺失校验 = exact task-scoped authorization 语义漏洞。

复现（stash 反证，修复前代码确定性 FAIL——见 §4.1）：wrong-task record
（decision=ALLOWED_AUTHORIZED_PAID + flags 全 True + 同 model/provider +
required_scope=别的 task 的 canonical scope）→ 旧 interpret_guard →
**AUTHORIZED**（9 项新/增强测试全部 FAIL）；旧 validator 接受
required_scope≠canonical 的 AUTHORIZED record。

修复（只改 `ai_agent_framework/fallback_paid_gate.py` +
`fallback_runtime.py` 1 个调用点）：
1. `interpret_guard(guard_record, model, provider, *, task_id, stage)`：
   keyword-only `task_id` / `stage` = gate 的 expected scope 上下文（runtime
   以与 A0 evaluate 同源的 task_id / stage_agent 传入——不引入第二套 scope
   推导）；canonical expected scope = `cg.scope_string(task_id, stage, model,
   provider)`（既有 A0 scope authority，Requirement 2）；
2. `ALLOWED_AUTHORIZED_PAID` 分支新增 required_scope **整串精确相等**校验：
   `scope != expected_scope` → FAIL_CLOSED，reason 显式含「scope mismatch +
   expected/actual 两值 + task/stage/model/provider 四维」；畸形 scope（None /
   空 / 非 str）→ FAIL_CLOSED（FIX-001 既有收口保持）；两路径都经
   `_parsed_fail_closed`（FIX-001 归一化：flags 恒 False、in-scope
   ALLOWED_AUTHORIZED_PAID token 不 echo、required_scope 类型安全 echo、raw
   进 source_guard_record）；
3. validator AUTHORIZED 一致性：由 authoritative record 自身字段重建
   canonical expected scope（`scope_string(task_id, stage_agent,
   paid_candidate_model, paid_candidate_provider)`）并要求
   `required_scope == expected_scope`（组件非 str → 不满足 → ValueError）——
   validator 独立拒绝手造 AUTHORIZED out-of-scope record（Requirement 8），
   与 interpret 层修复互为防御纵深；AUTHORIZED 之外的所有既有不变量
   （matched=True⟹AUTHORIZED / BLOCKED⟹BLOCKED token / guard whitelist /
   source dict-or-None + JSON 可序列化 / FAIL_CLOSED normalized 自洽）零削弱。

## 3. Requirements → 实现映射（本 FIX 范围）

| Req | 实现 |
|---|---|
| 1 只修 exact-scope blocker | fallback_paid_gate.py（修复单元）+ fallback_runtime.py 1 调用点；无其他改动 |
| 2 复用 A0 scope authority | canonical expected scope = `cost_guard.scope_string(task_id, stage, model, provider)`；无第二 scope 格式/授权机制 |
| 3 gate 知道 task_id/stage/model/provider | interpret_guard 新 keyword-only task_id/stage（runtime 同源透传）；model/provider 既有参数 |
| 4 AUTHORIZED 条件 | model==candidate、provider==candidate、required_scope == canonical expected scope、flags 全 True、其余 A0 要求不变 |
| 5 mismatch/malformed → FAIL_CLOSED | wrong task/stage/model/provider scope 或畸形 required_scope → `_parsed_fail_closed`（scope mismatch / malformed） |
| 6 normalized/raw 分层保持 | FIX-001 `source_guard_record` 机制原样；raw 矛盾 scope 证据可观察、绝不覆盖 normalized |
| 7 fail-closed record 语义 | gate_decision=FAIL_CLOSED、authorization_* = False、attempted/used = False、零 paid invocation、artifact validator-valid + 落盘 + reload 复验 |
| 8 validator 独立 enforcing | AUTHORIZED ⟹ required_scope == scope_string(task_id, stage_agent, paid_candidate_model, provider)；手造 out-of-scope → ValueError |
| 9 聚焦测试 | wrong task / wrong stage / wrong model-provider / malformed-missing（既有增强）/ exact canonical → AUTHORIZED / 手造 AUTHORIZED 拒绝 / fail-closed 落盘复验 / raw mismatch 可观察 / 零 invocation（见 §4） |
| 10 既有行为保持 | exact auth → AUTHORIZED 零 invocation；无 paid fallback invocation；FREE 优先；unqualified 不达 gate；无第二授权系统；无 silent paid；one-fallback；A5 STARTED |
| 11 focused + canonical 回归 | §4.2 |
| 12 fresh-runner closure | §4.3（P1–P5 新进程） |
| 13 新 fix commit 不 amend | §5 |
| 14 无无关清理 / PRE_ALLOWED_UNTRACKED / no push | §5 |

## 4. 验证证据

### 4.1 修复前复现 → 修复后通过（stash 反证，scratch 不提交）

`git stash push`（仅生产文件 fallback_paid_gate.py / fallback_runtime.py，
保留新测试）→ 修复前代码跑 FIX-002 聚焦选择：
**9 failed, 51 deselected**——`test_interpret_exact_authorized`（增强断言）+
5 项解释器 scope-mismatch + 2 项 runtime + 1 项 validator 全部确定性 FAIL
（旧 interpret 把 wrong-task record 判 AUTHORIZED；旧 validator 接受
out-of-canonical-scope AUTHORIZED——Codex blocker 精确复现）。stash pop 恢复
修复后：同文件 **60 passed**（§4.2 双文件 105 passed）。

### 4.2 聚焦 + canonical 回归（Requirement 11）

- 聚焦：`tests/test_a5_paid_escalation_gate.py` **52 → 60 项（+8 新聚焦；
  3 处既有断言增强：exact-authorized required_scope 断言 / malformed-scope
  参数加空串 / 测试文件 header）** 全绿；`tests/test_a5_fallback_runtime.py`
  （A5-002 FREE fallback 45 项，gate 接线回归）全绿——双文件 **105 passed**。
- Canonical（repo 惯例：`python -m pytest -q --deselect <4 个 phase_e/f 真实
  E2E 线程文件>`——RW-029 0x80000003 环境 flake 惯例隔离，同 A3-FIX-001 /
  A5 全系报告口径）：
  **2101 passed / 1 skipped / 38 deselected（0 failed）** = HEAD 4c2ebf9
  基线（同命令 stash 复跑）**2093 + 8 精确零回归**。
  （FIX-001 报告的「16 deselected / 2115 passed」口径含 phase_e* 文件实跑；
  本会话该 4 文件触发 RW-029 已知环境 flake，按仓库惯例 4-file-deselect
  隔离——两口径下新增 8 项全部计入 passed，零回归。）

### 4.3 fresh-runner closure（Requirement 12；新进程；P1–P5 5/5）

`python tests/fresh_runner_a5_paid_escalation_gate_fix002_validation.py`
（全新 python 进程跑真实 runner + fake hermes/codebuddy/codex .bat 子进程；
wrapper 级 scripted guard 只替换 gate-time A0 求值；退出码 = 失败场景数）：

- **P1（wrong task scope）**：A0 record 的 required_scope 编码别的 task →
  gate FAIL_CLOSED「scope mismatch」；paid_escalation_gate.json 存在 +
  validator 通过；normalized matched=False / guard_decision=None；
  required_scope type-safe echo = wrong scope；source_guard_record 保留 raw
  decision=ALLOWED_AUTHORIZED_PAID + matched=True + wrong scope（可观察）；
  marker 恰 1 行 aaa-orig@custom（零 paid invocation）；无消费 marker；
  WAITING；env probe 全 -none-。
- **P2（wrong stage scope）**：同型（stage=validator）→ FAIL_CLOSED +
  artifact 落盘/valid + raw wrong-scope 可观察 + 零 paid + WAITING + env 还原。
- **P3（real A0 + exact AAF_COST_AUTH）**：gate AUTHORIZED（matched/consumed
  true、required_scope == canonical、A0 消费 marker 存在）但 marker 仍恰 1 行
  ——exact-valid authorization 行为保持、零 paid invocation、WAITING。
- **P4（pg_free_intact + real A0）**：FREE fallback 行为保持——original 失败
  → 恰一次 zzz-fb free fallback（marker 2 行）→ used=true / final=zzz-fb、
  无 gate artifact、SUCCESS、env 还原。
- **P5（脚本化 canonical exact scope）**：gate AUTHORIZED（exact
  task/stage/model/provider scope）但零 paid invocation + 无消费 marker
  （interpret 只转述 A0 flags，不 claim）+ WAITING + env 还原。

parent fresh-runner 驱动复跑（corrected code）：FIX-001 驱动 **F1–F5 5/5**
+ A5-003 驱动 **N1–N5 5/5** 全绿（A5-003 / FIX-001 行为保持）。

## 5. 改动清单 / 范围纪律 / 遗留

改动（new commit，parent = 4c2ebf9；未 amend 32c4bbe / 4c2ebf9；未 push）：
- `ai_agent_framework/fallback_paid_gate.py`（修复单元：interpret_guard
  exact-required_scope 校验 + validator canonical expected-scope 不变量 +
  文档）
- `ai_agent_framework/fallback_runtime.py`（1 个调用点：interpret_guard
  透传 task_id / stage_agent）
- `tests/test_a5_paid_escalation_gate.py`（+8 项 FIX-002 聚焦 + 既有断言增强）
- `tests/fresh_runner_a5_paid_escalation_gate_fix002_wrapper.py`（新；fresh-runner
  guard modes：wrong-task / wrong-stage / exact-scope）
- `tests/fresh_runner_a5_paid_escalation_gate_fix002_validation.py`（新；P1–P5
  driver）
- `docs/internal/AAF-v0.5-A5-PAID-ESCALATION-GATE-001-FIX-002-REPORT.md`（本文件）
- `docs/internal/PROJECT_STATE.md` / `docs/internal/AAF_MASTER_BACKLOG.md`
  （状态同步；A5 保持 STARTED / NOT CLOSED / COMPLETE）

零修改：`runner.py`、`cost_guard.py`（scope authority 原样复用）、
`fallback_contract.py`、`active_routing.py`、`workbuddy_routing.py`、
`adapters.py`、`model_registry.py`。无 paid model invocation；无第二授权系统；
A5-003 / FIX-001 已接受行为零回归。PRE_ALLOWED_UNTRACKED（`.aaf/` /
`AAF_TASK004_PROCESS_CHECK.txt` / `scripts/start_bridge_hidden.vbs`）保留未动。
遗留：paid INVOCATION = 后续 A5 任务 scope（未实现）；A5 不自行 CLOSED/COMPLETE。

## 6. 验收对照

| Acceptance | 状态 | 证据 |
|---|---|---|
| exact task/stage/model/provider scope enforced | ✅ | interpret_guard + validator 双点 canonical equality（§4.2 测试 / §4.3 P1/P2/P5） |
| wrong/malformed scope cannot become AUTHORIZED | ✅ | stash RED 反证 + P1/P2 + 解释器矩阵 |
| canonical exact scope still AUTHORIZED | ✅ | P3/P5 + 既有 AUTHORIZED 测试保持 |
| validator independently enforces exact scope | ✅ | test_gate_validator_rejects_authorized_out_of_canonical_scope（4 维 + task_id/stage_agent 手造） |
| fail-closed audit machine-readable / validator-valid / persisted | ✅ | P1/P2 artifact + reload 复验 |
| raw mismatch evidence auditable | ✅ | source_guard_record == raw（wrong scope / matched=True 原文） |
| zero paid invocation | ✅ | marker 恰 1 行（P1/P2/P3/P5）+ calls==0（runtime 测试） |
| previous A5-003 behavior intact | ✅ | parent fresh-runner N1–N5 5/5 + 聚焦/回归零失败 |
| focused tests pass / canonical regression passes | ✅ | 60 聚焦 / 双文件 105 / canonical 2101 passed 0 failed |
| fresh-runner closure passes | ✅ | P1–P5 5/5（新进程） |
| no push / no amend / PRE_ALLOWED_UNTRACKED | ✅ | §5 |
| WorkBuddy 独立验证 + Codex APPROVE | ⏳ route 阶段（本任务外） |
| Unresolved Issues | 无（本任务 scope 内） |
