# M5 Agent 核心闭环整体验收

- 验收日期：2026-09-08
- 规格：docs/superpowers/specs/2026-09-07-m5-agent-core-design.md
- 实施计划：docs/plans/2026-09-07-m5-agent-core-implementation-plan.md
- 代码提交：c89df78、01fad35、b57baac、db65524、e99c9de

## 验收结论

M5 通过。Model Gateway、持久化运行状态、意图与发布语义绑定、声明式 Planner、十二项 Tool Registry、LangGraph 执行拓扑、Plan-Execute-Verify 运行时、多轮澄清、显式确认、取消、重试、检查点恢复、Outbox 和 Worker 已形成真实后端闭环。

M5 不包含正式对话页面和 SSE，这两项按规格属于 M6。没有配置模型部署 Secret 时，系统明确进入 failed_retryable/model.not_configured，不生成模拟答案。

## 自动化门禁

- Ruff：全仓通过；
- 严格 MyPy：100 个源码文件通过；
- Pytest：189 项全部通过；
- Model Gateway 覆盖官方 Chat Completions 请求、JSON Schema 二次校验、思考模式字段、流式事件、用量、鉴权错误和秘密不进入错误文本；
- Agent 覆盖声明式计划约束、低置信度澄清、语义别名绑定、幂等恢复、结果与 Evidence 固化；
- Outbox 覆盖 Data Source 的 job_id 与 AnalysisRun 的 run_id 参数路由。

## 数据库与部署验收

- 在一次性 PostgreSQL 数据库 zhixi_m5_migration_20260907_2348 完成全量升级、M5 降级到 20260907_0008、再升级到 20260907_0009；确认成功后已删除临时库；
- 现有平台库升级至 20260907_0009；
- information_schema 确认 10 张 analysis_* 表；
- API、PostgreSQL、Redis、MinIO、Worker、Web、双样例数据库均健康；
- Worker 注册 analysis_runs.execute；
- Celery Beat 使用 /tmp/celerybeat-schedule 和 /tmp/celerybeat.pid，以非 root 用户持续运行。

## 真实异步链路

运行 8b43e774-1f6f-4ab8-9d29-c3494d4f65b1 通过本地 HTTP API 创建。修复 Scheduler 状态文件权限和 Outbox 参数键后，链路按以下顺序完成：

API 创建 AnalysisRun 与事务 Outbox → Beat 触发 outbox.dispatch → Worker 收到 analysis_runs.execute → 运行时检查模型配置 → 保存检查点和事件 → 进入 failed_retryable。

最终 error_code 为 model.not_configured，model_calls 为 0；证明未配置密钥时不会发出模型请求、伪造答案或丢失可恢复状态。

## 安全结论

- DeepSeek Key 只从 DEEPSEEK_API_KEY 或部署 Secret 读取；
- 模型业务层不依赖供应商 SDK；
- 模型计划禁止 SQL、Python、Shell、代码、凭据和指标公式；
- 查询工具必须通过 Tool Registry，再复用 M4 的编译、AST 校验和验证 ID 执行；
- 运行冻结语义版本、目录快照和工具版本；
- 权限、安全和预算失败不可由模型重试绕过；
- 用户已有 docs/acceptance/M3-postgresql-catalog-acceptance.md 修改未纳入 M5 提交。

## 可选真实模型验收

当前本机 .env 未配置 DEEPSEEK_API_KEY，因此未进行付费真实模型调用。该项按 M5 规格为显式开启的可选验收，不影响可复现 Fake Gateway、真实数据库和真实异步基础设施验收。配置部署 Secret 后可对失败运行执行 retry，系统会从最近状态继续。
