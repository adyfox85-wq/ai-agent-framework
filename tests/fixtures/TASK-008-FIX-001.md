# TASK-008-FIX-001

## Task ID

TASK-008-FIX-001

## Task Name

修复 ExampleDetailPage 条件 Hook 调用并补充合法 / 无效报告 ID 导航验证

## Objective

修复 TASK-008 中 Codex 指出的唯一阻塞性 React Hooks 逻辑问题：

`ExampleDetailPage` 在报告不存在时提前 return，导致 `useReportFavorite()` 仅在合法报告 ID 分支中调用，违反 React Hooks 固定调用顺序规则。

本任务只修复该问题，并增加：

- 合法报告 ID → 无效报告 ID；
- 无效报告 ID → 合法报告 ID；

同一参数化路由下的导航验证。

不要进入 TASK-009，不重新打开 TASK-008 已完成范围。

---

## Background / Current State

项目：

example-business-project

当前阶段：

示例业务 H5 MVP 页面开发阶段。

TASK-008 当前 Agent 结论：

- Hermes：已实现报告模块第一阶段；
- WorkBuddy：PASS_WITH_WARNING；
- Codex：REQUEST_CHANGE；
- 当前状态：WAITING。

Codex 唯一阻塞问题：

`ExampleDetailPage` 存在条件调用 Hook。

证据：

- 报告不存在时提前 return；
- `useReportFavorite()` 位于该 return 之后；
- `/reports/:id` 为同一参数化路由；
- 合法 ID 与无效 ID 之间导航时，组件可能被复用；
- 从而导致不同 render 的 Hook 数量不一致。

典型风险路径：

```text
/reports/rep-mine-trend
→ /reports/not-found
```

可能触发 React Hooks 顺序错误，例如：

```text
Rendered fewer hooks than expected
```

---

## Requirements

### 1. 固定 Hook 调用顺序

修改：

`frontend/src/pages/ExampleDetailPage.tsx`

要求：

- 所有 Hook 必须在每次 render 中无条件调用；
- Hook 顺序必须固定；
- 不允许因为 `report` 是否存在而改变 Hook 数量；
- 不允许在 Hook 之前基于 `report` 做提前 return。

允许实现方式：

- 先完成所有 Hook 调用；
- Hook 内部处理 report 不存在的安全值；
- 再进入 not-found / valid-report 分支渲染。

不要做大规模重构。

---

### 2. `useReportFavorite` 安全调用

当前：

`useReportFavorite(report.id)`

需要调整为即使 report 不存在也可安全调用的方式。

可以：

- 传入稳定 fallback id；
- 或让 hook 支持 `undefined / null`；
- 或采用其他最小且类型安全的方案。

要求：

- 不改变数据业务语义；
- 合法报告数据逻辑保持原样；
- 无效报告不能误操作任意真实报告数据状态。

---

### 3. 合法 ID → 无效 ID 导航验证

新增或扩展现有 smoke / navigation 验证。

至少验证：

1. 打开合法报告：
   `/reports/<valid-id>`

2. 在同一 SPA 会话内导航到：
   `/reports/not-found`

3. 确认：

- 页面不崩溃；
- 无 React Hooks 顺序错误；
- 正确显示无效报告 / 不存在报告兜底；
- 底部“报告”导航仍正常。

---

### 4. 无效 ID → 合法 ID 导航验证

继续同一 SPA 会话：

1. 从：
   `/reports/not-found`

2. 导航回：
   `/reports/<valid-id>`

3. 确认：

- 页面正常恢复；
- 详情内容正常显示；
- 数据状态功能正常；
- 无 React Hooks 顺序错误；
- 无 console error。

---

## Scope / 禁止事项

### 允许修改

优先仅限：

- `frontend/src/pages/ExampleDetailPage.tsx`
- `frontend/src/hooks/useExampleData.ts`（仅在必要时）
- TASK-008 现有报告 smoke / navigation 测试文件
- `frontend/PROJECT_STATE.md`（仅在确有必要记录修复时）

### 禁止事项

禁止：

- 修改报告数据结构；
- 修改报告列表；
- 修改筛选逻辑；
- 修改分享隐私逻辑；
- 修改数据产品语义；
- 重做 TASK-008 UI；
- 接真实 API；
- 接数据库；
- 实现真实报告生成；
- 进入 TASK-009；
- 顺手修复其它非阻断 warning。

禁止修改：

- `workbuddy_skills/`
- `upstream_export/`
- core 后端；
- Phase 10.6 核心逻辑。

---

## Files / Resources

执行前必须读取：

1. TASK-008 最新 REPORT
2. `frontend/src/pages/ExampleDetailPage.tsx`
3. `frontend/src/hooks/useExampleData.ts`
4. `frontend/src/data/reports.ts`
5. `frontend/src/App.tsx`
6. TASK-008 现有 report smoke / navigation 测试

以 Codex REQUEST_CHANGE 为唯一修复依据。

---

## Acceptance Criteria

### React Hooks

必须满足：

- `ExampleDetailPage` 所有 Hook 每次 render 无条件调用；
- 合法 / 无效报告分支不改变 Hook 数量；
- 不存在条件调用 Hook；
- 不存在 Hook 前提前 return 导致顺序变化。

### 合法 ID → 无效 ID

必须满足：

- 同一 SPA 会话中可从合法报告详情导航到无效 ID；
- 不出现 React Hooks 报错；
- 正确显示 not-found 兜底。

### 无效 ID → 合法 ID

必须满足：

- 同一 SPA 会话中可从无效 ID 回到合法报告；
- 页面恢复正常；
- 数据功能仍可使用；
- 不出现 React Hooks 报错。

### 技术

必须满足：

- `npx tsc --noEmit` 通过；
- `npm run build` 通过；
- 如环境具备浏览器能力：
  - 合法 ↔ 无效 ID 往返 smoke 通过；
  - console error = 0。

### 范围

必须确认：

- 未重新打开 TASK-008 已完成范围；
- 未修改报告主体数据模型；
- 未修改分享逻辑；
- 未进入 TASK-009；
- 未修改后端 / skills。

---

## Route Hint

建议类型：

frontend bugfix / React Hooks correctness

建议执行链：

- Hermes：最小修复
- WorkBuddy：独立复核
- Codex：复审原 REQUEST_CHANGE 是否关闭

---

## Planner Notes

1. 本任务只处理 Codex 唯一阻塞项：

`ExampleDetailPage` 条件调用 Hook。

2. WorkBuddy 的其它 warning 均为非阻断，不在本任务范围：

- 浏览器 smoke 未独立复跑；
- 跨 TASK 工作树混杂；
- 详情页展示昵称属于产品认知提示。

3. Codex 的其它非阻断风险也不要在本任务修：

- 分享构建未来需要更严格隐私安全字段；
- 跨 TASK 工作树未整理；
- docs/tasks 验收产物范围问题。

4. 本任务验收的关键不是“页面能打开”，而是验证：

```text
valid id
→ invalid id
→ valid id
```

在同一参数化路由组件复用过程中 Hook 顺序始终稳定。

5. 修复完成并经 Codex APPROVE 后，TASK-008 才可正式关闭。

---

## Next Task

不得自动进入 TASK-009。

只有 TASK-008-FIX-001 最终审查通过后，由 Planner 再决定 TASK-009。
