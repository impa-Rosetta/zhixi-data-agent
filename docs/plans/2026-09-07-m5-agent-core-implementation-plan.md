# M5 Agent 核心闭环实施计划

- 状态：执行中
- 日期：2026-09-07
- 规格：`docs/superpowers/specs/2026-09-07-m5-agent-core-design.md`

## 执行规则

每个切片按测试先行、实现、静态检查、回归、真实链路、文档和精确提交执行。默认测试使用 Fake Gateway；真实 DeepSeek 验收必须显式开启预算。用户已有未提交文件不纳入任何提交。

## 切片一：模型网关与严格契约

- 定义供应商无关消息、工具、结构化响应、流式事件、用量和错误契约；
- 实现 DeepSeek OpenAI-compatible 适配器、超时、重试、错误映射及秘密安全；
- 实现可复现 Fake Gateway；
- 增加配置校验和协议测试。

## 切片二：运行状态与迁移

- 建立 AnalysisRun、Message、Plan、Step、ToolCall、Artifact、Evidence、Validation、Checkpoint 和 Event；
- 实现工作空间隔离、乐观锁、单调事件、幂等键、预算和生命周期约束；
- 完成 Alembic 升降级与模型测试。

## 切片三：意图、语义绑定、Planner 与 Registry

- 定义严格 Intent、Binding、AnalysisPlan 和 ContextPatch；
- 绑定已发布语义版本和可信指标，低置信度暂停澄清；
- Planner 拒绝自由代码、任意 SQL、未注册工具和指标公式；
- 注册十二类工具并接通目录、语义、可信查询、受控探索和确认能力。

## 切片四：执行图、Worker 与 API

- 实现 understand、bind、plan、policy、clarify/confirm、execute、verify、replan、present 状态图；
- 节点边界保存检查点，Outbox 幂等投递 Worker；
- 提供创建、读取、追加消息、确认、取消、重试和事件读取 API；
- 增加权限、错误和重复投递测试。

## 切片五：恢复、多轮与整体验收

- 实现结构化上下文补丁和多轮继承；
- 验证服务/Worker 中断恢复、取消、预算耗尽和模型故障保留产物；
- 运行 PostgreSQL/MySQL 真实工具闭环与可选真实 DeepSeek 验收；
- 更新 ADR、项目状态、项目日志、README、验收证据和 Compose；
- 运行全量质量门禁并推送 GitHub。

## M5 完成定义

五个切片全部通过，自动化和真实链路结果一致，运行状态可恢复，重复请求无重复关键副作用，低置信度进入澄清，模型不能修改可信指标或绕过 M4，Compose 服务健康，文档与远端提交一致。
