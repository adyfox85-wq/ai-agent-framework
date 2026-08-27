# AAF TASK EXECUTION POLICY — Anti-Bloat / Delta-first（正式 Framework Policy）

> Document Type: **Durable Framework Policy / 正式规则**（非历史记录）
> Established: 2026-08-28（AAF-MAINT-CONTEXT-001）
> Location: `docs/internal/AAF_TASK_EXECUTION_POLICY.md`
> Scope: 本仓库所有 TASK / FIX 的编写、stage prompt 构建、REPORT 生成与验证流程

本 Policy 解决 AAF 的 Context 膨胀问题：Hermes → WorkBuddy → Codex 曾采用
eager full-content chaining（TASK + 全部上游 narrative 全文层层叠加）。新协议改为
**reference-based / lazy-loading Stage Context Packet**，压缩是去重、不是删约束。

---

## 1. 核心原则（Anti-Bloat）

1. **TASK = current delta，不是项目知识库。**
   TASK 只描述本轮要做的增量；背景、历史、设计、全局规则属于 Repository，
   通过 path/section 引用，不复制全文。

2. **Repository 已有信息优先引用 path/section，不重复全文。**
   例如 `docs/internal/PROJECT_STATE.md` 的 Phase E 段、`AAF_MASTER_BACKLOG.md`
   的 RW 条目、冻结设计的 § 号——只写引用，不粘贴内容。

3. **同一语义不得在 Background / Requirements / Acceptance 多次改写。**
   一个约束只出现一次；其他位置引用它（"见 Requirements 1"），
   禁止三处各写一遍造成语义漂移与体积膨胀。

4. **FIX 只描述 parent blocker + 本轮 delta。**
   FIX 任务引用父任务（Task ID / 其 REPORT 的 REQUEST_CHANGE 项），
   只写本轮要关闭的 blocker 与对应改动；不重述父任务全文。

5. **全局 Git / routing / safety 规则集中到 policy。**
   重复出现的操作纪律（不 commit 到他人分支、验证命令、安全边界）集中维护，
   TASK 内不再逐条复制。

6. **长度增加必须有本轮新增信息依据。**
   压缩不是删除——任何新增内容必须对应本轮新增需求/证据；
   无新增信息依据的长度增长视为违规（见 §10 测量与 §12 反回归）。

7. **摘要只用于导航，Repository artifacts 才是验证真相。**
   summary / 结构化 JSON 帮助定位；验证必须回到真实文件、git diff、测试输出。

8. **压缩是去重，不是删约束。**
   以下内容任何情况下不得为瘦身而删除：unique blocker、safety invariant、
   required validation、acceptance semantics、scope boundary（见 §3 Coverage Guard）。

## 2. Compact TASK Schema（正式最小结构）

普通 TASK / FIX 均使用以下结构（见 `templates/TASK.md`）：

```
Task ID
Task Name
Workspace
Objective
Context
Source of Truth
Requirements
Scope / Out of Scope
Validation
Acceptance
Route
Route Hint
```

字段语义与去重边界：

| 字段 | 语义 | 去重边界 |
|---|---|---|
| Task ID / Name / Workspace | 身份与执行位置 | 唯一；不得在其他字段重复 |
| Objective | 本轮 delta 目标 | 与 Requirements 不重复改写 |
| Context | 必要最小上下文 | 只引用 PROJECT_STATE / BACKLOG / 前序 REPORT 的 path/section |
| Source of Truth | 权威来源引用 | 只列 path/section，不复制内容 |
| Requirements | 本轮唯一约束 | 与 Acceptance 语义不重复；同一约束只出现一次 |
| Scope / Out of Scope | 允许 / 禁止边界 | 边界必须完整，禁止为瘦身删除禁止项 |
| Validation | 怎么验证 | 方法/命令/证据；与 Acceptance（满足什么）语义去重 |
| Acceptance | 必须满足什么 | 验收语义完整保留 |
| Route | canonical machine 字段：显式声明执行链（`hermes -> workbuddy -> codex`） | 机器路由 authority；与 Route Hint 去重（Hint 只供人类阅读） |
| Route Hint | 建议执行链的人类补充 | 只读说明，不参与机器路由；可选 |

Formal validator（`task_validation.py`）保持最小必填集
（Task ID / Task Name / Objective / Acceptance）以兼容旧 TASK；
新 TASK 按本 Schema 全字段编写。解析器支持 Compact 全部字段的
既有格式（`Field: value` 同行式 / `# Field` 标题式），旧格式不破坏。

## 2.1 Explicit Route Authority（FIX-003 + FIX-004）

