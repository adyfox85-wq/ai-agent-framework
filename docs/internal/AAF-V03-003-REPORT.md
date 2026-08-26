# AAF-V03-003-REPORT

- Task: AAF-V03-003 (Formal Task Artifact Archive)
- Date: 2026-08-26
- Type: v0.3 开发任务（Task Package 显式归档）
- Status: **COMPLETE — WorkBuddy APPROVE**
- Executor: Hermes / Reviewer: WorkBuddy

---

## 1. Implementation Status

**新增 `ai_agent_framework/task_archive.py`**（184 行，零第三方依赖）+ `task_archive_cli.py`（独立 CLI）：

| 能力 | 实现 |
|---|---|
| Archive 单位 | 整个 Task Package：`<ws>/.aaf/<Task-ID>/` → `<ws>/.aaf/archive/<Task-ID>/`（shutil.move 同卷 rename） |
| 可归档 | SUCCESS / WAITING / FAILED |
| 拒绝 | CREATED / RUNNING → `TASK_NOT_ARCHIVABLE`（source 不变、零移动） |
| 覆盖保护 | 目标已存在 → `ARCHIVE_TARGET_EXISTS`（不覆盖其他包） |
| 状态不变 | task.json.status 归档后仍是原终态（Execution ≠ Storage Lifecycle） |
| metadata | 归档加 `archived_at`（非正式状态）；restore 清除 |
| 保留产物 | 全部文件移动（route/run/task/REPORT/agent results），不删除 |
| 失败行为 | 不伪装成功：SOURCE_NOT_FOUND / TASK_JSON_UNREADABLE / MOVE_FAILED / METADATA_WRITE_FAILED |
| Restore | archive → active，不改 status，目标已存在 → `RESTORE_TARGET_EXISTS`（无双份权威包） |
| REPORT 定位 | `find_report_path(task_id, workspace)`：active → archive 兜底 |
| CLI | `python -m ai_agent_framework.task_archive_cli archive|restore`（**不碰 run.py**） |

**Bridge 兼容（方案 B：resolver，职责清晰）**：`handoff.read_report` 增加 archived 兜底——原 report_path 失效时自动推导 `.aaf/archive/<Task-ID>/` 变体；**不修改 last_run.json**（非最近任务归档天然不受影响）。

## 2. Archive Storage Model

```
<Workspace>\.aaf\
├── <Task-ID>\              # ACTIVE（运行产物：task/route/run/REPORT/agent results）
└── archive\<Task-ID>\      # ARCHIVED（显式归档，全包移动，status 不变）
```

## 3. Eligibility Rules

| status | 可归档 | 说明 |
|---|---|---|
| SUCCESS | ✅ | 终态 |
| WAITING | ✅ | 本轮终态；可 restore 后 resume |
| FAILED | ✅ | 终态 |
| CREATED | ❌ TASK_NOT_ARCHIVABLE | 未执行 Agent 链 |
| RUNNING | ❌ TASK_NOT_ARCHIVABLE | 执行中 |

## 4. Restore / Resume Handling

- `restore_package(archive_path, active_root)`：archive → active（同卷 move），status 不变，清除 archived_at
- restore 后 `route.json` / `task.json` 完整 → 现有 `runner.run(..., resume_from=active)` 可直接 resume WAITING 任务
- 不设计大型 restore subsystem（任务 27/28 最小方案）

## 5. Bridge Compatibility

- **方案 B（resolver）**：`task_archive.archived_report_path(report_path)` 负责路径推导；`handoff.read_report` 负责兜底决策
- 原 report_path 失效 → 自动读 archived REPORT → **Copy Last Report 归档后仍有效** ✅
- 不修改 last_run.json；非最近任务归档不受影响 ✅

## 6. Test Status

✅ **159 passed in 1.50s**（143 基线 + 16 archive 新增，零回归）：

- SUCCESS/WAITING/FAILED 归档（全部产物保留，列表级校验）/ CREATED/RUNNING 拒绝（source 不变）/ 覆盖保护（archive + restore）/ status 不变 + archived_at / 失败行为（source 缺失/task.json 缺失）/ REPORT 定位（active→archive 转换）/ Bridge 兜底（归档后 read_report 生效 + 无副作用）/ restore（WAITING 不变 + 可 resume）/ 双份防护

CLI 冒烟 ✅：archive（全产物 + 机器可读 JSON）→ CREATED 拒绝 exit 2 → restore（状态不变）全流程。

## 7. Review Status

| 轮次 | 结论 | 内容 |
|---|---|---|
| 唯一轮 | **APPROVE** ✅ | 10 项核心全 VERIFIED；Execution/Storage Lifecycle 分离清晰；v0.2 核心零改动；4 minor 中 2 个已修（错误码语义 / restore 清 metadata） |

## 8. Core Files Changed

| 文件 | 变更 |
|---|---|
| `ai_agent_framework/task_archive.py` | **新增**（184 行） |
| `ai_agent_framework/task_archive_cli.py` | **新增**（独立 CLI） |
| `bridge/handoff.py` | read_report 增加 archived 兜底（+12 行） |
| `tests/test_task_archive.py` | **新增**（16 测试） |

**零改动**：router.py / report.py / adapters.py / runner.py / task_lifecycle.py / TASK.md / REPORT.md

## 9. Git Commit Status

| 项 | 状态 |
|---|---|
| Commit | 待提交（`feat: AAF-V03-003 formal task artifact archive`） |
| 基线 | 本地 `98dcab8` = 远程 `98dcab8`（已同步） |

## 10. Remote Sync Status

| 项 | 状态 |
|---|---|
| 提交后 | `git push origin main`（失败有限重试；失败记录 REMOTE_SYNC_PENDING，不阻塞本地完成） |

## 11. Unresolved Issues

无阻断问题。

非阻断备注（WorkBuddy 记录，本任务不处理）：
1. 跨卷 move 非原子保护（同卷正常；.aaf/ → .aaf/archive/ 恒同卷）
2. target-exists 检查与 move 之间 TOCTOU（本地单用户工具可接受）
3. 本任务未实现自动归档（任务 30 显式动作 ✅）、retention、ZIP、Registry
