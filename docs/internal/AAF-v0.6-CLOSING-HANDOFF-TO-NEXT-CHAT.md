# AAF v0.6 Closing Handoff To Next Chat

## Purpose

This document is the handoff checkpoint before ending the current planning conversation and starting a new one.

The next chat must treat this document as the current context boundary.

---

# 1. Current Decision

AAF has entered v0.6 architecture reset.

The main conclusion:

AAF should not continue expanding into a complex mandatory multi-agent framework.

The original problem was:

> Remove manual copy/paste between Planner and Hermes.

Not:

> Build the largest possible multi-agent system.

---

# 2. Frozen Architecture

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

---

# 3. Role Boundaries

## Planner

Responsible for:

- understanding intent
- creating TASK instructions
- deciding execution scope

Replaceable:

- ChatGPT
- DeepSeek
- future models

---

## Hermes

Execution center.

Responsible for:

- task execution
- tool usage
- reports
- evidence collection

---

## Ollama

Frozen position:

Ollama is a local model provider/runtime.

It is NOT:

- an independent Agent
- a Planner
- a mandatory routing layer

Purpose:

- reduce paid API cost
- provide local inference capability

Do not create complex splitting unless real usage proves value.

---

## Review

Review is optional and plugin-based.

Examples:

- Codex: high-risk code review
- WorkBuddy: UI verification / second opinion
- Kimi or others: possible future replacements

---

# 4. Removed Default Behavior

Do not restore:

```
Planner
 ↓
Hermes
 ↓
WorkBuddy
 ↓
Codex
```

for every task.

Reasons:

- excessive token cost
- unnecessary latency
- complexity growth

---

# 5. Important Discussion Outcome

Automatic task splitting was discussed:

Example:

```
Task
 ↓
Simple part → Ollama
Complex part → Paid API
 ↓
Merge
```

Conclusion:

Possible technically, but NOT default implementation direction.

Reason:

The routing and merge system may cost more complexity than it saves.

Validate simple architecture first.

---

# 6. Existing v0.6 Documents

Repository:

adyfox85-wq/ai-agent-framework

Location:

docs/internal/

Files:

- AAF-v0.6-ARCHITECTURE-RESET-DRAFT.md
- AAF-v0.6-FINAL-DESIGN.md
- AAF-v0.6-IMPLEMENTATION-BOUNDARY.md
- AAF-v0.6-EXECUTION-PROTOCOL.md
- AAF-v0.6-PRE-IMPLEMENTATION-CHECK.md

---

# 7. Next Chat Starting Point

Do NOT redesign architecture again.

Next step should be:

1. Read this handoff.
2. Confirm v0.6 boundaries.
3. Perform read-only repository audit.
4. Identify v0.5 components to keep/archive.
5. Only then create implementation tasks.

---

# 8. Safety Rules

Avoid:

- architecture expansion
- adding agents because they exist
- adding routers without evidence
- rebuilding solved parts

Prefer:

- simple workflow
- measurable benefit
- evidence-driven expansion
