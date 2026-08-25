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