- **`Route:` 是 canonical machine 字段**（非人类说明文字），由
  `router.parse_explicit_route` 正式 parse：`Route: hermes -> workbuddy -> codex`
  （分隔符容忍 `->` / `→` / `,` / 空白；agent 仅限 hermes / workbuddy / codex）。
- **三态解析（FIX-004）**：parser 返回 `RouteStatus` 三态，不得用 None 同时表示
  “没写 Route”和“写了但非法”：
  - `ABSENT`：TASK **完全没有** Route 字段 → legacy keyword heuristic 唯一允许路径
  - `VALID`：可解析且全部 agent 合法、无重复 → authoritative（覆盖 heuristic）
  - `INVALID`：非法 agent / malformed syntax（空段、悬挂分隔符）/ empty route /
    duplicate agent 结构 → **Task Validation FAIL（fail-closed）**，
    绝不静默回退 heuristic。
- **显式 Route 优先于全文关键词 heuristic**：TASK 声明合法 Route 时，
  `decide_route` 直接采用声明，不再用关键词猜测；keyword Router 仅作为
  legacy fallback / **Route 字段完全缺失**时的推断。**TASK 不得被迫重复
  "代码/安全/架构" 等无关词来触发 Codex**（Anti-Bloat 回归测试保障）。
- **Route Hint 保持人类补充**：只读说明，不参与机器路由（parse 只认
  `Route:` 字段）。
- **Route Completeness Guard**：Runner 在最终 SUCCESS 前验证所有 required
  route agents 都真正执行并产生有效结果（缺失 / FRAMEWORK_ERROR / 空结果 →
  `_aggregate_status` = WAITING，REPORT 追加对应 integrity note，绝不误报
  SUCCESS）。
- **Acceptance 不可被路由绕过**：TASK 显式要求 Codex = APPROVE 但实际 route
  不含 Codex → Validation 阶段直接发现 Route inconsistency 并拒绝执行
  （Runner 的防御性不变量断言：declared route ≠ computed route → 失败）。
- **旧 TASK 无 `Route:` 字段 → 保持 legacy keyword inference 不变**。

## 3. Semantic Coverage Guard（压缩不丢信息）

压缩必须满足（Requirement 3）：

- unique requirement coverage = 100%
- safety invariant coverage = 100%
- acceptance semantics coverage = 100%
- Source of Truth reference resolvable（引用路径存在）

自动检查：`context_packet.verify_semantic_coverage(original, compact)`
（确定性本地函数，无 LLM）——对 Requirements / Acceptance 节的编号项与 bullet 项
逐项核对 compact 中是否保留（空白/大小写归一化后的子串匹配）。

说明：自动 Guard 能捕获"整项删除"；若压缩改写措辞，语义等价性必须由
WorkBuddy 独立验证（Guard 不是语义证明，WorkBuddy 才是）。
Guard 失败（coverage < 100%）→ 该压缩不得提交。

## 4. Stage Context Packet 协议（reference-based / lazy-loading）

旧 eager full-content chaining（废止）：

```
Hermes:    TASK
WorkBuddy: TASK + Hermes full result
Codex:     TASK + Hermes full result + WorkBuddy full result
```

新协议（`adapters.build_prompt_measured` 实现）：

```
Hermes:    TASK 全文（= current delta）+ required Source of Truth 路径
WorkBuddy: TASK.snapshot.md path + hash（immutable execution snapshot）；Hermes
           结构化摘要（hermes_result.json）；changed files / commit / evidence 路径；
           repo access；Hermes narrative 全文只在按需读取
Codex:     TASK.snapshot.md path + hash；Hermes 结构化执行事实；WorkBuddy 结构化
           verdict/findings（workbuddy_result.json）；relevant repo/diff paths；
           上游 narrative 全文只在按需读取
```

规则：

- **Immutable Task Snapshot（FIX-002 + FIX-004）**：Runner 每次新任务执行开始时把实际执行的
  TASK 内容写入 `<output_dir>/TASK.snapshot.md`；Task Reference / task hash /
  context_manifest / 下游 prompt / REPORT 统一引用 snapshot。active/archive
  TASK 文件后续变化不得破坏本次 execution integrity。
- **Snapshot = Execution Authority From Entry（FIX-004）**：已有 execution
  directory（含 resume）且 `TASK.snapshot.md` 存在 → Runner 从入口起优先读取
  snapshot，并基于 snapshot 完成：task validation、Task ID parsing、route
  parsing、boundary-relevant semantics、ownership handshake identity、下游
  prompt/reference 生成。active TASK 只作 provenance / resume request locator，
  绝不重新成为 execution authority；若 intake Task ID 与 snapshot 严重冲突 →
  **显式拒绝 resume**（不得静默采用新 active 内容）。
