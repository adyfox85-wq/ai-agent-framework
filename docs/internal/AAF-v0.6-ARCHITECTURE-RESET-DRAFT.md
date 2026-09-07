# AAF v0.6 Architecture Reset Draft

## Purpose

This document records the architectural reset discussion after AAF v0.5.

The original goal of AAF was not to create a complex multi-agent system. The original problem was:

> Remove manual copy/paste between GPT planning and Hermes execution.

## Core Direction

AAF v0.6 returns to a lightweight collaboration model:

```
Planner (GPT / DeepSeek)
        |
        v
Hermes Executor
        |
        v
Optional Review
```

## Removed Default Flow

The previous mandatory chain:

```
GPT
 ↓
Hermes
 ↓
WorkBuddy
 ↓
Codex
```

is not the default execution path anymore.

Reason:

- excessive token consumption
- unnecessary reviews for normal tasks
- increased system complexity
- deviation from the original goal

## Review Design

Review becomes optional and capability-based.

Examples:

- WorkBuddy: UI verification / second opinion
- Codex: high-risk code review
- Other models may replace these roles later

Review tools are plugins, not fixed agents.

## Model Provider Direction

Ollama is not treated as a separate Agent.

Ollama remains a local model runtime/provider used by Hermes.

Primary purpose:

- reduce paid API usage
- handle suitable low-cost tasks locally
- provide fallback capability

Possible models:

- Qwen family models
- other local models supported by Ollama

Important constraint:

Do not introduce complex routing logic unless real usage proves necessary.

## Economic Routing Principle

The system should prefer:

1. local/free models when they are sufficient
2. free API models when appropriate
3. paid API models only when required

However, task splitting must not create more overhead than it saves.

## Plugin Principle

Future components should be replaceable:

- Planner: GPT, DeepSeek, other models
- Executor: Hermes
- Review: Codex, WorkBuddy, Kimi, other tools
- Model Provider: Ollama, API providers

AAF should define interfaces, not lock specific products.

## Current Decision

Before adding automatic task decomposition, validate the simple path first:

```
Planner -> Hermes -> Optional Review
```

Ollama remains a cost optimization layer inside the Hermes execution ecosystem, not a new top-level Agent.
