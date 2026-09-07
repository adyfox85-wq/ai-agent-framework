# AAF v0.6 Execution Protocol

Status: Protocol Freeze Draft

## 1. Purpose

This document defines the operational flow after AAF v0.6 architecture reset.

The goal is simple:

> Planner and Executor collaborate without manual copy/paste, while avoiding unnecessary multi-agent complexity.

---

# 2. Default Execution Flow

```
User
 |
 v
Planner
(GPT / DeepSeek / other)
 |
 v
TASK
 |
 v
Hermes Executor
 |
 v
REPORT
 |
 v
Optional Review
```

---

# 3. Planner Responsibilities

Planner decides:

- what needs to be done
- task boundaries
- required files
- acceptance criteria
- whether review is necessary

Planner creates the execution task.

Planner does not perform unnecessary execution work.

---

# 4. Hermes Responsibilities

Hermes receives the task as execution authority.

Hermes handles:

- command execution
- file operations
- tool usage
- validation
- result reporting

Hermes should not require human copy/paste between every step.

---

# 5. Model Provider Selection

Hermes may use different model providers:

```
Hermes
 |
 +-- Ollama local models
 |
 +-- Free API models
 |
 +-- Paid API models
```

Selection principle:

Use the lowest-cost capable provider.

Do not choose a cheaper provider if it causes:

- repeated failures
- excessive retries
- debugging overhead

---

# 6. Ollama Usage Boundary

Ollama is a local inference provider.

It is not an Agent.

It exists to:

- reduce paid API usage
- provide local capability
- support economical execution

Automatic task splitting is not enabled by default.

---

# 7. Review Trigger

Review is optional.

Review should be considered for:

- high-risk code changes
- architecture changes
- security-sensitive operations
- uncertain decisions

Review is usually unnecessary for:

- simple text processing
- normal file handling
- low-risk operations

---

# 8. Review Provider

Review capability is replaceable.

Examples:

- Codex
- WorkBuddy
- Kimi
- other future tools

The role matters, not the product.

---

# 9. Report Return

Hermes returns:

- execution status
- modified files
- tests performed
- artifacts
- problems
- unfinished items

Planner uses the report to decide next action.

---

# 10. Expansion Rule

Before adding new automation, ask:

1. Does it reduce manual work?
2. Does it reduce total cost?
3. Does it improve reliability?

If not, do not add it.

---

# 11. Frozen Default

AAF v0.6 operational model:

```
Think with Planner

Execute with Hermes

Review only when valuable
```
