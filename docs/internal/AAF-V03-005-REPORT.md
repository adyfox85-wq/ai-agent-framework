# AAF-V03-005-REPORT

- Task: AAF-V03-005 (Formal Project Boundary Control)
- Date: 2026-08-26
- Type: v0.3 开发任务（轻量边界表达/读取/检查/warning）
- Status: **COMPLETE — WorkBuddy APPROVE**（1 轮 REQUEST_CHANGE → 修复 → APPROVE）
- Executor: Hermes / Reviewer: WorkBuddy

---

## 1. Implementation Status

**新增 `ai_agent_framework/project_boundary.py`**（280 行）+ `project_boundary_cli.py`（CLI）+ runner/session 最小集成：

| 能力 | 实现 |
|---|---|
| Boundary Source | `docs/PROJECT_SCOPE.md`（真实检查发现并 **EXTEND ONLY**，备份在 `.aaf-backup/`；未另造竞争文件） |
| 确定性 parser | Core Goal / Current Scope / Frozen Boundaries / Approved Extensions / Backlog / Last Updated（中英标题 + `A / B / C` 多概念拆分） |
| 缺失 | `BOUNDARY_NOT_CONFIGURED`（不崩溃，configured=False） |
| Task Check | `check_task`：frozen path 显式命中 → **HIGH**；frozen 短语命中 → **MEDIUM**；无 → **NONE** |
| WARNING-FIRST | 默认不阻断 Router（HIGH 也继续执行） |
| 确定性 | 子串/exact match + 路径 token 正则 + 否定前缀归一化；无 LLM / 无 Agent |
| boundary.json | task_id/configured/severity/warnings/matched_boundaries/checked_at/source_path（原子写） |
| 顺序 | TASK → Validation → **Boundary Check** → Router（Validation 失败跳过） |
| 失败行为 | Boundary 模块错误 fail-open + 明确 warning（外围不使核心链路不可用） |
| CLI | `show` / `check <task>` / `add-backlog <item>`（显式动作，唯一修改 Scope 入口） |
| 不越界 | 不自动修改 Scope / 不自动加 Backlog / 不改 task.json.status / 不建库 / 不调 Agent |

## 2. Boundary Source Model

```
<Workspace>/PROJECT_SCOPE.md 或 <Workspace>/docs/PROJECT_SCOPE.md
（存在即正式 Boundary Source；本仓库：docs/PROJECT_SCOPE.md，v0.1 内容保留 + v0.3 正式 sections 追加）
```

## 3. Scope Data Model

`ProjectBoundary`：core_goal / current_scope / frozen_boundaries / approved_extensions / backlog / source_path / configured / parse_error

## 4. Boundary Check Model

```
check_task(boundary, task_text)
→ 组合 Objective/Requirements/Scope/Files/Background 字段文本
→ 1) frozen path token 子串命中 → HIGH（如 docs/internal）
→ 2) frozen 短语（/ 拆分 + 否定前缀归一化）命中 → MEDIUM（如 Hermes 配置）
→ 否则 NONE
→ 结果写 boundary.json（不阻断 Router）
```

## 5. Warning Severity Model

| severity | 触发 | 行为 |
|---|---|---|
| NONE | 无显式边界冲突 | 正常执行 |
| LOW | （预留） | — |
| MEDIUM | frozen 短语命中 | warning + 继续执行 |
| HIGH | 显式 frozen path 命中 | warning + 继续执行（warning-first） |

## 6. Session Integration

- `rollover` 数据优先级（修复后）：显式参数 → **PROJECT_SCOPE** → PROJECT_STATE → UNKNOWN
- NEXT_SESSION_START 携带 PROJECT_SCOPE 的 Frozen Boundaries + Current Scope
- PROJECT_SCOPE 缺失 → 退回原 PROJECT_STATE 逻辑（Session 不破坏）

## 7. Test Status

✅ **191 passed in 1.82s**（173 基线 + 18 boundary 新增，零回归）：

- parse（真实 repo scope + 各节）/ missing scope / malformed / backlog 分离 / 显式 scope 文件
- check：normal NONE / frozen 短语 MEDIUM / **真实多概念条目 MEDIUM** / frozen path HIGH / unconfigured 无 warning
- boundary.json 字段完整 + 原子写
- runner 集成：**HIGH warning 不阻断 Router**（REPORT+route.json 照常生成）/ **Validation 失败跳过 Boundary**
- Session：继承 SCOPE（Core Goal/Frozen/Current Scope）/ 缺失不破坏 / **SCOPE 优先于 STATE**

CLI 冒烟 ✅：show（真实仓库解析）/ check（正常 NONE / 真实 frozen path HIGH）

## 8. Review Status

| 轮次 | 结论 | 内容 |
|---|---|---|
| 第 1 轮 | **REQUEST_CHANGE** | ① 真实多概念 `/` 条目被路径判断误跳过（frozen 检测对真实 scope 无效）② Session 优先级反转（STATE 先于 SCOPE） |
| 第 2 轮 | **APPROVE** ✅ | 两项修复 VERIFIED（含新增测试）；2 minor 非阻断（HIGH 时冗余 MEDIUM warning 无害 / Current Scope 无 STATE fallback 属预期） |

## 9. Core Files Changed

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/project_boundary.py` | **新增**（280 行） |
| `ai_agent_framework/project_boundary_cli.py` | **新增**（CLI） |
| `ai_agent_framework/runner.py` | +15（Boundary Check 集成） |
| `ai_agent_framework/session_continuity.py` | +20（PROJECT_SCOPE 优先继承） |
| `docs/PROJECT_SCOPE.md` | **EXTEND ONLY**（追加正式 sections；备份 `.aaf-backup/PROJECT_SCOPE.md.before-aaf-v03-005-20260826-224822`） |
| `tests/test_project_boundary.py` | **新增**（18 测试） |

**零改动**：router.py / report.py / adapters.py / task_validation / task_lifecycle / task_archive

## 10. Git Commit Status

| 项 | 状态 |
|---|---|
| Commit | 待提交（`feat: AAF-V03-005 formal project boundary control`） |
| 基线 | 本地 `e1c8e9f` = 远程 `e1c8e9f`（已同步） |

## 11. Remote Sync Status

| 项 | 状态 |
|---|---|
| 提交后 | `git push origin main`（失败有限重试；失败记录 REMOTE_SYNC_PENDING） |

## 12. Unresolved Issues

无阻断问题。

非阻断备注：
1. HIGH 路径命中时短语循环可能多发一条冗余 MEDIUM warning（severity 仍 HIGH，无害）
2. NEXT_SESSION_START 的 Current Scope 只来自 PROJECT_SCOPE（无 PROJECT_STATE fallback，符合"正式 Boundary Source"设计）
3. 本任务未实现：DECISION_LOG / 硬阻断 / LLM 分类 / embeddings / Roadmap / Ticket 系统（明确 Excluded）
