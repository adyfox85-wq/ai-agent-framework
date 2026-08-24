# Automation notes

This prototype intentionally avoids UI automation. It shells out to each agent's non-interactive CLI and stores every prompt/result next to the final REPORT for auditability.

Current routing defaults:

- execution/change task -> Hermes -> WorkBuddy
- visual/review task -> WorkBuddy
- code/architecture/high-risk task -> add Codex after WorkBuddy

The Planner remains external for v0.2: it creates TASK content and later consumes REPORT.md. Automating ChatGPT project ingestion is a separate integration step and is not required to eliminate Agent-to-Agent copy/paste.
