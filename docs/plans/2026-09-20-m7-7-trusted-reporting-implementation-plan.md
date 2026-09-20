# M7.7 可信报告编排与导出实施计划

- 设计规格：`docs/superpowers/specs/2026-09-20-m7-7-trusted-reporting-design.md`
- 实施方式：按可独立验收的纵向切片连续交付，每个切片通过测试后单独提交并推送
- 安全边界：只引用已验证 Artifact、Evidence 和 Validation，不重新查询或计算业务结果

## 0. 前置收尾：图表渲染修复

- 完成 `AnalysisChart` 的 ECharts Dataset 注册和安全 Option 测试；
- 将原始字段名映射为中文业务标签；
- 运行前端类型、单测和构建；
- 独立提交，不包含用户已有文档改动。

## 1. M7.7-A1：领域模型与迁移

- 在 `packages/agent_core` 增加 `AnalysisReport` 和 `AnalysisReportFile`；
- 增加报告状态、格式、唯一约束和工作空间索引；
- 新增 Alembic 正向与回滚迁移；
- 增加状态机、模型约束和迁移测试。

验收：模型可创建、状态约束有效、迁移可升级和回滚、跨工作空间查询必须显式隔离。

## 2. M7.7-A2：ReportSpec 与可信 Composer

- 在 `packages/shared_contracts` 定义严格 ReportSpec v1 和 API 契约；
- 在 `packages/reporting` 实现来源校验、规范化、摘要、Markdown 和安全 HTML；
- 只接受已完成 Run、通过 Validation 且存在 Evidence 的白名单 Artifact；
- 对所有用户文本和来源文本进行 HTML 转义；
- 增加确定性快照、注入攻击和跨工作空间测试。

验收：相同输入产生相同摘要，未验证来源被稳定错误码拒绝，HTML 不含脚本和外部资源。

## 3. M7.7-A3：创建、列表和详情 API

- 新增报告服务和工作空间级路由；
- 实现创建幂等键、权限矩阵、分页列表和详情投影；
- 创建事务同时写入 Outbox 与审计；
- 在 API 主应用注册路由；
- 增加权限、幂等、隔离和错误契约测试。

验收：Analyst 可创建，Viewer 仅可读取，跨工作空间访问全部拒绝，重复创建不产生重复任务。

## 4. M7.7-B1：异步生成与对象存储

- 新增 Celery 报告任务和条件状态转换；
- 生成 Markdown、HTML、PDF，并计算 SHA-256；
- 使用 MinIO 私有对象键保存三种文件；
- 增加失败分类、两次自动重试、人工重试和临时对象清理；
- Worker 镜像固定 WeasyPrint 与 Noto Sans CJK 依赖。

验收：生成成功与失败均可恢复，重复消费幂等，PDF 中文完整，渲染过程无网络和数据库凭证。

## 5. M7.7-B2：预览、下载与审计

- 新增受控 HTML 预览接口；
- 新增 Markdown、HTML、PDF 流式下载；
- 下载时重新校验成员关系和来源权限；
- 使用安全中文文件名和 RFC 5987 编码；
- 记录预览、下载、拒绝和重试审计事件。

验收：不返回 MinIO 内部地址，权限撤销后无法预览或下载，摘要与下载内容一致。

## 6. M7.7-C：前端报告体验

- 增加报告 TypeScript 契约和 Query hooks；
- 在可信会话中增加“生成报告”入口和轮次选择；
- 增加报告状态卡、失败重试、在线预览和三种格式下载；
- 增加 Evidence 回链与自然语言错误；
- 完成桌面、390px、键盘和 `aria-live` 验收。

验收：前端不模拟成功状态，不可用来源明确说明原因，同一会话可继续追问。

## 7. M7.7-D：总体验收与交付

- 完成 Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest 和 Playwright；
- 完成迁移往返、Compose 健康、MinIO、Worker 和真实中文 PDF 验收；
- 更新能力清单、README、项目状态、项目日志和验收记录；
- 将 M7 标记为完成并明确进入 M8；
- 每个通过的切片独立提交并推送 GitHub。

## 8. 不纳入本计划

- 任意 HTML/CSS/脚本模板；
- 模型补写事实或重新计算业务数值；
- 公共分享链接、在线协作、审批和电子签章；
- 开放式 Python 沙箱与机器学习训练；
- 独立报告微服务。
