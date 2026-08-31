# AAF-v0.5-A2-CLOSE-001 — A2 Shadow Routing Closure Record

> Task: Close A2 Shadow Routing（正式关闭 A2，并修正剩余的状态/边界文档矛盾）
> Executor: Hermes（AAF Executor stage）2026-08-31
> Status: **A2 = CLOSED / COMPLETE / SYNCED**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **A2 正式关闭**：A2 = **CLOSED / COMPLETE / SYNCED**（2026-08-31，
   AAF-v0.5-A2-CLOSE-001 依据已完成的 A2 Closure Audit 判定 **A2_READY_TO_CLOSE**
   正式关闭；A2-001/002/003/004 及相关 FIX 均已 APPROVED + SYNCED）。
2. ✅ **A2 formal scope 内无 remaining gap**：A2 = observation-only Shadow Routing
   的全部必需能力已交付、被接受、已同步（见 §3 能力链）。
3. ✅ **stale language 已修正**：PROJECT_STATE.md 中原「实况 qualification 观测 /
   后续 A2 slice」表述已改为正式边界——runtime qualification observation = **A2+**
   （RW-030），**不属于** A2 closure requirement，也**不是**「后续 A2 slice」。
4. ✅ **边界明确**：A2 = observation-only Shadow Routing；A2+ = runtime qualification
   observation（RW-030）；A3 = actual routing（CAP-003，NOT IMPLEMENTED，未进入）。
5. ✅ **零行为变化**：本任务为 docs-only；未修改任何 runtime / code / test /
   model registry 行为；未实现 RW-030、未开始 CAP-003、未进入 A3-A6。

## 2. Closure Decision

- **Audit decision**: A2_READY_TO_CLOSE（A2 Closure Audit 只读复核：A2 formal scope
  需求矩阵全 SATISFIED；10 项证据链闭合；A2+ / A3+ 内容显式不属于 A2）
- **A2-001**（shadow-selection engine）: APPROVED + SYNCED（commit c5e5554）
- **A2-002**（Hermes shadow observation）: APPROVED + SYNCED
- **A2-003**（explicit task-risk provenance）+ FIX-001（empty Risk 拒绝）: APPROVED + SYNCED
- **A2-004**（evidence-backed registry qualification）: APPROVED + SYNCED（commit b00c9c5）
- 本任务不重新打开任何 A2 implementation gap；历史 artifacts / verdict 不可变、不重写。

## 3. 已完成能力链（formal A2 scope）

```
selector -> runtime shadow observation -> explicit Risk provenance -> evidence-backed eligible candidate
```

| 环节 | 交付 | 证据 |
|---|---|---|
| deterministic shadow-selection engine | A2-001 `ai_agent_framework/shadow_routing.py`（纯函数、零 I/O/LLM；NO_SHADOW_CANDIDATE 显式语义） | docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-001-REPORT.md；tests/test_shadow_routing.py（47 项） |
| runtime shadow observation（Hermes observation-only bypass） | A2-002 `ai_agent_framework/shadow_observation.py` + runner Hermes-stage hook → `shadow_observation.json` | docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-002-REPORT.md；tests（26 项） |
| explicit Risk provenance（task/planner） | A2-003 TASK 可选顶层 `Risk` 字段 + immutable snapshot 透传（risk_source=TASK_RISK_SOURCE）+ FIX-001 empty-Risk fail-closed | docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-003-REPORT.md；tests（28 + 6 项） |
| evidence-backed eligible candidate | A2-004 deepseek-v4-flash@deepseek = capability_tier T2 + QUALIFIED（accepted evidence snapshot）→ HIGH Hermes shadow 产生真实 hypothetical candidate | docs/internal/AAF-v0.5-A2-SHADOW-ROUTING-004-REPORT.md；.aaf/AAF-v0.5-A2-SHADOW-ROUTING-004/（shadow_observation.json、run.json、codex_result.json） |

- **authoritative=false**（shadow 决策永不作为实际执行 authority；validate fail-closed）
- **execution_affected=false**（actual Hermes model/provider/command 不变；零额外
  provider/LLM 调用；成本守卫范围不变）
- **A3-A6 未进入**：CAP-003 actual routing = NOT IMPLEMENTED；无自动路由 / 无健康轮询 /
  无 fallback / 无动态隔离 / 无观测-校准循环。

## 4. 正式边界（A2 / A2+ / A3）

| 边界 | 内容 | 归属 |
|---|---|---|
| A2 | observation-only Shadow Routing（selector + shadow observation + Risk provenance + evidence-backed candidate） | **CLOSED / COMPLETE / SYNCED**（本任务） |
| A2+ | runtime qualification observation（RW-030：Hermes FREE 模型可用性/稳定性实况观测；FREE ≠ healthy，UNKNOWN ≠ free） | **非 A2 closure requirement**；未实现，登记于 AAF_MASTER_BACKLOG.md RW-030（OBSERVATION / P1） |
| A3 | actual routing（CAP-003 Hermes Free Auto Routing / Model Routing） | NOT IMPLEMENTED；未进入 |

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：A2 Status = CLOSED / COMPLETE / SYNCED；删除
  「实况 qualification 观测/后续 A2 slice」stale language；Next mainline 边界更新；
  Last Updated 头部更新
- `docs/internal/AAF_MASTER_BACKLOG.md`：Last Updated 头部一致性更新；RW-030
  Remaining Gap / Decision 边界措辞精确化（A2+，非 A2 slice）
- 本 closure record（docs/internal/AAF-v0.5-A2-CLOSE-001-REPORT.md）
- **零** `.py` / registry / test 文件变更（git diff 验证，见 §7）

## 6. 验收对照

- A2 正式状态 = CLOSED / COMPLETE / SYNCED ✅（PROJECT_STATE.md §0 v0.5 块 + 本 record）
- A2/A2+/A3 边界无矛盾 ✅（§4 + PROJECT_STATE.md 同步修正）
- 无 A2 implementation gap 被重新打开 ✅（本任务零代码改动，未重开任何已接受 slice）
- 无代码行为变化 ✅（git diff 仅 docs/；无 test 变更）
- WorkBuddy 独立验证：route 阶段执行，verdict 记录于本任务 REPORT
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None

## 7. 验证证据（Executor 实测）

- `git status`：仅 `.aaf/`（常驻 untracked）、`AAF_TASK004_PROCESS_CHECK.txt`、
  `scripts/start_bridge_hidden.vbs` 等既有 PRE_ALLOWED_UNTRACKED 项；tracked 变更仅
  docs/internal/ 下本任务文件（见 git diff）
- `git diff --stat`：仅 markdown 文档变更，无 `.py` / registry / test 文件
- A2-001/004 接受 commit 存在：c5e5554 / b00c9c5（本任务执行前 HEAD）；SYNC-001
  任务文件齐备（.aaf/tasks/active/AAF-v0.5-A2-SHADOW-ROUTING-00{1,2,3,4}-SYNC-001.md）
- 本任务未新增/修改任何测试（Requirement 6：不修改任何 runtime/code/test/model
  registry 行为）；无需运行测试套件（零代码变更，无回归面）
