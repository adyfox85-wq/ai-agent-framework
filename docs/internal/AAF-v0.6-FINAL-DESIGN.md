# AAF v0.6 Final Design

Status: Architecture Freeze Draft

## 1. Origin Goal

AAF was created to solve one core problem:

> Remove manual copy/paste between planning and execution.

The purpose was not to create a complex multi-agent organization.

The system should optimize for:

- lower operating cost
- reliable execution
- replaceable components
- minimal human transfer work

---

# 2. Core Workflow

Default workflow:

```
Planner
(GPT / DeepSeek / other)
        |
        v
Hermes Executor
        |
        v
Optional Review
```

This is the standard path.

---

# 3. Planner Layer

Planner is responsible for:

- understanding user intent
- breaking down work when needed
- generating execution instructions
- deciding whether review is required

Planner is not permanently bound to one model.

Possible providers:

- ChatGPT
- DeepSeek
- future models

---

# 4. Hermes Position

Hermes remains the execution center.

Responsibilities:

- receive tasks
- execute commands
- operate tools
- generate reports
- maintain execution discipline

Hermes is not replaced by local models.

---

# 5. Ollama Position

Ollama is a local model runtime/provider.

It is NOT an independent Agent.

Purpose:

- reduce paid API consumption
- provide local inference capability
- handle suitable low-cost workloads

Example:

```
Hermes
  |
  +-- Ollama local models
  |
  +-- Free API models
  |
  +-- Paid API models
```

Important rule:

Do not introduce complex automatic splitting unless measured savings exceed added complexity.

---

# 6. Review Layer

Review is optional.

It is capability-based rather than agent-based.

Examples:

## UI / experience verification

Possible tools:

- WorkBuddy
- other UI validation tools

## High-risk code review

Possible tools:

- Codex
- Kimi
- other capable reviewers

Review providers are plugins.

---

# 7. Plugin Principle

AAF defines roles, not fixed products.

Examples:

Planner Plugin:

- GPT
- DeepSeek

Executor:

- Hermes

Model Provider Plugin:

- Ollama
- API providers

Review Plugin:

- Codex
- WorkBuddy
- Kimi

---

# 8. Economic Strategy

Priority order:

1. Local/free capability when sufficient
2. Free API capability
3. Paid API only when necessary

However:

A cheaper model is not automatically better if it creates:

- retries
- debugging cost
- routing complexity
- unreliable execution

The system optimizes total cost, not token price only.

---

# 9. Avoided Complexity

AAF will NOT automatically introduce:

- mandatory multi-agent chains
- every-task review
- automatic task splitting by default
- unnecessary router layers

Reason:

The infrastructure itself must not become more expensive than the problem it solves.

---

# 10. Current Frozen Direction

AAF v0.6 follows:

```
Simple by default

Planner
  |
Hermes
  |
Optional Review
```

Extend only when real usage demonstrates the need.
