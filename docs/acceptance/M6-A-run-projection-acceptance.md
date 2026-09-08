# M6-A 运行列表与完整投影验收

- 日期：2026-09-08
- 状态：通过
- 设计：docs/superpowers/specs/2026-09-08-m6-analysis-workbench-design.md
- 实施计划：docs/plans/2026-09-08-m6-analysis-workbench-implementation-plan.md
- 产品提交：c7cfba2

## 交付范围

- 新增按更新时间排序、支持 limit/offset 的工作空间 AnalysisRun 分页列表；
- 新增 /analysis-runs/{run_id}/view 服务端完整恢复投影；
- 投影覆盖运行、消息、最新计划、步骤、工具调用、产物、证据、验证和最后事件序号；
- 响应显式排除幂等键、内部事件游标、对象存储键和受限检查点推理；
- 新增前端稳定 TypeScript 类型、React Query 键和列表/投影访问层；
- 所有新增读取复用 Action.ANALYSIS_RUN，并由工作空间授权边界保护。

## 自动化证据

- Ruff：通过；
- 严格 MyPy：83 个源文件通过；
- Pytest：192 项通过，其中 M6-A 接口与真实 Agent 投影测试 7 项通过；
- ESLint：通过；
- TypeScript：应用与 E2E 类型检查通过；
- Vitest：12 个测试文件、25 项测试通过；
- 前端生产构建：Vite 生产包构建成功，npm 审计 0 个已知漏洞。

## 真实运行证据

- 从 Git 提交构建 API 与 Web 镜像成功；
- API 与 Web 容器重建后均为 healthy；
- 使用本地演示会话调用真实 HTTP 接口：
  - 任务列表 total=1、returned=1，分页参数与响应一致；
  - 完整投影恢复 messages=1、last_event_sequence=3；
  - 当前任务状态为 failed_retryable，原因是部署环境未配置模型密钥，未产生虚假结果；
- 本切片不修改数据库结构，因此无需新增迁移；
- 中文路径归档问题通过最小 Git 构建上下文规避，临时目录和归档已在验收后删除。

## 验收结论

M6-A 完成。服务端已提供稳定、隔离且不泄露内部推理的工作台读取模型，前端具备后续 SSE 和 UI 所需的明确契约。下一切片进入 M6-B 可重放 SSE 与客户端恢复。
