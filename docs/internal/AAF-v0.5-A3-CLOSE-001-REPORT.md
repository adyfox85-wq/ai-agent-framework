# AAF-v0.5-A3-CLOSE-001 — A3 Hermes Free Auto Routing Closure Record

> Task: Close A3 Hermes Free Auto Routing（正式关闭 A3，并修正剩余的状态/边界文档矛盾）
> Executor: Hermes（AAF Executor stage）2026-09-01
> Status: **A3 = CLOSED / COMPLETE / SYNCED**
> Route: Hermes -> WorkBuddy -> Codex（WorkBuddy 独立验证 + Codex APPROVE 为接受前置条件，按 route 阶段执行）

## 1. 结论（先给结论）

1. ✅ **A3 正式关闭**：A3 = **CLOSED / COMPLETE / SYNCED**（2026-09-01，
   AAF-v0.5-A3-CLOSE-001 依据已完成的 A3 Scope / Closure Audit 判定
   **A3_READY_TO_CLOSE** 正式关闭；A3-001 + FIX-001 = COMPLETE / APPROVED /
   SYNCED，A3 formal scope 内无 remaining gap）。
2. ✅ **能力链完整交付**：A3 = LOW-risk Hermes FREE active routing——explicit
   LOW Risk -> qualified FREE/LOCAL_FREE selection -> authoritative active
   routing -> real Hermes invocation（见 §3 能力链）。
3. ✅ **stale language 已修正**：PROJECT_STATE.md 中原「A3 = STARTED / 等待
   WorkBuddy+Codex+Planner 判定」与把 MEDIUM/HIGH routing、fallback、health 等
   误写为「A3 后续范围」的表述已全部改为正式边界。
4. ✅ **边界明确**：A3 = LOW-risk Hermes FREE active routing（已关闭）；A4 =
   WorkBuddy/economic/multi-agent routing；A5 = fallback / Cost Gate UX；A6 =
   observation/calibration/runtime requalification——A4-A6 均 NOT IMPLEMENTED、
   未进入；MEDIUM/HIGH 自动模型选择属 A4-A6（broader model routing）。
5. ✅ **零行为变化**：本任务为 docs-only；未修改任何 runtime / code / test /
   model registry 行为；未开始 A4/A5/A6。

## 2. Closure Decision

- **Audit decision**: A3_READY_TO_CLOSE（已完成的 A3 Scope / Closure Audit：
  A3 formal scope 需求全 SATISFIED；A3-001 + FIX-001 均 APPROVED + SYNCED；
  A3 formal scope 内无 remaining gap）
- **A3-001**（LOW-risk Hermes FREE active routing 首片）: APPROVED + SYNCED
  （commit 2e412517ac22a4aa06b991b4e657ea1accf7b42d）
- **FIX-001**（FREE_PROMO 严格排除）: APPROVED + SYNCED（commit
  06fbaf12d905c8f5d6884edff4b2b7ee746e8640；SYNC-001 fast-forward
  8c30d55..06fbaf1 同步 origin/main）
- 本任务不重新打开任何 A3 implementation gap；历史 artifacts / verdict
  不可变、不重写。

## 3. 已完成能力链（formal A3 scope）

```
explicit LOW Risk -> qualified FREE/LOCAL_FREE selection -> authoritative active routing -> real Hermes invocation
```

| 环节 | 交付 | 证据 |
|---|---|---|
| authoritative active routing decision | `ai_agent_framework/active_routing.py`（**复用现有 A2 selector / A1 registry / risk_contract 词汇，不创建第二套路由判断**；activation gates：agent=hermes + role=executor + 显式 Risk: LOW + selector eligible + selected cost_class ∈ FREE_OF_COST_CLASSES + qualification=QUALIFIED） | docs/internal/AAF-v0.5-A3-HERMES-FREE-ROUTING-001-REPORT.md；tests/test_active_routing.py（31 项，Req 10 全矩阵） |
| runner Hermes stage 集成 | Paid Guard 求值前决策；routing_applied=true → 设置 AAF_HERMES_MODEL=qwen3:4b / AAF_HERMES_PROVIDER=custom / AAF_HERMES_BASE_URL=http://127.0.0.1:11434/v1 覆盖，observation 后精确还原；adapters 透传 -m/--provider | tests/test_active_routing.py（runner 集成 5 项 + env apply/restore）；fresh-runner N+1（.aaf/AAF-v0.5-A3-HERMES-FREE-ROUTING-001/fresh-runner-validation/，N1-low-routed） |
| real Hermes invocation | N1 Risk: LOW 真实 runner 进程 → fake hermes chat 真实子进程可见 MODEL=qwen3:4b / PROVIDER=custom / BASE_URL=http://127.0.0.1:11434/v1，全链 SUCCESS | .aaf/.../fresh-runner-validation/N1-low-routed/（active_routing.json / cost_guard.json / shadow_observation.json / run.json） |

- **FREE_PROMO excluded**（FIX-001）：active routing cost gate 使用新的
  ACTIVE_ROUTING_COST_CLASSES = {FREE, LOCAL_FREE}（严格子集），FREE_PROMO
  永不进入 active routing——selector 可能选中 FREE_PROMO 候选（A1 一般 0-cash
  语义不变），但 A3 authority 拒绝（reason=SELECTED_NOT_FREE + 显式
  FREE_PROMO + strict set 记录于 audit），configured Hermes model/provider 保持。
- **non-LOW / missing 保持 configured**：Risk 缺失（RISK_UNAVAILABLE）/
  MEDIUM/HIGH/CRITICAL（RISK_NOT_LOW）/ 无候选（NO_SHADOW_CANDIDATE）/ 非 FREE
  （SELECTED_NOT_FREE）→ routing_applied=false，configured
  deepseek-v4-flash@deepseek 原样。
