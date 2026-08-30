# TASK（Compact Schema）

> Protocol: docs/internal/AAF_TASK_EXECUTION_POLICY.md（Anti-Bloat / Delta-first 正式规则）
> 新建 TASK / FIX 必须遵循该 Policy：TASK = current delta，不是项目知识库；
> Repository 已有信息优先引用 path/section，不重复全文；同一语义不得多处改写。

Task ID:
Task Name:
Workspace:
Risk:
（可选；Planner 显式声明的结构化 task risk：LOW|MEDIUM|HIGH|CRITICAL，唯一合法词汇，
不做大小写/同义词猜测。缺失 = 向后兼容，任务仍可执行，但 Hermes shadow risk =
RISK_UNAVAILABLE——missing ≠ LOW；存在但非法 = 校验严格拒绝。Planner 显式 Risk 即
structured provenance，不从正文/标题推断。）

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

Route:
（canonical machine 字段：显式声明执行链，如 `hermes -> workbuddy -> codex`。
声明后 Router 以此为准，不再靠全文关键词推断；可选。）

Route Hint:
（建议执行链：Hermes / WorkBuddy / Codex 分工；人类补充说明，仅供阅读，
不参与机器路由；可选。）

AAF_TASK_END
