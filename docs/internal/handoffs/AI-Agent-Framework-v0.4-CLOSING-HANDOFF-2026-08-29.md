# AI Agent Framework — v0.4 FINAL HANDOFF / CLOSING HANDOFF

- Date: 2026-08-29
- Type: Final Version Closing Handoff（v0.4 最终交接，FROZEN，不持续覆盖）
- Task: AAF-v0.4-FREEZE-001（Freeze and Final Package）
- Predecessor: docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-D-CLOSURE-2026-08-27.md
  （以及 Phase A/B/C closure handoffs）
- Authoritative state: docs/internal/PROJECT_STATE.md（顶部 v0.4 块）
- Acceptance evidence: `.aaf/AAF-v0.4-FINAL-ACCEPTANCE-002/`（REPORT.md + codex_result.md）

---

## 1. v0.4 目标

> 在 v0.3（Task Automation / Session Continuity / Project Boundary）基础上，构建
> **Desktop Shell MVP / Runtime Observability & Control**：
> A. Runtime State Foundation — B. Bridge Background / Tray Skeleton —
> C. Status Window + Chinese-first UI — D. Progress Visualization —
> E. Safe Cancel Lifecycle — F. Project Switching / Duplicate Task UX —
> 外加 Runtime Integrity / Bridge Reliability / Model Observability /
> WorkBuddy Stage Reliability 收口。

## 2. 当前最终状态

```
Version: v0.4
Status: FROZEN / RELEASE READY
Release Status: FROZEN（2026-08-29，AAF-v0.4-FREEZE-001）
Final Acceptance: PASS（AAF-v0.4-FINAL-ACCEPTANCE-002，2026-08-29）
Current Status: SUCCESS（Route: codex；Codex = APPROVE；Unresolved Issues = None）
Remote Sync: SYNCED（ahead/behind = 0/0；tracked tree clean）
```

## 3. Baseline / Freeze Metadata

| 项 | 值 |
|---|---|
| Accepted Implementation Baseline | `1d3771fe8220e1b2e21c774840d680ec9f2dce61` |
| Final Freeze Metadata Commit | docs-only 提交（PROJECT_STATE / backlog / policy / handoff；SHA 见 git tag `v0.4` 指向的提交，记录于 PROJECT_STATE §0 顶部） |
| Git Tag | `v0.4`（lightweight，对齐仓库既有 `v0.2.0-rc1` 惯例；指向 final freeze/release commit，未覆盖任何已有 tag） |
| 冻结边界 | 无新功能代码；freeze 仅文档 / tag / release metadata |

## 4. Release Closure Matrix（Final Acceptance-002 确认）

| Area | Status |
|---|---|
| Desktop Shell A–F | COMPLETE |
| Runtime Integrity（RW-020 / RW-022） | CLOSED |
| Safe Cancel（Phase E / 005-A/B/C + FIX） | COMPLETE |
| Bridge Reliability（RW-008 / RW-012） | CLOSED |
| Model Observability / Discovery | IMPLEMENTED |
| WorkBuddy Stage Reliability（RW-027） | SOLVED |
| GUI automated-test isolation（RW-026） | ACCEPTED |

## 5. 主要完成领域（v0.4）

- **Phase A** Runtime State Foundation（task.json live canonical runtime view；统一 Runtime State reader；legacy 兼容）
- **Phase B** Bridge Background / Tray（pythonw 无控制台常驻；单实例 mutex；Ctrl+Alt+A 热键全链路；restart/exit 回归）
- **Phase C** Status Window + Chinese-first UI（只读观察；六阶段条事实映射；Tray 接入）
- **Phase D** Progress Visualization（真实 Windows E2E）
- **Phase E** Safe Cancel Lifecycle（soft cancel + force cancel + ownership verification + canonical force authority + timezone-compatible elapsed contract；真实 Windows 正负 E2E）
- **Phase F** Project Switching + Duplicate Task UX（workspace 分类提交流程；atomic config persistence；真实 UI harness；RW-003 / RW-016 / RW-006 SOLVED）
- **Runtime Integrity**（RW-020 Dead Runner Detection SOLVED；RW-022 Final Status Truth SOLVED）
- **Bridge Reliability**（RW-008 parser SOLVED；RW-012 hotkey listener lifecycle SOLVED——单一 lifecycle authority、有界 backoff、TOCTOU 全收口）
- **Model Observability / Discovery**（只读事实层；model_observation.json 单一 machine authority；动态发现权威）
- **WorkBuddy Stage Reliability**（RW-027 SOLVED——bounded transient retry / confirmed-dead-before-retry / single absolute stage deadline / Windows tree cleanup authority / safe cleanup reserve / attempt admission / telemetry）