- **no silent fallback**：fallback_attempted 恒 false + validate fail-closed；
  routing 后 invocation 失败 → 如实 FRAMEWORK_ERROR → WAITING，绝不自动改模型。
- **Paid Guard preserved**：routed LOCAL_FREE 经**既有** classify_cost loopback
  判定（registry evidence-backed base_url → 127.0.0.1）→ ALLOWED_FREE 零授权
  零 claim；非免费路径继续遵循 A0（N2 control：deepseek 仍需精确
  AAF_COST_AUTH）；fake-local URL 对抗测试证明 AAF_HERMES_BASE_URL 不是 FREE
  后门。
- **active vs shadow artifacts 可区分**：active_routing.json（authoritative=true，
  decision_kind=active_routing，risk+provenance / considered / eligible /
  selected / routing_applied / routed+configured model+provider / reason /
  fallback_attempted）与 shadow_observation.json（authoritative=false，
  hypothetical）并存；stage result 同时携带 active_routing_ref +
  shadow_observation_ref。
- **A4-A6 未进入**：无 WorkBuddy/Codex routing、无 MEDIUM/HIGH 自动模型选择、
  无 fallback、无 health polling / quarantine、无 automatic qualification
  promotion、无 observation-calibration 循环。

## 4. 正式边界（A3 / A4 / A5 / A6）

| 边界 | 内容 | 归属 |
|---|---|---|
| A3 | LOW-risk Hermes FREE active routing（explicit LOW Risk -> qualified FREE/LOCAL_FREE selection -> authoritative active routing -> real Hermes invocation；FREE_PROMO excluded；non-LOW/missing 保持 configured；no silent fallback；Paid Guard preserved） | **CLOSED / COMPLETE / SYNCED**（本任务） |
| A4 | WorkBuddy/economic/multi-agent routing（含 broader / MEDIUM-HIGH 模型路由与 cheapest-model selection、WorkBuddy RemoteConfig 解析与经济路由） | NOT IMPLEMENTED；未进入 |
| A5 | fallback / Cost Gate UX（automatic fallback、free→paid switching、user confirmation dialog、图形化 Cost Gate UX） | NOT IMPLEMENTED；未进入 |
| A6 | observation/calibration/runtime requalification（health polling / quarantine、automatic qualification promotion、观测-校准循环） | NOT IMPLEMENTED；未进入 |

- MEDIUM/HIGH 自动模型选择 = A4-A6（broader model routing），**不是** A3
  remaining scope。
- Hermes free-model 可用性/稳定性（FREE ≠ healthy）持续登记于
  AAF_MASTER_BACKLOG.md RW-030（OBSERVATION / P1，A2+ 实况观测），不因 A3
  关闭而改变。

## 5. 变更清单（docs-only）

- `docs/internal/PROJECT_STATE.md`：A3 Status = CLOSED / COMPLETE / SYNCED；
  删除「A3 = STARTED / 等待 WorkBuddy+Codex+Planner 判定」stale language；
  「A3 后续范围（MEDIUM/HIGH 自动选择 / fallback / health / quarantine /
  promotion）」改为正式边界（A4-A6 future phases）；Next mainline 与
  Last Updated 头部更新
- `docs/internal/AAF_MASTER_BACKLOG.md`：CAP-003 Status = IMPLEMENTED（A3
  slice）/ NOT IMPLEMENTED（broader，属 A4-A6）；Current Implementation /
  Remaining Gap / Do Not Forget 边界措辞精确化；Summary 表 CAP-003 行更新；
  RW-030 Remaining Gap / Decision 一致性修正（A3 已关闭，非「未启动」）；
  CAP-004 Do Not Forget 精度修正（完整 Model Routing 仍 NOT IMPLEMENTED，
  仅 A3 LOW slice 已实现）；Last Updated 头部更新
- 本 closure record（docs/internal/AAF-v0.5-A3-CLOSE-001-REPORT.md）
- **零** `.py` / registry / test 文件变更（git diff 验证，见 §7）

## 6. 验收对照

- A3 正式状态 = CLOSED / COMPLETE / SYNCED ✅（PROJECT_STATE.md §0 v0.5 块 +
  本 record）
- CAP-003 LOW Hermes FREE active routing 标记 IMPLEMENTED ✅
- A3 与 A4-A6 边界无矛盾 ✅（§4 + PROJECT_STATE.md / backlog 同步修正）
- 无代码行为变化 ✅（git diff 仅 docs/；无 test 变更）
- WorkBuddy 独立验证：route 阶段执行，verdict 记录于本任务 REPORT
- Codex APPROVE：route 阶段执行
- Unresolved Issues = None

## 7. 验证证据（Executor 实测）

- `git status`：仅 `.aaf/`（常驻 untracked）、`AAF_TASK004_PROCESS_CHECK.txt`、
  `scripts/start_bridge_hidden.vbs` 等既有 PRE_ALLOWED_UNTRACKED 项；tracked
  变更仅 docs/internal/ 下本任务文件（见 git diff）
- `git diff --stat`：仅 markdown 文档变更，无 `.py` / registry / test 文件
- A3-001 / FIX-001 接受 commit 存在：2e412517... / 06fbaf12...（本任务执行前
  HEAD）；SYNC-001 证据齐备（.aaf/AAF-v0.5-A3-HERMES-FREE-ROUTING-001-SYNC-001/
  REPORT.md Current Status = SUCCESS：fast-forward 8c30d55..06fbaf1 非 force、
  无文件修改、无新 commit）
- 本任务未新增/修改任何测试（Requirement 7：不修改任何 runtime/code/test/model
  registry 行为）；无需运行测试套件（零代码变更，无回归面）
