# AI Agent Framework v0.2 Prototype

A minimal local runner for the validated workflow:

`Planner -> TASK.md -> Router -> Hermes -> WorkBuddy -> Codex(optional) -> REPORT.md -> Planner`

The router may skip Hermes for review/visual tasks. Codex is added for code/architecture/high-risk review.

## Requirements

- Python 3.11+
- Hermes CLI available as `hermes`
- Tencent CodeBuddy/WorkBuddy CLI available as `codebuddy`
- Codex CLI available as `codex` (only required when the route includes Codex)

Hermes supports single-query file input; CodeBuddy supports headless `-p`; Codex supports non-interactive `exec`.

## First run

From this folder:

```powershell
python run.py .\TASK.md --workspace "D:\AdyAI\guoxue-skills-lab" --output "D:\AdyAI\guoxue-skills-lab\.aaf\TASK-003" --dry-run
```

Inspect `route.json`. Then run for real by removing `--dry-run`:

```powershell
python run.py .\TASK.md --workspace "D:\AdyAI\guoxue-skills-lab" --output "D:\AdyAI\guoxue-skills-lab\.aaf\TASK-003"
```

The final machine handoff is `REPORT.md` in the output directory.

## Bootstrap checks

```powershell
hermes --version
codebuddy --version
codex --version
python --version
```

If an agent command is absent, the run stops with `WAITING` and records the missing command in `REPORT.md` instead of silently skipping validation/review.