测试基线（Final Acceptance 时）：全量 non-GUI 1289 passed / 1 skipped / 9 deselected（gui_e2e 结构性排除）。

## 6. 重要架构不变量（invariants）

1. TASK = formal input；task.json = machine lifecycle state；REPORT = execution result；边界不互相越权。
2. Validation / 聚合 **fail closed**（malformed / missing / invalid → 不 fail-open）。
3. 热键 listener **单一 owner**；recovery 有界；shutdown 期间不恢复不复活；任意时刻至多一个 CodeBuddy 进程。
4. 模型观测是**只读事实层**，观测不是 execution authority；不实现 routing / cost gate / 自动切换。
5. `.aaf/` 为 runtime/history evidence，不入 repository；历史 artifacts 不删除、不重写。
6. GitHub = 正式知识权威；Obsidian = Working Knowledge / Conversation Handoff 层。

## 7. 已知 Deferred 项（v0.4 non-blocking）

| 项 | 分类 |
|---|---|
| RW-021 Bridge Restart/Exit completion notification continuity | DEFERRED / OPEN P2 |
| RW-028 early validation（enter=2）diagnostics visibility | DEFERRED P2 diagnostics UX / non-blocking |
| Windows 0x80000003 pytest test-env observation（RW-029） | DEFERRED / NON-BLOCKING observation |
| RW-023（E2E 固定 Task ID）、RW-025（时钟 flake）、RW-013、RW-014 等 | 既有登记项，保持原状态 |

## 8. Future Scope（明确 NOT IMPLEMENTED，不属于 v0.4）

- Automatic Model Routing —— **NOT IMPLEMENTED**（backlog CAP-003）
- Model Registry / Cost policy extensions —— NOT IMPLEMENTED
- Cost Gate —— **NOT IMPLEMENTED**
- Free/Paid routing logic —— NOT IMPLEMENTED

未来政策（已登记 backlog CAP-003）：满足质量与风险阈值前提下优先最低现金成本模型；
LOCAL_FREE / FREE / FREE_PROMO 优先；**Free → Paid 必须显式用户确认**（Cost Gate）；
动态模型/免费/倍率元数据必须先刷新再决策。

## 9. 运营风险（external operational dependency，非 v0.4 correctness blocker）

**A. 外部 WorkBuddy/CodeBuddy availability 可波动**（placeholder empty output / long latency / timeout）。
Framework 现处理：retries bounded（initial + 1，可配）、fail closed、process cleanup safe
（tree confirmed 才允许 retry）、无 unsafe overlap（Registry Gate）、记录 telemetry
（workbuddy_attempts.json）。这是 external operational dependency，不是已知 v0.4 correctness blocker。

**B. Windows 全量 pytest 环境曾出现 0x80000003**（RW-029）。
当前无证据证明正常生产 AAF runtime 必然受影响。分类：**DEFERRED / NON-BLOCKING observation**
（除非 repository 证据另有说明）。

**C. Early validation error UI 可能只显示 enter=2**（RW-028）。
Validation fail-closed correctness 已确认。分类：**P2 diagnostics UX / non-blocking**。

## 10. Model Observability Final State

- Model Observability = **IMPLEMENTED**
- Model Discovery = **IMPLEMENTED（以真实 CLI/interface 能力为限）**
- 动态发现（dynamic discovery）保持权威；以下为 **dated observations**（2026-08-29），
  不是硬编码永久事实：