- **Raw-Byte Task Hash（FIX-004）**：Task Hash = snapshot 文件**原始 bytes** 的
  标准 SHA-256（`hashlib.sha256(path.read_bytes())`），bytes = `stat().st_size`；
  不经过 read_text / 换行归一化 / encoding replacement——外部工具
  （certutil / sha256sum / hashlib.read_bytes）可直接复算，CRLF/LF 文件均可。
- **Agent 必须保持独立验证，不得只相信 summary。**
  WorkBuddy / Codex prompt 内保留独立验证指令：读取 snapshot 全文、检查仓库实际状态、
  核对 changed files / commit / evidence。
- **摘要只用于导航**：结构化 JSON 的 summary 字段明确标注"不是验证真相"。
- **下游 prompt 不默认嵌入上游 narrative 全文**；只有引用路径。

## 5. Structured Stage Results

每个 stage 生成机器可读短结果 `<agent>_result.json`（`context_packet.build_stage_result`），
最小字段：

```
agent / status / verdict / blocking_rework / commit / tests /
changed_files / evidence_paths / findings / warnings
（+ summary_complete + structured_summary_status + summary 导航字段 + narrative_path）
```

- **Machine-Readable Stage Summary 契约（FIX-002）**：WorkBuddy / Codex 答复必须以
  `AAF_STRUCTURED_RESULT_BEGIN {JSON} AAF_STRUCTURED_RESULT_END` 块结尾，包含
  verdict / blocking_rework / findings / warnings；Hermes 至少包含 status /
  changed_files / commit / warnings。Framework 只接受经过 schema validation 的
  结构化块（`extract_and_validate_structured`）；缺失 / 损坏 → 显式
  `structured_summary_status = NOT_PROVIDED / MALFORMED`。
- **unknown ≠ empty（FIX-002）**：findings / warnings 未提取时为 `null`（UNKNOWN），
  绝不伪装为 `[]`；`[]` 只出现在 Agent 显式声明"确认没有"的情况。不完整 summary
  不得被下游当成完整事实——下游 prompt 显式标记 PARTIAL/UNKNOWN 并指引读取 narrative。
- **Narrative / JSON 一致性 guard（FIX-002）**：structured 声明 complete 时，narrative
  中显式 warning（W1:/WARNING:/⚠）与 REQUEST_CHANGE / FAIL（无通过结论时）不得在
  JSON 中消失；违反 → `structured_summary_status = CONSISTENCY_VIOLATION`、
  `summary_complete = false`（下游必须读 narrative）。
- `.md` 长报告继续保留用于追溯（evidence_paths 引用），不再默认全文注入下游 prompt。
- 框架只确定性派生可验证事实（status/verdict 由结论词或 validated 结构化块派生、
  commit/changed_files 由 git 事实）；tests/findings/warnings 框架不猜测——真实内容在
  narrative。

## 5.1 Remote Sync Truth（FIX-002）

`context_packet.remote_sync_state(workspace)` 确定性计算三类状态（写入 REPORT
`## Remote Sync` 段）：

- **Commit Sync**: SYNCED / UNSYNCED / UNKNOWN —— `HEAD == origin/main` 且
  ahead/behind=0/0 只表示 commit graph synced
- **Tracked Working Tree**: CLEAN / DIRTY —— `git status --porcelain -uall`；
  预允许 untracked local artifacts（`.aaf/`、`scripts/start_bridge_hidden.vbs`、
  `AAF_TASK004_PROCESS_CHECK.txt`）不得单独导致 DIRTY
- **Task Remote Sync**: SYNCED **仅当** Commit Sync = SYNCED **且** Tracked
  Working Tree = CLEAN（本轮 tracked 修改必须 commit + push 后才能满足）；
  否则 UNSYNCED（非 git 仓库 → NOT_APPLICABLE，REPORT 不输出该段，不虚构）

`commit_changed:false` 不能证明本轮 tracked modifications 已同步——必须以
Task Remote Sync 为准。

## 6. Context Manifest / Integrity

每个运行目录生成 `context_manifest.json`（`context_packet.write_manifest`），至少记录：

- `execution_task`：immutable snapshot（`TASK.snapshot.md`）的 path + hash + bytes
  ——**所有 downstream integrity check 的默认验证对象**（FIX-003）；hash 为 snapshot
  文件原始 bytes 的标准 SHA-256、bytes 为 `stat().st_size`（FIX-004，外部工具可复算）
