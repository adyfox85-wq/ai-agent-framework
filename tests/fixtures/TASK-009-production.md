AAF_TASK_BEGIN

Task ID: AAF-v0.4-TASK-009
Task Name: Bridge Reliability Final Closure

Workspace: D:\AdyAI\ai-agent-framework

Objective:
完成 AAF v0.4 freeze 前 Bridge Reliability 收口：

1. 实现并关闭 RW-012 hotkey listener self-recovery。
2. 基于正式 TASK contract 对 RW-008 做最终 closure 判定。
3. 对 RW-021 completion notification continuity 做 necessity check，仅在同根、低风险、低成本时合并实现。

Background:
RW-008 最新生产 blocker 已直接由 Hermes 修复：

Commit:
61e3a058e700fffa68852e1cb5e3d1424969c152

Root Cause:
Bridge/task validation parser 在 CRLF 输入下因行尾 \r 导致 Acceptance 等字段无法解析。

Implemented:
- bridge/task_io.py parser newline normalization
- task_validation.py same normalization
- duplicate Acceptance fail-closed
- LF / CRLF / BOM / multiline Acceptance regressions
- targeted 117 passed
- non-GUI 897 passed
- Remote Sync 0/0

Remaining RW-008 observations:
- U+3000 full-width-space indentation not supported
- rich-text/Markdown escaping risk not concretely reproduced
- legacy "Acceptance Criteria" alias differs between parser layers

These must not automatically become freeze blockers unless they belong to the current formal TASK contract.

RW-024 implementation is already SOLVED in repository.
A fresh Bridge process is expected to load both RW-008 and RW-024 changes.

Requirements:

1. RW-008 Formal Contract Review
Read:
- templates/TASK.md
- AAF_TASK_EXECUTION_POLICY.md
- current Bridge intake/parser
- task_validation
- RW-008 backlog entry

Determine the actual current formal TASK contract.

Explicitly classify each remaining item:

A. U+3000 indentation
B. Markdown/rich-text escaping
C. "Acceptance Criteria" legacy alias

For each:
- FORMAL CONTRACT REQUIRED
or
- LEGACY / NON-CONTRACT / OBSERVATION

Do not implement non-contract compatibility merely to close backlog.

2. RW-008 Closure Rule
If current formal Compact TASK contract is fully supported after commit 61e3a05:
→ mark RW-008 SOLVED for v0.4.

Document remaining legacy/non-contract compatibility as deferred observation only.

If a remaining item is proven part of formal current contract and reproducibly fails:
→ implement only that minimal gap.

3. Parser Safety
Any RW-008 change must preserve:

- malformed TASK fail closed
- missing/empty Acceptance reject
- duplicate Acceptance fail closed
- invalid/duplicate Route fail closed
- AAF_TASK_BEGIN / AAF_TASK_END authority
- immutable snapshot/hash semantics

Do not broaden parser to "accept anything".

4. RW-012 Actual Gap Discovery
Inspect current:
- hotkey listener
- Bridge startup
- tray integration
- listener health/detection
- shutdown path
- warning/status logic

Establish actual existing behavior before implementation.

5. RW-012 Self-Recovery
When the hotkey listener unexpectedly stops or becomes unusable:

- Bridge should attempt safe recovery
- recovery must not require restarting the whole Bridge
- only one active listener may exist
- duplicate hotkey registration must not occur
- intentional shutdown must not trigger recovery
- Bridge shutdown must not resurrect listener
- repeated failures must be bounded
- no tight restart loop
- failure must remain observable by log/status/warning

6. Recovery Ownership
Use one clear owner for listener lifecycle/recovery.

Avoid multiple components independently restarting the listener.

7. RW-012 Regression Matrix
At minimum:

A.
listener unexpectedly exits
→ recovery attempted
→ one active listener

B.
recovery succeeds
→ Bridge remains usable

