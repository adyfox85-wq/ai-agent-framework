# AAF v0.6 Implementation Boundary

Status: Boundary Freeze Draft

## Purpose

This document defines what AAF v0.6 keeps, removes, freezes, and postpones after the architecture reset.

The goal is preventing architecture expansion before real usage proves the need.

---

# 1. KEEP

## Planner -> Hermes -> Optional Review

The default workflow remains:

```
Planner
   |
   v
Hermes
   |
   v
Optional Review
```

This solves the original problem:

Remove manual copy/paste between planning and execution.

---

# 2. KEEP: Hermes as Execution Core

Hermes remains responsible for:

- receiving tasks
- executing operations
- using tools
- generating reports
- maintaining execution records

No replacement planned.

---

# 3. KEEP: Model Provider Concept

Models are providers, not agents.

Examples:

- Ollama local runtime
- API models
- free models
- paid models

The provider layer exists for economic flexibility.

---

# 4. KEEP: Plugin Thinking

Components should be replaceable.

## Planner

Possible:

- GPT
- DeepSeek
- future models

## Review

Possible:

- Codex
- WorkBuddy
- Kimi
- future tools

## Model Provider

Possible:

- Ollama
- API providers

---

# 5. REMOVE FROM DEFAULT FLOW

The following are not mandatory:

```
Planner
 ↓
Hermes
 ↓
WorkBuddy
 ↓
Codex
```

Reasons:

- high token consumption
- slower execution
- unnecessary for simple tasks
- increased failure points

---

# 6. POSTPONE

## Automatic Task Splitting

Not implemented by default.

Reason:

Splitting tasks into local model + paid model may create:

- routing complexity
- merge complexity
- additional token overhead
- harder debugging

Only introduce after measurable benefit.

---

## Complex Router

Not implemented.

Simple routing is preferred:

```
Need execution
        |
      Hermes
```

---

# 7. Ollama Boundary

Ollama remains inside the Hermes ecosystem.

It is not:

- a Planner
- an Agent
- a required extra execution layer

Primary objective:

Reduce paid API usage where practical.

---

# 8. Review Boundary

Review happens only when needed.

Examples:

Require review:

- high-risk code
- architecture changes
- security-sensitive changes

Usually no review:

- simple text processing
- normal file operations
- low-risk tasks

---

# 9. Development Rule

Before adding any new component, answer:

1. Does it reduce human work?
2. Does it reduce total cost?
3. Does it improve reliability?

If not, do not add it.

---

# 10. v0.6 Target

The target is not a larger agent system.

The target is a reliable personal AI workflow:

```
Think with Planner

Execute with Hermes

Review only when valuable
```

Simple first. Expand only from evidence.
