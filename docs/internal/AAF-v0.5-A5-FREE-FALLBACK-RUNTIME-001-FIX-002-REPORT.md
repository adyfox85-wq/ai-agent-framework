# AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002 — Fix Report

> Task: Harden fallback audit closure exception boundary
> （修复 AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-001 的唯一 Codex blocker：
> fallback 第二模型已实际 invocation 后，任何 audit validation / serialization /
> persistence 异常都必须被统一收口为显式 fail-closed 结果，并保留
> attempted=true / used=false / no-third-invocation 语义）
> Executor: Hermes（AAF Executor stage）2026-09-03
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE = 接受前置条件）
> Baseline: HEAD = local `8b3c24b4b90a4bec5ae1680a9b354c2828b2740e`（parent = `a0ac326630d68af4dac3b271429d3120cf412b57`；本任务**新提交、不 amend parent**）

## 1. 结论（先给结论）

1. ✅ **Codex 唯一 blocker 收口——post-invocation authoritative audit closure
   现在是 exception-safe 的 fail-closed 边界**（TASK Requirement 1/2/3/4/5）：
   `_emit()` 原只捕获 `(ValueError, TypeError, OSError)`，audit validator /
   序列化 / 持久化抛出未预期的 `RuntimeError` / `UnicodeError` / 其他实现或
   runtime 异常时（UnicodeError ⊂ ValueError 已被旧 catch 覆盖，但
   RuntimeError、KeyError、自定义异常等全部可逃逸），异常会在 fallback 第二
   模型已实际 invocation（attempted=true 已置位）之后裸逃逸出
   `run_fallback_after_failure` —— runner 的宽泛 except 只打印泛化
   `[a5-fallback] layer error`，`audit_closure_error` 返回路径无法执行，
   attempted=true 事实、audit closure failure 与 fallback overlay env 还原
   全部丢失（无 A3 routing overlay 的调用情形中 env 泄漏）。修复 = 双层边界：
   - ① `_emit` 的 catch 拓宽为 `Exception`——audit 组装（含 validator）/
     序列化 / 持久化中**任何**异常都是 audit closure 失败 → 记入
     `emit_failure` + 返回 None（绝不裸逃逸）；
   - ② 自 `ALLOWED_FREE` admission（第二模型 invocation 真实发生、
     attempted=true 不可撤销）起，整个 invocation + audit closure 段由兜底
     fail-closed 边界包裹——任何未被内层捕获的意外逃逸（如输出接受判定
     `_output_is_valid` 的异常）都转为同样的结构化 fail-closed 结果。
   - 两条路径统一返回：`attempted=true` / `used=false`（fallback 输出**绝不**
     被接受）/ `result_text=None`（runner 保留原始 FRAMEWORK_ERROR）/
     `audit_closure_error`（含真实异常类型 + 消息，显式 surface）/
     `overlay_saved`（调用方照常观察后还原 env）——无第三模型、无进一步
     fallback retry；原始失败上下文保留。
   - 边界之外（admission 之前、无 attempt 发生）的 pre-invocation 编程错误
     不在此捕获（Requirement 5——不吞无关错误，原语义保持）。
2. ✅ **runner 消费结构化 outcome，不降级为泛化 "layer error"**（Requirement
   6）：runner.py 零改动——FIX-001 已有的结构化消费点（`audit_closure_error`
   → stderr + stage result 文本 `FRAMEWORK_ERROR[a5-fallback audit closure
   failed]`）原样消费新 outcome；由于 fallback 层现在对 post-invocation
   audit-closure 失败**只返回结构化结果、绝不 raise**，runner 的 layer-error
   分支只可能在 pre-invocation 编程错误时触发（此时无 attempt、无 overlay，
   原语义正确）。
3. ✅ **FIX-001 行为全部保持**（Requirement 8/9）：`ALLOWED_AUTHORIZED_PAID`
   不能作为 FREE fallback 执行 / `AAF_COST_AUTH` 不能启用 paid fallback /
   仅 `ALLOWED_FREE` 可达第二模型 invocation / zero paid escalation
   实现——全部保持并被 FIX-002 fresh-runner G4（authorized-paid refused）在
   新进程中复证；exactly-one / no-chain / no-third-model / same-model
   transport retry 分离 / aux+unknown 排除 / A3 初始 routing 零修改保持。
