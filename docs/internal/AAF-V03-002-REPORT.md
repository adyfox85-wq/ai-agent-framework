# AAF-V03-002-REPORT

- Task: AAF-V03-002 (Formal Task Lifecycle)
- Date: 2026-08-26
- Type: v0.3 开发任务（最小、正式、确定性 Task Lifecycle）
- Status: **COMPLETE — WorkBuddy APPROVE**
- Executor: Hermes / Reviewer: WorkBuddy

---

## 1. Implementation Status

**新增 `ai_agent_framework/task_lifecycle.py`**（69 行，零第三方依赖）：

| 能力 | 实现 |
|---|---|
| 状态模型 | `VALID_STATUSES = (CREATED, RUNNING, WAITING, SUCCESS, FAILED)`（无 ARCHIVED） |
| 状态文件 | `<output_dir>/task.json`（与 route.json/REPORT.md 同目录，Bridge 输出 = `<ws>/.aaf/<task-id>/task.json`） |
| 字段 | task_id / status / updated_at / task_path / workspace / report_path（+ internal reason） |
| 原子写 | 临时文件 → `os.replace`（避免部分写入损坏 JSON） |
| 写失败 | 抛 `LifecycleError`（不静默忽略） |
| 损坏恢复 | 读损坏抛错；更新时从新值重建 |
| 只读状态 | `read_status()`（缺失 → None） |

**runner.py（EXTEND ONLY，+58 行）**：

```
Validation 通过 → CREATED（resume: RUNNING + reason=RESUMED）
进入执行链     → RUNNING
完成           → SUCCESS（verdict=SUCCESS） / WAITING（其他）
dry-run        → CREATED + reason=DRY_RUN（不伪装 SUCCESS）
Framework 异常 → FAILED + reason=FRAMEWORK_ERROR → 重新抛出（保持调用方行为）
report 生成后  → 回填 report_path
```

## 2. Lifecycle State Model

| 状态 | 语义 | 触发 |
|---|---|---|
| CREATED | 通过 Validation，尚未执行 Agent 链 | run() 开始（含 dry-run 终态） |
| RUNNING | 执行链进行中 | 非 dry-run 进入 agents 循环；resume 时 |
| WAITING | 正常结束但有未解决问题 | `_aggregate_status` != SUCCESS |
| SUCCESS | 正常完成且结论成功 | `_aggregate_status` == SUCCESS |
| FAILED | Framework 级无法完成 | 未预期异常（route/report/lifecycle 写失败等） |

## 3. Transition Rules

```
validate(TASK) ─失败→ 抛 TaskValidationError（不进 Lifecycle）
validate 通过 → CREATED
normal run    → RUNNING → SUCCESS | WAITING
dry-run       → CREATED（reason=DRY_RUN，不伪装 SUCCESS）
resume        → RUNNING（reason=RESUMED）→ SUCCESS | WAITING | FAILED
异常          → FAILED（记录后重抛）
```

**边界**：agent 级 FRAMEWORK_ERROR 由现有逻辑捕获 → WAITING（v0.2 语义保持）；FAILED 仅由 Framework 级异常触发（不误吞 agent 失败）。

## 4. Test Status

✅ **143 passed in 1.45s**（124 基线 + 19 lifecycle 新增，零回归）：

- 模块：5 状态写读 / 非法 status（ARCHIVED）拒绝 / report_path 回填与保留 / 原子写无 .tmp 残留 / 损坏读抛错 / 损坏更新重建
- 集成：dry-run → CREATED+DRY_RUN / SUCCESS / WAITING / Framework 异常 → FAILED / Validation 失败不进 lifecycle / resume WAITING→RUNNING→SUCCESS（结果复用）

CLI 冒烟：合法 dry-run → task.json（CREATED + DRY_RUN + report_path 回填）；非法 → exit 2 + 无 task.json ✅

## 5. Review Status

| 轮次 | 结论 | 内容 |
|---|---|---|
| 唯一轮 | **APPROVE** ✅ | 9 项核心 + FAILED 边界全 VERIFIED；v0.2 核心零改动；3 个 minor（2 cosmetic 已清理：死代码 / resume reason 保留） |

## 6. Core Files Changed

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/task_lifecycle.py` | **新增**（69 行） |
| `ai_agent_framework/runner.py` | EXTEND ONLY（+58 行；run() 签名不变） |
| `tests/test_task_lifecycle.py` | **新增**（19 测试） |

**零改动**：router.py / report.py / adapters.py / bridge/* / TASK.md / REPORT.md

## 7. Git Commit Status

| 项 | 状态 |
|---|---|
| Commit | 待提交（`feat: AAF-V03-002 formal task lifecycle`） |
| 基线 | 本地 `9f14e8c` = 远程 `9f14e8c`（已同步） |

## 8. Remote Sync Status

| 项 | 状态 |
|---|---|
| 提交后 | `git push origin main`（失败有限重试；失败则 REMOTE_SYNC_PENDING，不阻塞本地完成） |

## 9. Unresolved Issues

无阻断问题。

非阻断备注：
1. **resume 语义保持 v0.2 现状**：`_load_resume_state` 仅排除 FRAMEWORK_ERROR 结果，真实 FAIL/REQUEST_CHANGE verdict 会被复用（不重试）——这是既有行为（EXTEND ONLY 保留），WorkBuddy 观察为测试缺口，非本任务范围
2. dry-run 终态 = CREATED + reason=DRY_RUN（不新增正式状态；任务 12 语义保留）
3. Bridge last_run.json 与 Framework task.json 职责分离，未改动
4. task.json 将成为 Task Registry / Artifact Archive / Session Continuity 的基础（本任务未实现）
