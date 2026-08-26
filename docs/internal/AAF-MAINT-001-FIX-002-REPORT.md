# AAF-MAINT-001-FIX-002 REPORT

> Task ID: AAF-MAINT-001-FIX-002
> Task Name: Complete AAF Master Backlog and Recovery Registry
> Executor: Hermes
> Date: 2026-08-27
> Workspace: D:\AdyAI\ai-agent-framework
> Status: **COMPLETE（Hermes 执行部分）**

## Current Status

SUCCESS（Hermes 侧执行完成，测试通过，commit + push 完成）

## Route

hermes -> workbuddy -> codex

## Master Backlog Path

```
D:\AdyAI\ai-agent-framework\docs\internal\AAF_MASTER_BACKLOG.md
```

（仓库内权威路径：`docs/internal/AAF_MASTER_BACKLOG.md`）

## Obsidian Mirror Path

```
D:\AdyAI\Obsidian-Vault\AI Agent Framework\AAF_MASTER_BACKLOG.md
```

- 镜像顶部声明 **MIRROR ONLY**、Source 路径与"Do not maintain this mirror
  as an independent authoritative version"。
- 已校验：去掉 10 行镜像头后，正文与源文件逐行一致（diff 通过）。
- 仅建立一次镜像；未开发自动同步程序或 Obsidian plugin。

## Items Recorded

- RW-001 ～ RW-013：13 项 Real-World Usage / Usability / Incident 登记
- BND-001：Planner-layer Anti-Drift Validation
- CTX-001：Context Length / Conversation Rollover UX
- HIST-001：Historical Framework Optimization Set Recovery（RECOVERY_PENDING）

共 16 个正式条目，每个条目均包含：ID / Title / Category / Status /
Priority / Evidence / Origin / Current Implementation / Remaining Gap /
Decision / Target / Do Not Forget。

Status 仅使用：OPEN / PARTIAL / OBSERVATION / SOLVED / RECOVERY_PENDING /
DEFERRED。
Priority 仅使用：P0 / P1 / P2 / P3。

## RW-013 Incident（self-triggering reference trap）

- 已登记为 RW-013，Status: OPEN，Priority: P1。
- 记录两次 Router 事故的区别：
  - **RW-011（AAF-MAINT-001）**：局部范围限制被误判为任务级 review 模式，
    执行意图被压制 → 已由 commit 457df93 修复，SOLVED。
  - **RW-013（AAF-MAINT-001-FIX-001）**：任务 Background 为描述前一次事故
    引用 Router 自己的分类短语，全文信号匹配再次触发 review route，
    Hermes 第二次被跳过 → 根因为 self-triggering reference trap，
    本任务只登记、不修改 Router。
- Runtime Diagnose 五项确认已记录：source 正确 / route.json 非 stale /
  import path 正确 / runner path 正确 / routing 前未截断；Direct Probe 与
  stored route.json 一致。
- 本任务及所有新产物**未原样引用任何 Router 触发短语**，防止再次自我触发。
- 事故证据保留：`.aaf/AAF-MAINT-001/`、`.aaf/AAF-MAINT-001-FIX-001/`
  不删除、不覆盖（两者当前均为 untracked 本地证据，与 .gitignore 既定
  运行时状态行为一致）。

## Anti-Drift（BND-001）

- 已登记 PARTIAL / P2。
- Framework 层已实现的防漂移机制已列全（PROJECT_SCOPE / Boundary Check /
  warning-first / suggestion 不自动升级 / 不扩 scope / 不自动写 backlog /
  不自动产生下一 TASK）。
- 明确保留 gap：ChatGPT Planner 长期对话层仍需验证 context compression、
  weighting change、accumulated requirements、model tendency 是否导致
  漂移 / scope creep / 遗忘 / suggestion 误升级。
- 明确原则：**Framework 层完成 ≠ Planner conversation 层已解决**。

## Session Continuity（CTX-001）

- 已登记 PARTIAL / P1。
- 已列 v0.3 现有实现（explicit rollover / SESSION_SUMMARY.md /
  NEXT_SESSION_START.md / bounded recent context）。
- 完整保留用户希望的 6 步承接目标与 6 项不遗失内容。
- 原则：不做 infinite memory；不自动无限生成会话。

## Historical Optimization Recovery（HIST-001）

- 已登记 RECOVERY_PENDING / P2。
- 记录事实：`Known historical optimization set exists; exact original list
  not yet recovered.`
- **未**根据今天的问题、模型常识或推测重新凑成十项。
- 恢复来源候选已登记：old handoffs / PROJECT_STATE history / ChatGPT
  exported conversations / Obsidian notes / local Markdown records。

## Recovery Principle

- 恢复链已写入 Master Backlog 第 5 章与 PROJECT_STATE 0.4：