4. ✅ **测试**（Requirement 7）：`tests/test_a5_fallback_runtime.py` 新增 6 项
   FIX-002 聚焦（4 项 fault-injection 单元：validator 抛 RuntimeError /
   persistence 抛 RuntimeError / persistence 抛 UnicodeError / post-
   invocation 兜底边界（输出接受判定抛 RuntimeError）——均证明 attempted=
   true / used=false / result_text=None / audit_closure_error surface /
   无第三模型（恰 1 次 fallback invocation）/ env 还原；2 项真实 runner
   集成：persistence RuntimeError 与 validator RuntimeError → 结果文本显式
   append `FRAMEWORK_ERROR[a5-fallback audit closure failed]`（非 "layer
   error"）、无 artifact、WAITING、env 还原）+ 全量 non-GUI 4-file-deselect
   **2041 passed / 1 skipped / 38 deselected** = HEAD（8b3c24b）基线 **2035 +
   6 精确零回归**（stash 反证：5/6 新测试对未修复代码确定性 FAIL——旧路径确
   以 `[a5-fallback] layer error: RuntimeError: ...` 裸逃逸；UnicodeError
   注入测试对未修复代码已通过（UnicodeError ⊂ ValueError），其作用是锁定
   Requirement 7 要求本身）。
5. ✅ **Fresh-runner 全新进程验证**（Requirement 11）：新驱动 **4/4** 全绿
   （G1 validator RuntimeError / G2 persistence RuntimeError / G3
   persistence UnicodeError / G4 authorized-paid refused）——每个场景全新
   python 进程运行真实 runner + fake hermes/codebuddy/codex 真实 child
   CLI，证据见 §5。
6. ✅ **状态文档按需更新**（Requirement 12/13）：A5 保持 **STARTED**（NOT
   CLOSED / COMPLETE——REQUIRED_BEFORE_A5_CLOSE 9 项不重写：free→paid
   escalation 路径 / Cost Gate UX 未开始，本 FIX 只修复已交付 runtime 单元
   的 audit-closure 异常边界缺陷）；PROJECT_STATE header + A5 实现状态
   bullet + backlog CAP-003/CAP-004/§7 相关行同步；A6 / A4+ 边界保持
   outside；A0-A4 不重开。
7. ✅ **范围纪律**（Requirement 13）：无无关清理；PRE_ALLOWED_UNTRACKED
   （.aaf/、AAF_TASK004_PROCESS_CHECK.txt、scripts/start_bridge_hidden.vbs）
   保留；本任务改动 = fallback_runtime.py（修复单元，唯一生产代码修改；
   runner.py 零改动）+ 测试 3 文件 + docs 3 文件；no push。

## 2. 修复设计

### 2.1 Blocker 根因（Codex REQUEST_CHANGE）

Codex 定位：`_emit()`（fallback_runtime.py）只捕获 `ValueError / TypeError /
OSError`：

- fallback_runtime.py 已把 `attempted=True` 并实际调用第二模型后，若 audit
  validator、序列化或持久化实现抛出其他异常（例如 `RuntimeError`、
  `UnicodeError`——后者虽是 ValueError 子类但异常面远不止此：KeyError /
  自定义实现异常等全部逃逸），`_emit()` 异常裸逃逸 → 1263 行的
  `audit_closure_error` 返回路径无法执行 → runner 的宽泛异常处理只打印
  `layer error`（runner.py:663），不把 audit closure failure 加入 stage
  result，也无法取得 `fallback_overlay_saved` → 机器/阶段结果无法表达已经
  发生的 attempted=true / used=false，违反"不得假装 invocation 没发生"和
  "不得静默丢弃 audit failure"；无 A3 routing overlay 的调用情形中 fallback
  env 覆盖无法由该路径还原。

### 2.2 修复（双层 fail-closed 边界，全部落在 fallback_runtime.py）

**① `_emit` catch 拓宽为 `Exception`**（audit closure 内层边界）：

```python
except Exception as exc:  # noqa: BLE001 — FIX-002：audit closure 边界
    # assemble（含 validator）/ 序列化 / 持久化的任何未预期实现/runtime
    # 异常（RuntimeError / UnicodeError / KeyError ...）都是 audit closure
    # 失败 → 统一收口（emit_failure 记录），绝不作为裸异常逃逸
    emit_failure[:] = [f"{type(exc).__name__}: {_excerpt(str(exc))}"]
```

- 该 catch 的作用域 = `_emit` 函数体（audit record 组装/校验/序列化/持久化）
  —— audit closure 机制本身的任何失败**按定义**就是 audit closure 失败，
  无论调用发生在 invocation 前（→ record=None → 返回 None /
  _no_attempt_result，不发起第二模型，fail closed）还是 invocation 后
  （→ record=None → 结构化 fail-closed 返回）；这不构成对 pre-invocation
  无关编程错误的吞没（Requirement 5 边界保持：_emit 之外的 admission/
  decision 错误仍按原语义处理）。

**② post-invocation 兜底 fail-closed 边界**（外层边界，Requirement 1/4/5）：

