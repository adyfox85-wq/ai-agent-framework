# AAF Real-World Hotfix — Router Local Readonly Constraint

- Date: 2026-08-27
- Type: real-world router hotfix（不修改 Lifecycle/Bridge/adapters/Boundary；不启动 v0.4）
- Status: **COMPLETE — WorkBuddy APPROVE + Codex APPROVE**
- 触发: AAF-MAINT-001 路由错误（执行任务被误判 review-only）

---

## Root Cause

`ai_agent_framework/router.py` 的 `STRONG_READONLY_SIGNALS` 含 `不修改任何` 等宽泛表达；AAF-MAINT-001 的局部约束「不修改任何 Framework 功能代码」（真实语义：禁止改产品功能代码）命中该信号 → `decide_route` 优先判 review-only → 路由 `workbuddy -> codex`，**Hermes 被错误跳过**（执行动作：创建 backlog / 更新 PROJECT_STATE / commit+push 全部被压制）。

## Fix（最小语义修复）

`ai_agent_framework/router.py`：

1. **STRONG_READONLY_SIGNALS 收窄**为无歧义整体只读：`只检查` / `只读` / `read-only` / `only review`（移除 `不修改任何` / `不要修改任何` / `不进行任何修改` / `without modifying` / `no modification`）
2. **新增 GLOBAL_READONLY_SIGNALS**（文件/仓库级真正全局只读，可压过执行词）：`不修改任何文件/仓库/东西/内容`、`整个任务只读`、`整体只读`、`without modifying any file/files/repository/project/anything`、`no changes to any files` 等
3. **decide_route 顺序**：`global_readonly_hit OR (strong_readonly_hit AND not execution_hit)` → review-only；否则 `execution_hit` → `hermes -> workbuddy (-> codex)`——执行意图优先于局部只读约束
4. **EXECUTION_WORDS 新增 `更新`**（"更新 PROJECT_STATE.md" 是执行意图）

## Regression Cases（tests/test_router.py，8 个）

| Case | 输入 | 期望 |
|---|---|---|
| 1 | 创建 AAF_MASTER_BACKLOG.md，但不修改任何 Framework 功能代码 | 含 Hermes ✅ |
| 2 | 更新 PROJECT_STATE.md，不修改任何 Router/Bridge 代码 | 含 Hermes ✅ |
| 3 | 只读检查仓库，不修改任何文件 | 不含 Hermes ✅ |
| 4 | 对代码做只读审查，不修改任何文件 | workbuddy -> codex ✅ |
| 5 | 普通执行任务（实现登录页面功能） | hermes -> workbuddy ✅ |
| 6 | 普通 review 任务（复核结果报告） | 不含 Hermes ✅ |
| 7 | create docs without modifying any framework code（英文局部） | 含 Hermes ✅ |
| 8 | review the page design, without modifying any file（英文全局） | 不含 Hermes ✅ |

## Tests

✅ **206 passed**（198 + 8 新；1 次 flaky session 测试失败经单独/重跑确认非回归）

## WorkBuddy

**APPROVE** ✅（6 项 VERIFIED；2 non-blocking 观察：'不修改任何代码' 未入 GLOBAL（有意避免"创建 X 但不修改任何代码"误判）；文档未同步 STRONG/GLOBAL 拆分说明（optional））

## Codex

**APPROVE** ✅（首轮 REQUEST_CHANGE：英文局部 `without modifying any` 同样过宽 → 收窄为文件/仓库级 + 补 case7/8 → 最终 APPROVE）

## Core Files Changed

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/router.py` | STRONG 收窄 + GLOBAL 新增 + decide_route 顺序 + EXECUTION_WORDS |
| `tests/test_router.py` | +8 regression tests |

**未触碰**：Lifecycle / Bridge / adapters / Boundary / 其他执行链。

## AAF-MAINT-001

Retry Ready（不自动执行；由 Planner 决定重新提交或 resume）。
