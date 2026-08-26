# AAF-V03-PUBLIC-001-REPORT

- Task: AAF-V03-PUBLIC-001 (v0.3 Public Release Readiness — README / Install / Quick Start)
- Date: 2026-08-27
- Type: Public Documentation / Release Readiness（不新增产品功能；不启动 v0.4）
- Status: **COMPLETE — WorkBuddy APPROVE + Codex APPROVE**

---

## Docs Changed

| 文件 | 变更 |
|---|---|
| `README.md` | v0.2 → v0.3 重写（92 行 → ~290 行） |
| `docs/QUICKSTART.md` | **新增**（12 步新用户流程） |
| `docs/TROUBLESHOOTING.md` | **新增**（9 类故障 A-I） |

未修改任何功能代码（git 仅 3 个文档文件）。

## README Structure

首屏（30 秒内）→ 定位（是什么/不是什么）→ 角色表 → Requirements → Installation → Bootstrap Check → **⚠️ 先启动 Bridge** → Bridge 配置 → Planner TASK 格式 → Quick Start 12 步 → 运行时行为 → Runtime Artifacts → Lifecycle → Resume → Archive → Session Continuity → Boundary Control → Troubleshooting → Known Limitations → Real-World Validation → 版本 → 测试。

## Installation Model

- `git clone https://github.com/adyfox85-wq/ai-agent-framework.git` + `cd`
- **明确无 pip package / installer**（明确警告不要运行不存在的 `pip install ai-agent-framework`）
- Agent CLI（hermes / codebuddy / codex）需用户独立安装、登录、配置（已声明）

## Quick Start Model

12 步：Clone → 确认 CLI → **启动 Bridge** → 配置 Project/Workspace → Planner 输出 TASK → Copy → Ctrl+Alt+A → 确认弹窗 → Execute → 后台运行 → Copy Report → 回 Planner。
Bridge 必须先启动的提醒置于 Quick Start 前部（真实使用踩坑点）。

## Known Limitations（已在 README 诚实列出）

Windows 为主 / 无开机自启 / 无自动切换项目 / hotkey listener 偶发失活（已知 runtime issue，重启恢复）/ TASK parser 格式较严格 / 无 installer / 无 pip package / 不自动写回 ChatGPT / 不自动下一 TASK。

## Real-world issues documented

1. Bridge 必须先启动（Quick Start 前部）
2. Bridge 无开机自启（Known Limitations）
3. hotkey listener 失效（Troubleshooting H + Known Limitations）
4. TASK Markdown 转义导致校验失败（TASK Format 提醒 + Troubleshooting B/C）
5. Codex hash 目录升级 MISSING_COMMAND → fallback（hotfix 7cbf594，Troubleshooting E + Real-World Validation）
6. Project binding via config.json（Bridge 配置节）
7. config 热加载（Bridge 配置节）
8. uv venv shim+real 两层 ≠ 多实例（Troubleshooting I）

## Test Status

✅ **198 passed**（v0.3 closure 191 + Codex discovery hotfix 7；文档任务不改代码，数字无变化；已重跑确认）

## WorkBuddy Review

**APPROVE** ✅（16 项检查全 VERIFIED；2 non-blocking 观察：run.py --help banner 仍写 v0.2（pre-existing 代码，不在文档范围）；Workspace 校验来源为 Bridge 而非 parser（用户可见行为一致））

## Codex Review

**APPROVE** ✅（首轮 REQUEST_CHANGE → 修复 2 ISSUE（resume 措辞扩大 + boundary CLI 示例 workspace）→ 二轮 REQUEST_CHANGE → 修复残留（QUICKSTART 末句"修复再 resume"误导）→ 三轮 APPROVE）
- 修复项：resume 说明限定 FRAMEWORK_ERROR；业务性 FAIL/REQUEST_CHANGE 会被复用（不重跑）；boundary CLI 示例显式 `--workspace <业务项目>`

## Git Commit

- `git commit` 见下
- 禁止项未触碰（无 force push / reset / rebase / amend / clean）

## Remote Sync

见下（push 结果）。

## Unresolved Issues

None blocking。已知 non-blocking：run.py --help banner 文案仍为 v0.2（后续代码级顺手更新候选，非本任务范围）。