自 `ALLOWED_FREE` admission 分支起（attempted=true 置位前一刻）到函数返回，
整个 invocation + audit closure 段包进 `try/except Exception`：

- 内层 `invoke` 的 `except Exception` 语义不变（invocation 失败 = 失败的
  fallback attempt：attempted=true / used=false，仍走权威 audit closure
  持久化一条如实记录）。
- 外层兜底捕获任何其他逃逸（如 `_output_is_valid` 抛异常、evidence 文本
  构造异常等未预期实现/runtime 错误）→ 转为结构化 fail-closed 返回：
  `attempted=true` / `used=false` / `result_text=None`（原始失败保留）/
  `audit_closure_error`（"unexpected <Type>: <msg> escaped inside the
  post-invocation authoritative audit closure boundary ..."）/ 
  `overlay_saved`（env 还原路径保留）。
- 两条收口路径都不发起第三模型、不重试另一个 fallback、不静默丢弃 audit
  failure（Requirement 3/4）。

**runner 消费**（Requirement 6）：无需改动——FIX-001 已实现的结构化消费
（`audit_closure_error` → stderr 打印 + 追加 stage result 文本
`FRAMEWORK_ERROR[a5-fallback audit closure failed]: ...`，attempt 证据持久化
到 hermes_result.md，链语义照常 fail closed → WAITING）对新 outcome 原样
生效；runner 的 `[a5-fallback] layer error` 分支从此只可能是 pre-invocation
编程错误（无 attempt、无 env overlay，正确语义）。

## 3. 实际修改

| 文件 | 改动 |
|---|---|
| `ai_agent_framework/fallback_runtime.py` | 修复单元（唯一生产代码修改）：模块 docstring + `run_fallback_after_failure` docstring 增补 FIX-002 语义；`_emit` catch 拓宽 `Exception`；ALLOWED_FREE admission 之后的 invocation + audit closure 段加兜底 fail-closed 边界（外 except → 结构化 fail-closed 返回） |
| `tests/test_a5_fallback_runtime.py` | +6 项 FIX-002 聚焦测试（4 单元 fault-injection + 2 真实 runner 集成），见 §4 |
| `tests/fresh_runner_a5_free_fallback_fix002_wrapper.py` | 新 fresh-runner wrapper（FIX-002 fault 注入 env + 进程结束 env probe） |
| `tests/fresh_runner_a5_free_fallback_fix002_validation.py` | 新 fresh-runner 驱动（G1–G4） |
| `docs/internal/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002-REPORT.md` | 本报告 |
| `docs/internal/PROJECT_STATE.md` | header Last Updated + A5 实现状态 bullet（FIX-002 条目） |
| `docs/internal/AAF_MASTER_BACKLOG.md` | CAP-003 全套行 + CAP-004 Do Not Forget + §7 summary 行的 FIX-002 同步 |

零修改（byte-identical）：`fallback_contract.py` / `cost_guard.py` /
`active_routing.py` / `workbuddy_routing.py` / `adapters.py` /
`model_registry.py` / `runner.py`。

## 4. 测试证据（Requirement 7/10）

### 4.1 聚焦 fault-injection（tests/test_a5_fallback_runtime.py，+6）

| 测试 | 注入 | 断言（全部通过） |
|---|---|---|
| `test_fix002_validator_runtime_error_after_fallback_success` | `validate_fallback_runtime_record` 在 attempted 时抛 RuntimeError | calls==1（无第三模型）/ attempted=true / used=false / result_text=None / audit_record=None / artifact_ref=None / audit_closure_error 含 "audit closure"+"RuntimeError"+注入消息 / 无 artifact 落盘 / env 还原 |
| `test_fix002_audit_persistence_runtime_error_after_fallback_success` | `save_fallback_runtime` 抛 RuntimeError | 同上（含 RuntimeError 消息） |
| `test_fix002_audit_persistence_unicode_error_after_fallback_success` | `save_fallback_runtime` 抛 UnicodeError | 同上（含 UnicodeError 消息） |
| `test_fix002_unexpected_post_invocation_escape_fail_closed` | `_output_is_valid` 抛 RuntimeError（_emit 之外的逃逸） | 同上 + audit_closure_error 含 "escaped inside the post-invocation"（兜底边界证明） |
| `test_runner_fix002_persistence_runtime_error_not_reduced_to_layer_error` | 真实 runner + save 抛 RuntimeError | hermes_calls==2（original + 恰一次 fallback）/ result 以 FRAMEWORK_ERROR 开头 + 含 `FRAMEWORK_ERROR[a5-fallback audit closure failed]`（结构化消费，非 layer error）/ 无 artifact / WAITING / env 还原 |
| `test_runner_fix002_validator_runtime_error_fail_closed` | 真实 runner + validator 抛 RuntimeError | 同上 |

