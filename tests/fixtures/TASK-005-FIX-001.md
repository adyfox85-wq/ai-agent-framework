# TASK-005-FIX-001

## Task ID

TASK-005-FIX-001

## Task Name

补齐示例业务 H5 我的详情页面实现

## Objective

补齐 TASK-005 中实际未执行的前端实现，使“我的详情”页面达到原 TASK-005 的验收要求。

本任务不是重新设计 TASK-005，也不是进入 TASK-006。

只针对最新 REPORT 中 WorkBuddy FAIL 与 Codex REQUEST_CHANGE 明确指出的缺失项进行实现。

---

## Background / Current State

项目：

example-business-project

当前阶段：

示例业务 H5 MVP 页面开发阶段。

已完成：

- TASK-001：frontend 工程恢复；
- TASK-002：首页 Home 完成；
- TASK-003：关系页 Relation 完成；
- TASK-004：用户建档流程完成；
- TASK-004-FIX-001：出生信息数据契约修正完成，最终 SUCCESS。

TASK-005 原目标：

实现“我的详情”第一阶段页面。

最新 REPORT 结论：

- Current Status：SUCCESS（Framework 路由完成）
- WorkBuddy：FAIL
- Codex：REQUEST_CHANGE

原因：

TASK-005 实际实现阶段被跳过，当前 `ExampleDetailPage.tsx` 仍是 TASK-004 占位页。

已确认当前仍存在：

- `/profile-detail` 路由；
- 已建档基本资料回显；
- `birthTimeUnknown=true` → “时间不详”；
- 未建档兜底。

但 TASK-005 新要求尚未实现。

---

## Requirements

### 1. 完整实现顶部个人区域

在现有资料回显基础上补齐：

- 展示盘视觉；
- 昵称；
- 性别；
- 建档状态；
- 出生日期；
- 出生时间或“时间不详”；
- 出生城市。

必须继续兼容：

```ts
birthTime: string | null
birthTimeUnknown: boolean
```

不得破坏 TASK-004-FIX-001 已批准的数据契约。

---

### 2. 固定排盘基础信息区

新增集中 Mock 数据，并在页面结构化展示：

- 结构摘要；
- 元素摘要；
- 基础摘要一；
- 基础摘要二。

要求：

- 数据必须集中在 `src/data/mock.ts` 或现有集中 Mock 层；
- 页面不得散落硬编码数据；
- 不生成真实排盘；
- 不新增真实排盘算法；
- 不绑定未冻结的完整后端报告 JSON。

必须删除或替换当前占位文案：

> 排算与解读将在后续任务实现，当前为占位。

TASK-005 完成后，该占位不能继续存在。

---

### 3. 动态趋势区

实现四档趋势：

- 今日；
- 本周；
- 本月；
- 今年。

要求：

- 使用集中 Mock；
- 今日 / 本周如适合可复用已有 `MetricCard`；
- 本月 / 今年保持同一视觉体系；
- 不实现真实周期 / 周期 / 周期计算。

---

### 4. “问自己”入口

在详情页增加：

“问自己一件事”

或语义等价入口。

目标路由：

`/divination`

该路由已存在。

只建立跳转，不实现推演页新功能。

---

### 5. “我的历史报告”入口

增加：

“我的历史报告”

目标路由：

`/reports`

该路由已存在。

只建立跳转，不实现报告列表新功能。

---

### 6. 未建档兜底保持有效

如果：

`mockUser.profile === null`

必须：

- 不展示伪造详情；
- 显示尚未建档；
- 提供 `/profile-create` 建档入口。

不能因本次页面补齐破坏现有兜底。

---

### 7. 更新项目状态

更新：

`frontend/PROJECT_STATE.md`

将：

`/profile-detail`

从 TASK-005 占位状态更新为：

TASK-005 第一阶段已实现。

不要把真实排算标记为完成。

---

## Scope / 禁止事项

### 允许修改

仅限：

`frontend/`

建议允许：

- `src/pages/ExampleDetailPage.tsx`
- `src/data/mock.ts`
- 已有通用组件
- 必要的新详情展示组件
- 相关样式
- `frontend/PROJECT_STATE.md`

如确有必要可新增：

- `src/components/` 下详情专用展示组件

---

### 禁止事项

禁止：

