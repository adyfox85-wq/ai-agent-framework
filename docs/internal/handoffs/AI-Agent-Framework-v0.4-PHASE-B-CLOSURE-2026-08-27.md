# AI Agent Framework v0.4 — Phase B Closure（2026-08-27）

> Document Type: Durable Phase Closure / Handoff（冻结性质，与 PROJECT_STATE.md 的 Living 状态区分）
> Related: `docs/internal/PROJECT_STATE.md`（Living State）、`docs/internal/AAF_MASTER_BACKLOG.md`（RW-021 登记）
> 本报告只记录 Phase B closure 事实；不重新生成或覆盖 Phase A handoff
> （Phase A: `docs/internal/handoffs/AI-Agent-Framework-v0.4-PHASE-A-START-HANDOFF-2026-08-27.md`）。

---

## 1. Phase B Scope

Phase B — Bridge Background / Tray Skeleton（v0.4 主线第 B 阶段）：

- Background Bridge Host：`scripts/start_bridge.pyw`（pythonw 无控制台入口）；`bridge/main.py` 全部 print 改 `_log()`（pythonw 下安全），启动失败兜底写 `~/.aaf-bridge/bridge_error.log` + 弹窗
- Tray Skeleton：`bridge/tray.py`（ctypes `Shell_NotifyIconW` 零第三方依赖；菜单：打开状态 / 重启 Bridge / 退出 AAF + 灰显健康行；双击图标 = 打开状态）
- Status 最小窗口：`bridge/ui.py` `show_bridge_status()`（Bridge 状态 / 热键 / 当前项目 / 当前 Workspace / 最近 Task；Phase C 预留接入点）
- Restart Bridge：注销热键 → 启动新实例（pythonw + `AAF_BRIDGE_RESTART=1`）→ 旧实例退出；单实例命名 mutex（CreateMutexW + WAIT_ABANDONED 交接）
- Exit AAF：确认窗（提示不取消正在执行的任务）→ 只退出宿主；不写 cancel.request / control.json / task.json / run.json
- Hotkey Health（最小范围）：`classify_bridge_health()`（OK / DEGRADED，5s 轮询，Tray 图标反映）
- Core / UI 边界：Desktop Shell 只读产物（last_run.json / config / task.json），不复制 Router / Runner / Lifecycle / Agent adapters / TASK / REPORT 协议

不实现（Phase B 边界）：CANCELLED / cancel.request / control.json / state.lock / launch registry / force kill / Safe Cancel / progress / stuck / 完整状态窗口 / Chinese-first UI / project switching / Duplicate UX / autostart / RW-020。

## 2. Implementation Commit

- Commit: `6a9814d04675a8012e6c3ab27c61de69ba99b704` — `feat(v0.4-phase-b): bridge background host + tray skeleton`
- Remote Sync: SYNCED（本地 main == origin/main）

## 3. Closure Validation Evidence（AAF-v0.4-TASK-002-FIX-001）

真实 Windows 桌面会话验收（2026-08-27），全部为实测证据（`.aaf/AAF-v0.4-TASK-002-FIX-001/`：EVIDENCE.md、status_window.png、s1–s6 步骤脚本、REPORT.md）：

| 验收项 | 结果 |
|---|---|
| Ctrl+Alt+A 原占用来源确认 | 原 error 1409 来源 = TASK-002 实施前遗留的旧 Bridge 自身（`python -m bridge.main`），非第三方程序；旧实例安全退出后新 Bridge 注册成功 |
| Background pythonw Bridge | PASS — 无控制台常驻，可脱离 PowerShell / Terminal |
| Tray | PASS — Shell_NotifyIconGetRect 实测可见；状态窗口打开/关闭不退出 Bridge |
| Single instance | PASS — 命名 mutex；全程断言实例数 = 1 |
| Ctrl+Alt+A real GUI E2E | PASS — Hotkey → Clipboard → TASK validation → Confirmation → Launcher → Framework → REPORT 全链路（Cancel 路径不落盘；Execute 路径 SUCCESS/COMPLETED） |
| Restart regression | PASS — 重启后单实例 / Tray / Hotkey 全部恢复 |
| Exit regression | PASS — Exit AAF 不修改 canonical task terminal state（状态快照 diff 0/0/0） |
| Test regression | 233 passed（与 baseline 一致，零代码修改） |

## 4. Tests

- `pytest -q` = **233 passed**（216 baseline + 17 新增 `tests/test_bridge_tray.py`，零下降）
- Executor 实测 233 passed in 3.26s；WorkBuddy 独立复跑 233 passed in 3.00s

## 5. Agent Verdicts

- WorkBuddy: **PASS_WITH_WARNING**（唯一 warning = Codex closure review 延迟执行，后已由 Codex 独立完成）
- Codex: **APPROVE**（未发现代码、架构或 lifecycle blocker；Phase B 可判定 COMPLETE，不需要代码返工）
- Blocking: **NONE**
- 未完成项（非阻塞）：无框架侧未完成项

## 6. New Backlog Observation（本任务登记）

真实验收中发现新缺口（非 Phase B blocker，不重开 Phase B）：

**Bridge Restart / Exit Completion Notification Continuity**

- Framework runner / validation task 可以继续运行并最终生成 SUCCESS REPORT
- 但启动该 task 的原 Bridge instance 被 Restart / Exit 后，新 Bridge instance 不会自动恢复原 launcher wait-thread / completion callback
- 用户没有收到原有「任务完成」提示 / Planner Handoff copy action，只能手工发现 REPORT.md

已长期登记：`docs/internal/AAF_MASTER_BACKLOG.md` → **RW-021**（OPEN / P2）。
与 RW-020（runner 已死亡的孤儿 RUNNING）明确区分：本问题中 runner 存活并成功完成，仅 Bridge 换代后 notification continuity 丢失。
本 closure 任务只登记，不实现 reattachment / launch registry（Phase E 范畴）。

## 7. Next Phase Candidate

**Phase C — Status Window + Chinese-first UI**

- 仅标记 Next Phase Candidate；Phase C 不得标记 STARTED
- Phase C 必须由 Planner 后续正式生成 TASK 才算启动
- 本任务不启动 Phase C

## 8. Git / Remote Sync

- Branch: main；closure sync 提交后 local main == origin/main，ahead/behind = 0/0
- 本 closure 报告提交与 PROJECT_STATE / AAF_MASTER_BACKLOG 同步提交
