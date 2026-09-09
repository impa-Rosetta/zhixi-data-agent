# M6-C 三栏问析工作台验收

- 验收日期：2026-09-09
- 阶段：M6-C
- 上游：M6-A 运行投影、M6-B 可重放 SSE
- 代码提交：`418108d`

## 交付范围

正式 `/app` 分析入口已经替换占位页面。桌面端由分析任务、对话运行、执行与证据三栏组成；窄屏端通过任务、问析、执行三个可触控分区保持完整能力。运行 URL 固化为 `/app/analysis/:runId`，刷新或重新打开链接会恢复同一后端运行。

工作台接入以下真实命令：

- 创建 AnalysisRun；
- 提交多轮澄清；
- 批准或拒绝确认门计划；
- 取消排队中或执行中的任务；
- 从可恢复失败检查点重试。

界面仅渲染 M5/M6 服务端投影和持久化事件。没有配置模型时，后端以 `failed_retryable/model.not_configured` 明确失败，前端不会合成回答或伪造成功结果。

## 实时状态与权限

- Bearer Fetch SSE 与 React Query 权威投影合并，事件按序去重；
- 序号空洞或关键事件触发服务端投影刷新，短时断线保留现有状态；
- 切换运行时事件、连接状态与错误按 `runId` 隔离，避免旧任务状态串入新任务；
- 审计员不获得分析执行控件；
- 技术详情不展示检查点内部状态、受限推理或凭据。

## 自动化证据

- Ruff：通过；
- 严格 MyPy：101 个源文件通过；
- Pytest：195 项通过；
- Vitest：15 个文件、39 项通过，其中 M6-C 页面 6 条主流程通过；
- TypeScript、ESLint：通过；
- Vite 生产构建：通过。

## 真实部署与浏览器验收

- `zhixi-data-agent-web` 镜像从 Git 提交源码构建并部署；
- Web、API、Worker、Scheduler、PostgreSQL、MySQL、Redis 与 MinIO 恢复运行，Web/API 健康检查通过；
- Playwright 使用本机 Chrome 对桌面 1440×1000 和移动 390×844 各执行一次真实登录、创建运行、URL 恢复、执行详情和无横向溢出验收，2 项全部通过；
- 浏览器运行创建真实数据库记录，未拦截 API 或注入静态答案。

## Docker 稳定性记录

本次 Windows 重启后先后发现 `dockerInference` 与 `userAnalyticsOtlpHttp.sock` 两个陈旧 Docker Desktop 瞬态套接字。精确清理后引擎恢复，镜像、容器卷和数据库未删除。`scripts/docker-preflight.ps1` 已覆盖两种已知根因，后续仍坚持先只读预检、显式恢复、禁止 factory reset。

## 结论

M6-C 完成。用户已可通过正式 Web 工作台控制真实 Agent 运行全生命周期，并在桌面或移动布局观察可恢复执行状态。M6-D 将补齐真实结果、Evidence 定位、可信等级和 M6 整体验收。