- 重做 TASK-004 建档流程；
- 修改出生时间数据契约；
- 重开 TASK-003 关系页；
- 实现 TASK-006 推演页；
- 实现完整报告列表；
- 实现真实排算；
- 实现真实排算；
- 实现真实元素算法；
- 实现真实周期 / 周期 / 周期算法；
- 接真实 API；
- 接数据库；
- 接登录；
- 接支付。

禁止修改：

- `workbuddy_skills/`
- `upstream_export/`
- Phase 10.6 后端；
- 核心逻辑；
- WorkBuddy 正式 skills。

---

## Files / Resources

执行前必须读取：

1. `frontend/PROJECT_STATE.md`
2. TASK-005 原始任务
3. TASK-005 最新 REPORT
4. `frontend/src/pages/ExampleDetailPage.tsx`
5. `frontend/src/pages/HomePage.tsx`
6. `frontend/src/components/MetricCard.tsx`
7. `frontend/src/data/mock.ts`
8. `docs/2026-08-22-demo-h5-home-frontend-handoff.md`
9. `docs/2026-08-22-h5-web-bridge-context.md`
10. `docs/2026-08-22-core-h5-api-contract.md`

以仓库当前代码和最新 REPORT 为最高优先级。

---

## Acceptance Criteria

### 功能

必须满足：

- `/profile-detail` 正常访问；
- 已建档状态显示完整顶部个人区域；
- `birthTimeUnknown=true` 明确显示“时间不详”；
- 有展示盘视觉；
- 有建档状态；
- 结构摘要结构化展示；
- 元素摘要展示；
- 基础摘要一展示；
- 基础摘要二展示；
- 今日趋势展示；
- 本周趋势展示；
- 本月趋势展示；
- 今年趋势展示；
- “问自己一件事”可点击并进入 `/divination`；
- “我的历史报告”可点击并进入 `/reports`；
- 未建档状态仍正确兜底；
- TASK-005 旧占位文案已删除。

### Mock / 数据

必须满足：

- 详情 Mock 集中管理；
- 页面不散落固定排盘数据；
- 不新增真实算法；
- 不绑定未冻结完整报告 JSON。

### 技术

必须满足：

- `npx tsc --noEmit` 通过；
- `npm run build` 通过；
- 无明显控制台错误。

### Browser Smoke

如执行环境具备浏览器能力，必须验证 375px：

已建档：

- 页面无横向溢出；
- 顶部个人区域正常；
- 固定排盘区正常；
- 四档趋势正常；
- 两个入口可点击。

未建档：

- 正确显示兜底；
- 可进入建档。

### 项目状态

必须：

- 更新 `frontend/PROJECT_STATE.md`；
- 不再将 `/profile-detail` 标记为 TASK-005 占位。

### 范围

确认：

- 未修改 skills；
- 未修改后端；
- 未实现真实排盘算法；
- 未进入 TASK-006；
- 未重开 TASK-003 / TASK-004。

---

## Route Hint

建议类型：

frontend implementation recovery / missing implementation fix

建议执行链：

- Hermes：必须执行实际实现
- WorkBuddy：独立复核
- Codex：复审原 REQUEST_CHANGE 是否关闭

Router 必须确保：

本轮不能跳过 Executor 实现阶段。

---

## Planner Notes

1. 本轮失败的核心不是实现质量，而是 TASK-005 **根本没有被执行**。

2. WorkBuddy 已确认当前基线 TypeScript 健康，问题纯粹是 TASK-005 缺失。

3. Codex 与 WorkBuddy 一致确认以下为阻断缺失：
   - 固定排盘结构化 Mock；
   - 结构摘要；
   - 元素摘要；
   - 基础摘要一；
   - 基础摘要二；
   - 今日 / 本周 / 本月 / 今年趋势；
   - 展示盘视觉；
   - 建档状态；
   - “问自己”入口；
   - “历史报告”入口；
   - PROJECT_STATE 更新。

4. `/divination` 与 `/reports` 已存在，不需要新建复杂路由。

5. 工作树仍混有旧 TASK 的未提交改动。执行报告必须精确列出本轮实际修改文件，不得把历史改动错误归入 TASK-005-FIX-001。

6. 本任务完成且最终审查通过后，才允许规划 TASK-006。

---

## Next Task

TASK-006

示例业务 H5 推演页第一阶段实现。

仅在 TASK-005-FIX-001 最终 REPORT 通过后进入。
