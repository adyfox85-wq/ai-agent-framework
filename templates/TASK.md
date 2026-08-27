# TASK（Compact Schema）

> Protocol: docs/internal/AAF_TASK_EXECUTION_POLICY.md（Anti-Bloat / Delta-first 正式规则）
> 新建 TASK / FIX 必须遵循该 Policy：TASK = current delta，不是项目知识库；
> Repository 已有信息优先引用 path/section，不重复全文；同一语义不得多处改写。

Task ID:
Task Name:
Workspace:

Objective:
（本轮 delta 的目标。长度增加必须有本轮新增信息依据。）

Context:
（必要的最小上下文；优先引用 PROJECT_STATE / AAF_MASTER_BACKLOG / 前序 REPORT 的 path/section，
不复制全文。FIX 只描述 parent blocker + 本轮 delta。）

Source of Truth:
- docs/internal/PROJECT_STATE.md
- docs/internal/AAF_MASTER_BACKLOG.md
- （…只列引用，不复制内容）

Requirements:
1. 
2. 

Scope / Out of Scope:
允许：…
禁止：…

Validation:
（验证方法 / 命令 / 证据要求。与 Acceptance 语义去重：这里写"怎么验证"，
Acceptance 写"必须满足什么"。）

Acceptance:
1. 
2. 

Route Hint:
（建议执行链：Hermes / WorkBuddy / Codex 分工；可选。）

AAF_TASK_END
