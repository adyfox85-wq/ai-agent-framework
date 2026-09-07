# AAF v0.6 Pre Implementation Check

Status: Preparation Freeze

## Purpose

Before modifying code, this document defines the implementation boundary check.

The objective is not to rebuild AAF from scratch.

The objective is to reduce the existing system to the smallest reliable workflow.

---

# 1. Primary Question

Before changing anything:

> Does this component directly solve the original problem?

Original problem:

Remove manual copy/paste between Planner and Hermes.

---

# 2. Components To Keep

## Hermes

Keep as execution core.

Responsibilities:

- receive TASK
- execute tools
- produce REPORT
- maintain execution evidence

---

## Planner Interface

Keep.

Possible planners:

- ChatGPT
- DeepSeek
- future models

The protocol matters more than the model.

---

## Optional Review

Keep as an optional capability.

Not mandatory in every task.

---

# 3. Components To Review

## Router

Question:

Does it reduce real work?

If routing logic creates more maintenance than value, simplify.

---

## Multi-agent Chain

Review existing chains:

```
Hermes
 -> WorkBuddy
 -> Codex
```

Only keep when the task requires it.

---

# 4. Components Not Default

The following are not default execution requirements:

- WorkBuddy every task
- Codex every task
- automatic decomposition
- automatic local/paid model splitting

---

# 5. Ollama Checkpoint

Ollama remains:

```
Model Provider
```

Not:

```
Agent
```

Its value is economic:

- reduce paid API usage
- provide local capability

Do not create a complex Ollama orchestration layer before proving necessity.

---

# 6. Implementation Order

Recommended order:

1. Freeze current architecture
2. Identify unnecessary mandatory paths
3. Preserve working execution loop
4. Simplify configuration
5. Test real tasks
6. Expand only from evidence

---

# 7. Success Criteria

AAF v0.6 succeeds when:

- user no longer manually transfers execution messages
- Hermes executes reliably
- cost is controlled
- components remain replaceable
- complexity stays proportional to value

---

# Final Rule

Do not build an agent system because it is possible.

Build only what removes real friction.
