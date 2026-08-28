# REPORT

## Current Status
SUCCESS（Phase F Implementation + 72 项新测试 + 真实 Windows E2E A–I 全部通过；760 passed；
正式 COMPLETE 判定留待 WorkBuddy 独立验证 + Codex 审查后由 Planner 确认）

## Route
hermes（本实现任务）-> workbuddy（待独立验证）-> codex（待审查）

## Original Task
AAF-v0.4-TASK-006 — Phase F Project Switching and Duplicate Task UX
（完整 TASK 见 .aaf/tasks/active/AAF-v0.4-TASK-006.md 与 .aaf/AAF-v0.4-TASK-006/TASK.snapshot.md）

## 实现总结

按冻结设计（docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md §9 Project Switching /
§10 Duplicate Task UX）实现，未重新设计；全部决策逻辑与 UI 分离，可单测。

### 新增文件
- `bridge/workspace.py` — TASK Workspace 校验与分类纯函数：
  check_workspace（fail closed：空 / malformed / 控制字符 / NUL / 非绝对路径 /
  不存在 / 非目录 / 无权限 / Bridge 私有目录安全校验）；classify_workspace →
  SAME / KNOWN / UNKNOWN / INVALID（设计 §9）
- `bridge/duplicate.py` — duplicate 状态卡片数据（设计 §10）：running（registry
  活跃 launch / launcher 当前任务）/ completed（终态 SUCCESS / WAITING / FAILED /
  CANCELLED）/ abnormal（残留 RUNNING / CREATED）/ unknown（无 task.json）；
  REPORT 路径 = task.json.report_path → task_archive.find_report_path 归档兜底；
  最近活动 = 产物最大 mtime；判定基础 = canonical TASK.md 落盘路径存在（与
  save_task 同一判定，未放宽 duplicate protection）
- `bridge/intake.py` — 提交流程决策（纯逻辑）：plan_submission（只读决策）+
  apply_submission（确认后切换持久化 + 落盘）；决策矩阵：
  SAME → proceed（无额外确认，req 2）；KNOWN → confirm_switch（req 3）；
  UNKNOWN → confirm_unknown（fail-safe，req 4）；INVALID → reject fail closed
  （req 5）；launcher RUNNING + 目标 workspace 不同 → reject（req 7）；
  duplicate running → reject 不启动第二 runner（req 9）；duplicate
  completed/abnormal/unknown → reject + 卡片（需新 Task ID，req 10，不另造
  rerun 架构）；确认后切换持久化唯一入口 config.update_project（req 6/12）
- `tests/fixtures/run_dry.py` — 真实 run.py 的 dry-run 包装（真实 runner 子进程 +
  真实文件契约，零 Agent 依赖；Phase E 同款确定性约束）
- `tests/test_phase_f_workspace.py`（18 项）/ `tests/test_phase_f_duplicate.py`
  （20 项）/ `tests/test_phase_f_intake.py`（25 项）/ `tests/test_phase_f_e2e.py`
  （9 项真实 Windows E2E A–I）

### 修改文件
- `bridge/config.py` — recent_projects（上限 5，按 last_used 倒序）+ update_project
  （唯一切换持久化入口，原子写）+ known_workspaces / same_workspace /
  normalize_workspace / project_name_for
- `bridge/ui.py` — 「切换项目确认」窗（当前项目 / 目标项目 / Workspace / Task ID /
  「将修改 AAF Bridge 的项目设置」+ 陌生路径红色警示；[切换并执行] / [取消]）与
  「任务已存在」状态卡片（状态中文映射 + 英文原值 / 阶段 / 最近活动 / 结果 /
  REPORT 路径；[查看状态] / [打开 REPORT] / [关闭]），中文优先（req 11）
- `bridge/main.py` — _process_clipboard 接入 intake 流程：决策 → reject（错误 /
  duplicate 卡片）→ 切换确认 → apply_submission（切换持久化 + 落盘）→
  launcher.launch（既有并发保护不变）；duplicate 卡片 [查看状态] 复用状态窗口、
  [打开 REPORT] 用 os.startfile
- `docs/internal/PROJECT_STATE.md` — Phase F = IMPLEMENTATION DELIVERED（正式
  COMPLETE 判定留待 route 验证，符合项目惯例）；Next Step = Planner v0.4
  Remaining-Issues Retrospective → Runtime Integrity batch planning
- `docs/internal/AAF_MASTER_BACKLOG.md` — RW-003 / RW-016 OPEN → SOLVED（设计
  §9/§10 全量落地）；RW-006 OPEN → SOLVED（仅按 Phase C/D/E/F 真实交付证据校正
  状态，不重新开发）；RW-009 / RW-014 状态核对保持 PARTIAL（无新交付，未扩大
  scope）；Summary 表同步

