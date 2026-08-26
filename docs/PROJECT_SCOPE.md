# Project Scope — AI Agent Framework

## 项目定位

AI Agent Framework 是个人 AI 工作基础设施，用于沉淀：

- Agent 角色协议
- TASK 任务机制
- 工作流
- 路由规则
- 汇报机制
- 验收机制

服务未来所有 AI 项目，不属于具体业务项目。

## 范围内（v0.1）

- 建立基础目录结构（docs / protocols / templates / examples）
- 项目说明（README）与范围说明（本文档）

## 不在范围内（v0.1）

- 协议迁移（不进行旧项目协议迁移）
- 复制 <BUSINESS_PROJECT> 文件
- 修改 Hermes 配置
- 修改 WorkBuddy 配置
- 修改账号 / token
- 创建自动化程序
- 创建 launcher
- 创建消息总线

## 目录职责

| 路径 | 用途 |
|------|------|
| `docs/` | 项目文档：范围、决策记录、体系说明 |
| `protocols/` | 协议区：Agent 角色协议、TASK 任务机制、工作流、路由规则、验收机制、汇报规范 |
| `templates/` | 模板区：可直接复用的任务 / 汇报 / 验收模板 |
| `examples/` | 示例区：示例任务、示例报告，帮助理解协议用法 |

## 版本

v0.1 —— 项目初始化，仅建立骨架，不写协议内容。

---

## Core Goal

沉淀个人 AI 工作基础设施：Agent 角色协议、TASK 任务机制、工作流、路由规则、汇报机制、验收机制，服务未来所有 AI 项目（不属于具体业务项目）。

## Current Scope

- v0.3 正式组件：Bridge Intake（Planner → TASK.md）、Formal Task Validation、Task Lifecycle（CREATED/RUNNING/WAITING/SUCCESS/FAILED）、Task Artifact Archive、Session Continuity、Project Boundary Control
- 自动执行链：TASK → Validation → Boundary Check → Router → Runner → Agents → REPORT → Planner Handoff
- 工作目录：D:\AdyAI\ai-agent-framework（代码）与 D:\AdyAI\Obsidian-Vault（知识）

## Frozen Boundaries

- 不进行旧项目协议迁移
- 不复制 <BUSINESS_PROJECT> 文件
- 不修改 Hermes 配置 / WorkBuddy 配置 / 账号 / token
- 不自动创建下一 TASK / 不自动归档 / 不自动修改 Scope
- 不引入数据库 / SQLite / 向量库 / 无限记忆
- 不自动创建 ChatGPT 新会话 / 不跨项目迁移
- 不改写历史（禁止 force push / reset / rebase / amend / clean）
- 不删除 docs/internal 历史材料与 .aaf-backup 备份

## Approved Extensions

- v0.3 已批准扩展：Bridge Copy Last Report（000-C）、Formal Validation（001）、Lifecycle（002）、Archive（003）、Session Continuity（004）、Boundary Control（005）

## Backlog / Future Ideas

- Task Registry（全局任务索引）
- DECISION_LOG（决策记录）
- Bridge Copy Next Session Start
- 自动上下文长度检测提示
- 跨 Agent 交接包模板增强

## Last Updated

2026-08-26（AAF-V03-005 EXTEND）