- `task`：legacy key，恒等于 execution_task（向后兼容，两者 hash 必须一致）
- `intake_task`：仅 provenance（active TASK 原始 path，**无 hash**——不出现
  第二个 hash authority；active 文件后续变化不影响 execution integrity）
- 每 stage result_md / result_json 的 path + hash + bytes
- workspace；commit / HEAD（git 事实，非 git 仓库为 null，不虚构）
- 每 stage prompt 的 size 指标（§10）

引用完整性检查：`context_packet.check_references(manifest)` —— 所有引用 path 存在且
hash 匹配（默认验证 execution_task；intake_task 因可能被移动/归档不参与校验）；
snapshot 或 stage 文件后来变化（含 tamper）→ 检测为 hash 不匹配
（可追溯性不丢失）。

## 7. REPORT De-duplication

最终 REPORT（`report.build_report`）：

- 不再复制整份 `## Original Task <full TASK>`；
  改为 `## Task Reference`：Task ID / Task Path（= immutable snapshot
  `TASK.snapshot.md`）/ Task Hash / Artifacts 目录。
- 可额外记录 `Original Intake Path`（active TASK 原始路径）——它只能是
  provenance，不是 execution authority（FIX-003）。
- 提供 `sync_state` 时附加 `## Remote Sync` 段（§5.1：Commit Sync /
  Tracked Working Tree / Task Remote Sync）。
- Agent Results：摘要 + `<agent>_result.md` 完整结果路径；不复制上游 narrative 全文。
- Planner Handoff 保留真正需要的：final status、blocking issues、verdicts、
  next-step facts、artifact references。
- Legacy 外部调用方（不提供 Task Path/Hash）自动 fallback 到旧全文嵌入（§8）。

## 8. Backward Compatibility

- 旧 TASK / 旧 `.aaf` artifact 仍可读：旧目录没有 `<agent>_result.json` →
  `build_prompt` 自动 fallback 到 legacy 全文嵌入（行为与 v0.2 一致）。
- 新协议不破坏：Router、Hermes execution、WorkBuddy 独立验证、Codex 审查、
  REPORT 生成、Planner handoff、task lifecycle（全量测试回归保障）。
- `build_report` 无 Task Reference 参数时保留旧格式（自包含 REPORT）。

## 9. No-Information-Loss Fallback

下游 Agent 无法读取引用文件时，**必须**：

- prompt 层面：显式 fail-fast 指令（"引用文件缺失或无法读取 → 报告 FAIL /
  REQUEST_CHANGE 并列出缺失项，不得静默缺上下文继续审查"）；
- 构建层面：被引用的 narrative 文件缺失 → `_narrative_reference_block` 显式
  fallback 嵌入全文并标注 `FALLBACK_EMBEDDED`；
- 任何情况下不得静默缺上下文继续审查 / 验证。

## 10. Context Size Measurement（可观测性）

每 stage 记录（`context_packet.measure_prompt`，写入 manifest）：

- generated prompt chars / bytes
- embedded artifact count（默认注入的 artifact 数）
- referenced artifact count（按需引用数）

无 tokenizer 时记录 chars/bytes，不虚构 token 精确值。
对比方法：在同一个代表性 fixture 上构建 old full-chain prompt 与 new packet prompt，
比较总 chars（`context_packet.compare_packet_sizes`）。
测量证据（FIX-002 Req 11，可复算）：同一 fixture（tests/test_context_integrity.py
`test_context_size_fixture_exact_numbers`，固定 workspace 路径）old full-chain
**26,211 chars** → new packet **5,379 chars**（**-79.5%**，embedded=0，referenced=1/2）。
只允许记录可复算数字；不得同时保留两组冲突数字。

## 11. 禁止事项（本 Policy 不授权）

- 不得以"压缩"为名删除 unique blocker / safety invariant / required validation /
  acceptance semantics / scope boundary。
- 不得用任意"最多 N 字"硬截断真实需求；长度规则只用于发现异常。
- 不得静默降级验证质量；缺失引用宁可 FAIL 也不猜。

## 12. Anti-Regression（防未来再次膨胀）

以下 guard 由 `tests/test_context_compaction.py` 自动执行：

- REPORT generator 不恢复 full TASK embedding（提供 Task Reference 时无
  `## Original Task` 全文段）；
- downstream prompt builder 不恢复 unconditional upstream full-report
  concatenation（有结构化 JSON 时 prompt 不含上游 narrative 全文）；
- Compact TASK Policy 文件存在且被当前模板（`templates/TASK.md`）引用。

---

*Policy 变更须经 Planner 评审 + WorkBuddy/Codex 复核后落盘；本文件本身同样遵守
Anti-Bloat 原则（引用而非复制）。*