C.
recovery fails repeatedly
→ bounded retry/backoff
→ visible failure state/log

D.
intentional shutdown
→ no recovery

E.
multiple recovery triggers
→ no duplicate listener

F.
Bridge exit during recovery
→ no resurrection

8. RW-021 Necessity Check
Inspect current completion notification behavior across Bridge restart.

Answer:

A. Is the issue still reproducible/current?
B. Does it share the same lifecycle owner/root cause as RW-012?
C. Can it be solved with a very small, low-risk change in this task?

If YES to all:
→ implement and test.

Otherwise:
→ leave RW-021 OPEN/DEFERRED P2
→ document why it does not block v0.4 freeze.

Do not create a separate large notification recovery subsystem.

9. RW-024 Observation
Do not modify RW-024 unless an actual fresh-Bridge reproduction shows regression.

If current fresh Bridge completion copy behavior is observed during normal task execution:
- no secondary success modal = confirm observation
- secondary modal returns = record regression only

Do not run dedicated ToDesk/clipboard GUI E2E.

10. Scope Discipline
Do not implement:

- Model Observability
- Model Routing
- stage timing
- autostart
- Tray Stop
- fixed E2E Task ID
- packaging
- new runtime authority logic

11. Tests
Run:

- RW-008 relevant parser regressions
- RW-012 targeted lifecycle/recovery tests
- RW-021 targeted tests only if implemented
- Bridge regression tests
- all non-GUI unit/integration tests

Do not run real clipboard / ToDesk-sensitive GUI E2E.

12. Documentation
Update existing:
- docs/internal/AAF_MASTER_BACKLOG.md
- docs/internal/PROJECT_STATE.md if required by current project maintenance policy

No new duplicate handoff documents.

Target state:

RW-008:
SOLVED for current formal v0.4 TASK contract,
unless a genuine formal-contract blocker remains.

RW-012:
SOLVED.

RW-021:
SOLVED if safely same-root;
otherwise DEFERRED/OPEN P2 and explicitly non-blocking for freeze.

13. Review
WorkBuddy independently verify:

- RW-008 contract classification is justified
- parser still fail-closed
- listener recovery works safely
- no duplicate listener
- intentional shutdown safe
- retries bounded
- RW-021 decision does not inflate scope

Codex audit:

- parser safety boundary
- listener lifecycle ownership
- no restart loop / duplicate listener
- no lifecycle authority regression
- freeze scope discipline

14. Remote Sync
Complete with:

- commit
- push origin main
- ahead/behind = 0/0
- tracked tree clean

Acceptance:
1. Current formal TASK contract explicitly identified.
2. RW-008 remaining observations classified by contract relevance.
3. No non-contract parser expansion solely for compatibility.
4. Formal Compact TASK intake works with LF/CRLF and multiline Acceptance.
5. Parser remains fail-closed.
6. RW-008 = SOLVED for v0.4 if no formal blocker remains.
7. RW-012 real failure mode identified from code.
8. unexpected listener loss safely self-recovers.
9. no duplicate listener / hotkey registration.
10. intentional shutdown does not recover.
11. repeated recovery failure is bounded and observable.
12. RW-012 = SOLVED.
13. RW-021 necessity check completed.
14. RW-021 deferred if independent/nonessential, without blocking freeze.
15. no unrelated scope expansion.
16. targeted tests PASS.
17. all required non-GUI tests PASS.
18. WorkBuddy no blocking rework.
19. Codex APPROVE.
20. Remote Sync = SYNCED.
21. tracked tree clean.

Expected Final Result:
SUCCESS

Route: hermes -> workbuddy -> codex

Route Hint:
Formal RW-008 contract closure
→ RW-012 minimal listener self-recovery
→ RW-021 necessity check
→ WorkBuddy independent Bridge reliability verification
→ Codex lifecycle/parser safety audit
→ Planner closes Bridge Reliability

AAF_TASK_END