### Backlog 收口证据（req 15）
- RW-003 SOLVED：workspace 识别（canonical TASK Workspace 字段）+ 已知/陌生确认切换 +
  recent_projects + 切换持久化 + RUNNING 保护，全部由 E2E B/C/D/E/F/I 实证
- RW-016 SOLVED：duplicate 状态卡片（running/completed/abnormal/unknown 分类 +
  中文展示 + 不覆盖 artifacts + REPORT 入口），由 E2E G/H + 单元测试实证
- RW-006 SOLVED（状态校正）：Phase C（状态窗口）/ D（进度估算 + stuck 提示）/
  E（停止/强制停止入口）/ F（项目切换 + duplicate 卡片）真实交付证据闭合全部
  Remaining Gap；未重新开发
- RW-009 / RW-014：仅状态核对，无新交付 → 保持 PARTIAL（与 TASK 范围一致）

## 测试证据
- 全量：`python -m pytest tests/ -q` → **760 passed**（688 基线 + 72 新增，零下降）
- Phase F 单元：workspace 18 / duplicate 20 / intake 25 = 63 项
- 真实 Windows E2E（tests/test_phase_f_e2e.py，9 项）：
  A. 当前 workspace TASK → 无额外确认 → 真实 launcher + 真实 run.py dry-run
     子进程执行 → REPORT.md / route.json / context_manifest.json 产物 + registry
     EXITED + config 未变
  B. 已知 workspace 切换 → confirm_switch → 确认后切换（config 持久化 +
     recent_projects 置顶）+ TASK.md 落在目标 workspace + 执行完成
  C. 拒绝切换（不调用 apply）→ 零文件写入、current workspace 不变
  D. 陌生 workspace → confirm_unknown；确认前不执行不写入；确认后切换并执行
  E. invalid workspace → reject fail closed（不写任何文件，launcher 保持 IDLE）
  F. RUNNING 任务 → 拒绝项目切换（running_blocked）+ 同 workspace 第二任务
     launcher 抛 AlreadyRunningError（无第二 runner；registry 唯一活跃 launch）
  G. duplicate RUNNING → reject + 卡片（kind=running）+ 无第二 registry 条目
  H. duplicate terminal（canonical SUCCESS + REPORT）→ reject + 卡片
     （kind=completed，需新 Task ID）+ artifacts 逐文件 hash 前后一致（未覆盖）
  I. Bridge restart（新 launcher 实例 + recover_launches）→ current project 从
     config 正确恢复 + 同 Task ID 仍被 duplicate running 拒绝 + 新 Task ID 正常
- 验证命令：见本报告「复现」节

## 范围边界（req 16 遵守）
未实现：autostart / parser compatibility / orphan/dead runner recovery / final
status aggregation fix / hotkey self-heal / completion notification continuity /
Context Compaction redesign / 大型项目 manager/dashboard。
Authority 边界（req 12）：UI/Bridge confirmation 只决定是否允许切换与启动；
未改写 TASK execution snapshot / Task ID / Workspace / canonical terminal /
历史 artifacts；未杀掉任何当前任务。

## 问题与说明
- 无未解决 blocker。
- 说明 1：设计 §9.2.3「从最近项目选择」下拉为可选增强（设计原文「可选，若实现
  成本低；否则仅确认窗」），第一版按设计降级为仅确认窗，不构成缺口。
- 说明 2：§10.3 Resume 按钮按设计原文「第一版可只显示提示该任务需重新提交」处理；
  既有 `--resume-from` CLI 保留不动。
- 说明 3：E2E 的「正常执行」支线使用真实 runner 的 dry-run（框架既有语义），
  Agent 链不调用——与 Phase E E2E 同款确定性约束（Agent 调用本身不在 Phase F 范围）。

## 复现
```
python -m pytest tests/test_phase_f_workspace.py tests/test_phase_f_duplicate.py tests/test_phase_f_intake.py tests/test_phase_f_e2e.py -q
python -m pytest tests/ -q          # 全量 760 passed
```

## 交接（WorkBuddy / Codex 验证入口）
- 设计权威：docs/design/AAF-DESKTOP-SHELL-MINIMAL-DESIGN.md §9 / §10 / §11 / Phase F
- 实现：bridge/workspace.py、bridge/duplicate.py、bridge/intake.py、bridge/config.py、
  bridge/ui.py、bridge/main.py
- 测试：tests/test_phase_f_workspace.py、test_phase_f_duplicate.py、
  test_phase_f_intake.py、test_phase_f_e2e.py、tests/fixtures/run_dry.py
- 状态：docs/internal/PROJECT_STATE.md（Phase F 段）、docs/internal/AAF_MASTER_BACKLOG.md
  （RW-003 / RW-016 / RW-006 / RW-009 / RW-014）