| Agent | observed version | model / provider |
|---|---|---|
| Hermes | v0.20.5 | model = deepseek-v4-flash（此前观测），provider = deepseek |
| WorkBuddy（CodeBuddy） | 2.141.0（`codebuddy --version` 动态 probe） | model/provider 可保持 UNKNOWN（config 不暴露） |
| Codex | codex-cli 0.150.0-alpha.12.2 | model/provider 可保持 UNKNOWN（server-side 不可枚举 limitation） |

machine authority：`.aaf/<task>/model_observation.json`（schema_version=1）。

## 11. WorkBuddy Reliability State

RW-027 = **SOLVED**（AAF-v0.4-TASK-011 + FIX-001 + FIX-002，2026-08-29）：
bounded transient retry（同 invocation，绝不换模型/付费层级）、confirmed-dead-before-retry、
single absolute stage deadline、Windows tree cleanup authority（taskkill /T /F + 顶层确认退出 = tree confirmed）、
safe cleanup reserve（默认 60s 下限）、attempt admission control、结构化 telemetry。
任何时刻最多一个 CodeBuddy 进程；cleanup 未确认 → fail closed 绝不 retry。

## 12. Project Status Transparency Rule（长期协作规则）

正式落盘：`docs/internal/AAF_TASK_EXECUTION_POLICY.md` §16（2026-08-29，AAF-v0.4-FREEZE-001）。

规则核心：任何项目、任何对话推进时，Planner / AI 必须清楚展示：
**当前阶段 / 当前步骤 / 已完成 / 未完成 / 下一步 / 阶段进度 / 主线或临时支线**。
因 blocker 插入临时工作时，必须明确：这是临时支线、为什么插入、完成后回到哪条主线。
不得让用户从长上下文中自己推断「现在在做什么、做到哪了、还剩多少」。

**Global Collaboration Rule Sync Pending**：该规则应同步至 Obsidian / 全局 AI 协作规范
（本 Framework 无直接 Obsidian 写入能力，不假装已同步；待人工/有权限通道同步）。

## 13. 下一 Planner 对话如何恢复（How to resume）

1. 读 `docs/internal/PROJECT_STATE.md` 顶部 v0.4 块（FROZEN 状态、baseline、freeze commit、tag）。
2. 读本 handoff（v0.4 最终交接）与 `docs/internal/AAF_MASTER_BACKLOG.md` §7 Summary（deferred/future 总览）。
3. 若只是**使用 AAF**：直接使用，不进入 v0.5 development。
4. 若用户**显式开始 v0.5 / Model Routing / 新功能开发**：才开启新 development line，
   新 line 从 deferred/future 项（§7/§8）立项，遵守 Policy §16 透明规则。
5. v0.4 已冻结：**不得随意重开**。仅当出现新的、具体的 release-blocker evidence
   并经 WorkBuddy/Codex 复核确认后才可能例外。

## 14. 冻结边界（Handoff Boundary）

- **v0.4 已完成（FROZEN）。**
- 下一对话若只是使用 AAF：**不得自动进入 v0.5 development**。
- 只有用户明确开始 v0.5 / Model Routing / new feature development，才开启新 development line。

## 15. Release Package / Notes

- 本仓库无独立 CHANGELOG 惯例 → 本 handoff 承担 v0.4 release notes 职责。
- 最小 release package = frozen git tag `v0.4` + 本 handoff + PROJECT_STATE + backlog +
  README（既有）。不新增 installer/build pipeline（无既有 artifact convention，不新造）。

## 16. Repository 状态验证（freeze 时点）

- main = origin/main = `1d3771fe8220e1b2e21c774840d680ec9f2dce61` 及其后的 docs-only freeze 提交
- tag `v0.4` 已创建并推送
- tracked tree clean；ahead/behind = 0/0
- 常驻 untracked（历史惯例，未误删、未误提交）：`.aaf/`、`AAF_TASK004_PROCESS_CHECK.txt`、`scripts/start_bridge_hidden.vbs`
- 历史 `.aaf` execution artifacts 未删除、未重写（v0.4 evidence 保留）
- 本 freeze 未引入任何功能代码