**stash 反证**：对未修复代码（HEAD 8b3c24b 的 fallback_runtime.py）运行上述
测试 = **5 failed / 1 passed**（5 项 RuntimeError/UnicodeError 注入全部
FAIL——旧路径确以 `[a5-fallback] layer error: RuntimeError: ...` 裸逃逸；
UnicodeError 项通过因为它本就被旧 catch 的 ValueError 覆盖——该项是
Requirement 7 的锁定测试）。

### 4.2 全量 non-GUI 回归

`python -m pytest -m "not gui_e2e"`（pytest.ini addopts 默认排除 38 项
gui_e2e；另按项目惯例 4-file-deselect）：
**2041 passed / 1 skipped / 38 deselected** = HEAD 8b3c24b 基线 **2035 + 6
精确零回归**。

## 5. Fresh-runner N+1（全新进程；Requirement 11）

驱动：`python tests/fresh_runner_a5_free_fallback_fix002_validation.py`
退出码 = 失败场景数 = **0（4/4 全绿）**。证据：
`.aaf/AAF-v0.5-A5-FREE-FALLBACK-RUNTIME-001-FIX-002/fresh-runner-validation/`
（不提交）。每个场景 = 全新 python 进程跑真实 runner
（fresh_runner_a5_free_fallback_fix002_wrapper.py）+ fake hermes/codebuddy/
codex 真实 child CLI；hermes chat 每次 invocation 向 marker append
`MODEL=<model>@<provider>`；wrapper 在 runner 进程结束前打印
`AAF_ENV_PROBE|...`（same-process env 还原证明）。

- **G1（validator RuntimeError）**：`fb_success` + aaa-orig 失败 +
  `AAF_TEST_AUDIT_VALIDATE_FAULT=runtime_error` → marker 恰 2 行
  （aaa-orig@custom 原始失败 + zzz-fb@custom fallback attempt 真实发生、
  无第三模型）；hermes_result.md = `FRAMEWORK_ERROR`（原始失败保留）+
  `FRAMEWORK_ERROR[a5-fallback audit closure failed]: ... attempted=true;
  RuntimeError: FIX-002 simulated authoritative audit validator
  RuntimeError ... used=false, fail closed`；无 fallback_runtime.json
  （权威 audit 未落盘）；run=WAITING；codebuddy 未 spawn（无 chain）；
  stderr 无 "layer error"；env probe 三行全 `-none-`（还原）。
- **G2（persistence RuntimeError）**：`AAF_TEST_AUDIT_SAVE_FAULT=runtime_error`
  → 同 G1 断言形状全绿。
- **G3（persistence UnicodeError）**：`AAF_TEST_AUDIT_SAVE_FAULT=unicode_error`
  → 同 G1 断言形状全绿。
- **G4（authorized-paid refused——FIX-001 保护新进程复证）**：
  `fb_paid_admission` + 精确 `AAF_COST_AUTH` → hermes chat 恰 1 次
  （marker 无 zzz-free@remote-api 行）；audit attempted=false /
  used=false / authorization_outcome=ALLOWED_AUTHORIZED_PAID / eligible=true /
  final==original / evidence "was NOT invoked"；cost_auth_consumed.json 存在
  （A0 按既有一次性语义在 admission 边界 claim）；run=WAITING；codebuddy 未
  spawn；env probe 全 `-none-`。

## 6. 状态与边界（Requirement 8/9/12/13）

- A5 = **STARTED**（NOT CLOSED / COMPLETE——REQUIRED_BEFORE_A5_CLOSE 9 项
  不重写：free→paid escalation 路径 / Cost Gate UX 未开始）。
- FIX-001 语义全部保持并被 G4 复证：ALLOWED_AUTHORIZED_PAID 不能作为 FREE
  fallback 执行 / AAF_COST_AUTH 不能启用 paid fallback / 仅 ALLOWED_FREE
  可达第二模型 invocation / zero paid escalation 实现。
- exactly-one fallback / no chain / no third model / same-model transport
  retry（RW-027）分离 / aux+unknown 排除 / A3 初始 routing 零修改 / A0 Paid
  Guard 权威零修改——全部保持。
- A6（health/quarantine/requalification）与 A4+（HIGH/CRITICAL/Codex
  routing）边界保持 outside；A0-A4 不重开。
- PRE_ALLOWED_UNTRACKED（.aaf/、AAF_TASK004_PROCESS_CHECK.txt、
  scripts/start_bridge_hidden.vbs）保留，无删除。
- No push（本任务提交 = 本地新 commit，parent 8b3c24b 未 amend）。

## 7. Unresolved Issues

- None（本 executor 阶段确认无剩余问题；WorkBuddy 独立验证 + Codex APPROVE
  由 route 执行）。