```
GitHub / local repo → README → PROJECT_STATE → AAF_MASTER_BACKLOG
→ latest closing handoff → 创建新的 ChatGPT Project / Planner conversation
→ 继续维护
```

- 即使旧 ChatGPT Project 或 conversation 不存在，Framework 仍能恢复
  到可继续升级的状态（RW-009，P0）。

## Source Policy

```
Repository（GitHub / local repo）:  authoritative source
ChatGPT（Project / conversation）:   planner / discussion interface
Obsidian:                            human-readable mirror and recovery layer
```

- 已写入 Master Backlog 与 PROJECT_STATE；Obsidian 镜像明确 MIRROR ONLY。

## Tests

```
python -m pytest tests/ -q
206 passed in 1.77s
```

- 与历史基线 206 passed 一致，零回归。
- 本次仅文档 / 项目状态 / 镜像 / 报告修改，未触碰 Framework runtime
  implementation（router / bridge / adapters / lifecycle / boundary /
  archive / session / report 均无改动），测试结果符合预期。

## WorkBuddy

状态：**PENDING —— 由 Framework 下一环节（workbuddy）独立执行**。
本报告不代填 WorkBuddy 结论。

WorkBuddy 验证清单（源自本任务要求 16）：

- [ ] RW-001 至 RW-013 完整（13 项全部存在）
- [ ] 今天原始问题全部覆盖
- [ ] Router 两次真实 incident 区分清楚（RW-011 局部约束误判 / RW-013 自我引用触发）
- [ ] hotkey runtime issue 已登记（RW-012）
- [ ] BND-001 gap 保留
- [ ] CTX-001 gap 保留
- [ ] HIST-001 没有被臆造（RECOVERY_PENDING，未重构十项）
- [ ] Repository / ChatGPT / Obsidian 权威关系清晰
- [ ] PROJECT_STATE 要求未来先读取 Master Backlog（0.5 Future Planning Rule）
- [ ] v0.4 未启动（保持 NOT STARTED）
- [ ] Framework runtime implementation 没有被改变（git diff 仅文档）

## Codex

状态：**PENDING —— 由 Framework 下一环节（codex）独立执行**。
本报告不代填 Codex 结论。

Codex audit 清单（源自本任务要求 17）：

- [ ] 记录是否完整（16 项正式条目 + 恢复链 + 政策）
- [ ] 已实现能力与 Future capability 是否区分（如 RW-005 OBSERVATION、
      RW-007 PARTIAL、RW-010/006 OPEN 仅登记）
- [ ] 历史十项没有幻觉（HIST-001 = RECOVERY_PENDING，未凑项）
- [ ] Recovery chain 是否足以在丢失旧 ChatGPT conversation 后重建
      Planner context（RW-009 + 第 5 章恢复链）
- [ ] Router incident history 是否准确（RW-011 / RW-013 与
      AAF-HOTFIX-ROUTER-READONLY.md、.aaf 证据一致）

## Files Changed

| 文件 | 变更 |
|---|---|
| `docs/internal/AAF_MASTER_BACKLOG.md` | **新增**：长期 Master Backlog（16 个正式条目 + 恢复/耐久性章节 + 更新规则） |
| `docs/internal/PROJECT_STATE.md` | 更新 v0.3 头部区块（CLOSED / 维护观察期 / hotfix 与事故记录 / 可用性缺口 / Source·Mirror·Recovery 政策 / Future Planning Rule）；历史区块未动 |
| `D:\AdyAI\Obsidian-Vault\AI Agent Framework\AAF_MASTER_BACKLOG.md` | **新增**：Obsidian 镜像（MIRROR ONLY，正文与源逐行一致） |
| `docs/internal/AAF-MAINT-001-FIX-002-REPORT.md` | **新增**：本报告 |

**未触碰**：Framework runtime implementation（`ai_agent_framework/`、
`bridge/`、`tests/` 无改动）；v0.3 历史文档；`.aaf/AAF-MAINT-001/`、
`.aaf/AAF-MAINT-001-FIX-001/` 证据保留。

## Commit

- Commit: 由 Hermes 在本次执行完成后创建（单次 commit，不改写 Git 历史）。
- 提交内容：上述 4 个文件（Obsidian 镜像在仓库外，不入库）。

## Remote Sync

- 状态：以实际 push 结果为准（成功后为 SUCCESS；如失败将标记
  REMOTE_SYNC_PENDING 并如实报告）。

## Unresolved

- WorkBuddy / Codex 独立验证待 Framework 后续环节执行（本报告已附验证
  清单，供其逐项核对）。
- 长期问题均已在 Master Backlog 登记（OPEN / PARTIAL / OBSERVATION /
  RECOVERY_PENDING），按政策不自动进入下一 TASK。
- v0.3 保持 CLOSED；v0.4 保持 NOT STARTED。
