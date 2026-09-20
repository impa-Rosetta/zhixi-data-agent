# M7.7 可信报告编排与导出设计规格

- 日期：2026-09-20
- 阶段：M7.7
- 状态：待实施
- 上游依赖：M7.1–M7.6 会话、Artifact、Evidence、Validation、ChartSpec
- 目标：从已验证分析产物生成可追溯的 Markdown、HTML 和 PDF 报告

## 1. 背景与目标

M7.1–M7.6 已形成连续多轮问析、持久化事件、恢复、推荐追问、描述统计和受限图表闭环。M7.7 在不重复查询、不重新计算业务结果、不让模型补写事实的前提下，把用户选择的可信分析产物编排为正式报告。

本阶段交付以下产品能力：

1. 用户在同一工作空间内从会话中选择已验证轮次并创建报告；
2. 服务端冻结报告内容、来源、模板和权限上下文；
3. 异步生成 Markdown、HTML 和 PDF 三种格式；
4. 报告中的结论、表格、图表和指标口径可回链到原始 Evidence；
5. 用户可查看生成状态、预览、下载和重试失败任务；
6. 创建、生成、预览、下载和重试均进入审计日志。

## 2. 核心原则

### 2.1 可信来源

报告只能引用当前工作空间内满足以下条件的 Turn 和 Artifact：

- AnalysisRun 已完成；
- 至少存在一项通过的 AnalysisValidation；
- Artifact 能定位到同一 Run 的 Evidence；
- 当前用户拥有报告创建权限和来源数据访问权限；
- Artifact 类型属于报告模板允许的白名单。

报告编排不得重新执行查询，不得修改已验证数值，不得把未验证的模型文本提升为事实结论。

### 2.2 不可变快照

报告创建时冻结 ReportSpec、模板版本、来源标识、展示内容、内容摘要和权限主体。来源数据后续刷新、语义模型发布新版本或会话继续追加消息，都不会静默改变既有报告。

### 2.3 确定性生成

Markdown 和 HTML 由受控模板确定性生成。PDF 由同一 HTML 和固定中文样式表生成。相同 ReportSpec、模板版本和渲染器版本应得到相同正文摘要。

### 2.4 失败隔离

报告生成失败不修改 Conversation、Turn、Run、Artifact、Evidence 或 Validation。失败记录保留错误类别和可重试状态，已存在的分析结果仍可正常使用。

## 3. 方案选择

采用“模块化单体 API + 现有 Celery Worker + MinIO 对象存储”的服务端报告方案。

- API 负责鉴权、来源校验、ReportSpec 冻结、查询和下载授权；
- Worker 负责 Markdown、HTML、PDF 渲染和对象上传；
- PostgreSQL 保存报告元数据、状态、摘要和对象定位；
- MinIO 保存生成文件，存储桶保持私有；
- Web 端只消费严格契约，不在浏览器重新拼接可信正文。

PDF 渲染采用 WeasyPrint，并在 Worker 镜像中固定版本、安装 Noto Sans CJK 字体及必要系统库。浏览器打印仅作为开发诊断手段，不进入正式导出链路。

本阶段不拆分独立报告微服务。若 M9 压测显示 PDF 渲染影响现有 Worker 吞吐，再通过专用 Celery 队列和独立部署单元进行物理隔离，领域契约保持不变。

## 4. 领域模型

### 4.1 AnalysisReport

新增 `analysis_reports` 表，至少包含：

- `id`：UUID；
- `workspace_id`：工作空间边界；
- `conversation_id`：来源会话；
- `created_by`：创建用户；
- `title`：受长度限制的报告标题；
- `status`：`queued | generating | succeeded | failed | expired`；
- `template_key`：模板标识；
- `template_version`：模板版本；
- `renderer_version`：渲染器版本；
- `report_spec`：冻结后的严格 JSON；
- `source_digest`：规范化来源摘要；
- `content_digest`：成功生成后的正文摘要；
- `error_code`：稳定错误码，不保存秘密和堆栈；
- `attempt_count`：生成尝试次数；
- `expires_at`：文件过期时间，可为空；
- `created_at`、`started_at`、`finished_at`、`updated_at`。

约束：

- 所有查询必须同时带 `workspace_id`；
- 同工作空间内 `idempotency_key` 唯一；
- 状态转换只能由领域服务执行；
- 成功报告的 ReportSpec、摘要和对象键不可修改；
- 删除采用文件过期与元数据保留策略，不物理删除审计依据。

### 4.2 AnalysisReportFile

新增 `analysis_report_files` 表，每个报告最多保存三种格式：

- `report_id`、`workspace_id`；
- `format`：`markdown | html | pdf`；
- `object_key`：MinIO 私有对象键；
- `media_type`；
- `byte_size`；
- `sha256_digest`；
- `created_at`、`expires_at`。

`report_id + format` 唯一。对象键由服务端生成，API 不接受客户端传入的路径。

### 4.3 ReportSpec v1

ReportSpec 是严格、版本化的 Pydantic 契约，包含：

- `schema_version`；
- 报告标题、生成主体和生成时间；
- 工作空间、会话和所选 Turn 标识；
- 模板允许的 Section 列表；
- 每个 Section 引用的 Artifact、Evidence 和 Validation 标识；
- 冻结后的指标名称、单位、时间范围和展示值；
- ChartSpec 或表格数据的安全副本；
- 语义模型版本、目录快照和查询摘要；
- 免责声明与可信等级。

ReportSpec 不包含访问令牌、数据库凭证、原始连接信息、模型提示词、隐藏推理、任意 HTML 或任意脚本。

## 5. 状态机与数据流

### 5.1 创建

1. Web 提交标题、会话标识、所选 Turn 标识和模板键；
2. API 校验 `analysis.report.create` 权限；
3. API 在同一事务中锁定并读取来源，验证工作空间、完成状态、Validation 和 Evidence；
4. Composer 将来源投影为 ReportSpec v1；
5. API 保存 `queued` 报告、Outbox 事件和审计记录；
6. Worker 通过 Outbox/Celery 幂等消费生成任务。

### 5.2 生成

1. Worker 使用条件更新把状态从 `queued` 切换为 `generating`；
2. 依据固定模板生成 Markdown；
3. 由 Markdown 对应的结构化 Section 生成转义后的受控 HTML；
4. 使用固定 CSS 和中文字体把 HTML 渲染为 PDF；
5. 计算三种文件摘要并上传 MinIO 私有存储桶；
6. 在单一数据库事务中写入文件元数据、正文摘要和 `succeeded` 状态；
7. 发布会话事件，使前端无需刷新即可看到完成状态。

### 5.3 失败与重试

- 可重试错误：对象存储短暂故障、渲染器暂时不可用、Worker 中断；
- 不可重试错误：来源不可信、ReportSpec 非法、权限已撤销、模板不存在；
- 自动尝试最多两次，指数退避；
- 用户重试复用同一 ReportSpec，不重新读取业务数据；
- 已上传但未完成数据库提交的对象使用临时前缀，由清理任务回收；
- 错误响应只返回稳定错误码和自然语言说明。

## 6. 报告内容与模板

首个模板 `quality-analysis-v1` 包含：

1. 封面和报告元信息；
2. 核心结论；
3. 指标概览；
4. 趋势、排行或对比图表；
5. 描述统计与异常说明；
6. 数据来源、语义口径和查询验证；
7. Evidence 索引；
8. 可信性声明与使用限制。

模板只渲染 ReportSpec 中存在的 Section。缺少某类产物时省略对应章节，不生成占位结论。

图表优先使用安全 ChartSpec 和已验证数据重新绘制为服务端静态 SVG。若服务端静态绘图尚未通过验收，则第一版 PDF 使用受控表格和趋势摘要，Web 预览继续展示现有 ECharts；不得截取浏览器画面或引入任意脚本执行。

## 7. API 契约

新增工作空间级接口：

- `POST /api/v1/workspaces/{workspace_id}/reports`：创建报告；
- `GET /api/v1/workspaces/{workspace_id}/reports`：分页列表；
- `GET /api/v1/workspaces/{workspace_id}/reports/{report_id}`：报告详情；
- `POST /api/v1/workspaces/{workspace_id}/reports/{report_id}/retry`：重试失败报告；
- `GET /api/v1/workspaces/{workspace_id}/reports/{report_id}/preview`：返回受控 HTML 预览；
- `GET /api/v1/workspaces/{workspace_id}/reports/{report_id}/download?format=pdf`：鉴权后流式下载；
- `GET /api/v1/workspaces/{workspace_id}/reports/{report_id}/evidence`：返回来源定位信息。

创建接口支持 `Idempotency-Key`。详情和列表不返回 MinIO 内部地址。下载文件名由服务端生成并进行 RFC 5987 编码。

## 8. 权限、安全与审计

新增动作：

- `analysis.report.create`；
- `analysis.report.read`；
- `analysis.report.download`；
- `analysis.report.retry`。

规则：

- Viewer 可读取和下载有权访问来源的报告；
- Analyst 可创建和重试自己的工作空间报告；
- Admin/Owner 可管理工作空间内全部报告；
- 下载时重新校验当前成员关系和来源权限；
- 对已撤销数据权限的用户拒绝预览和下载；
- HTML 使用固定模板和转义，禁止脚本、事件属性、外部资源和任意 URL；
- PDF 渲染禁用网络访问，不向渲染进程注入数据库和模型凭证；
- 创建、成功、失败、重试、预览、下载和拒绝均写入审计日志；
- 日志和错误不得记录报告正文、原始数据行或秘密。

## 9. 对象存储与生命周期

对象键格式：

`reports/{workspace_id}/{report_id}/{content_digest}.{extension}`

存储桶保持私有。API 使用服务端凭证读取并流式返回，不把永久签名地址暴露给客户端。

默认保留策略：

- 比赛与本地部署默认不过期；
- `expires_at` 为未来企业策略预留；
- 清理任务仅删除已过期文件，保留报告元数据、摘要和审计记录；
- 对象删除失败可安全重试。

## 10. 前端体验

### 10.1 创建入口

完成且包含可信 Artifact 的会话显示“生成报告”。用户可选择当前会话中的已完成轮次，填写标题并确认模板。未通过验证的轮次不可选择，并给出自然语言原因。

### 10.2 状态与预览

会话内显示报告卡片：

- 排队中：显示等待状态；
- 生成中：显示当前阶段；
- 已完成：显示在线预览和三种格式下载；
- 失败：显示可理解的原因和重试按钮；
- 已过期：保留元信息并提示重新生成。

预览沿用现有产品视觉，但正文由后端受控 HTML 提供。用户可从章节中的证据标记返回原会话、Turn 和 Evidence。

### 10.3 响应式与无障碍

- 桌面端使用正文加报告信息侧栏；
- 390px 宽度下单列展示，无横向溢出；
- 状态、格式和按钮具有文字标签，不只依赖颜色；
- 键盘可完成选择、创建、预览、下载和重试；
- 异步状态通过 `aria-live` 提示。

## 11. 可观测性

M7.7 先记录与现有日志体系兼容的结构化字段：

- `report_id`、`workspace_id`、`conversation_id`；
- `template_key`、`template_version`；
- 状态转换和耗时；
- 各格式字节数与摘要；
- 稳定错误码和重试次数。

M8 再接入 OpenTelemetry、Prometheus 指标和告警。本阶段不得为观测方便记录报告正文或用户数据。

## 12. 测试与验收

### 12.1 单元测试

- ReportSpec 严格校验和规范化摘要；
- 来源白名单、验证状态和工作空间隔离；
- 状态机合法与非法转换；
- Markdown/HTML 转义和确定性输出；
- 文件名、对象键和摘要生成；
- 权限矩阵和稳定错误码。

### 12.2 集成测试

- 创建事务、Outbox 投递和幂等键；
- Worker 成功、失败、自动重试和人工重试；
- MinIO 上传、下载、摘要校验和临时对象清理；
- PDF 中文字体、分页、页眉页脚和无外部网络；
- 权限撤销后的预览与下载拒绝；
- 报告来源可回链到 Turn、Artifact、Evidence 和 Validation。

### 12.3 前端测试

- 仅可信会话显示可用入口；
- 选择轮次、创建、轮询或事件更新、预览和下载；
- 失败重试与权限错误自然语言呈现；
- 桌面、390px、键盘与无障碍验收；
- 不使用前端模拟数据或伪造成功状态。

### 12.4 完成门禁

- Markdown、HTML、PDF 三种格式均来自同一 ReportSpec；
- 报告数值与来源 Artifact 完全一致；
- 每个事实章节至少能定位一项 Evidence；
- 跨工作空间读取和下载阻断率 100%；
- PDF 中文字符完整，无乱码、截断和不可读字体；
- 生成失败不改变任何原分析产物；
- Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest、Playwright、迁移往返和 Compose 健康检查通过；
- 验收文档、项目状态、能力清单和部署说明同步更新。

## 13. 实施切片

### M7.7-A：领域与可信编排

- AnalysisReport、AnalysisReportFile、迁移和共享契约；
- 来源选择、权限验证、ReportSpec v1 和内容摘要；
- Markdown/HTML 确定性编排；
- API 创建、列表和详情。

### M7.7-B：异步 PDF 与存储

- Celery 生成任务和状态机；
- WeasyPrint、Noto Sans CJK 和固定样式；
- MinIO 私有文件、下载、重试、过期和审计；
- 失败恢复与幂等验收。

### M7.7-C：产品界面

- 会话内生成入口与可信轮次选择；
- 报告卡片、状态更新、在线预览和下载；
- Evidence 回链、自然错误和移动端适配。

### M7.7-D：总体验收

- 自动化和真实纵向链路；
- 中文 PDF 视觉验收；
- 文档、能力清单、项目状态和比赛材料同步；
- M7 完成门禁与 GitHub 推送。

## 14. 非目标

- 不实现任意用户自定义 HTML、CSS 或脚本；
- 不允许模型生成或修改业务数值；
- 不在报告生成时重新查询业务数据库；
- 不实现报告在线协同编辑、审批流和电子签章；
- 不开放公共分享链接；
- 不在 M7.7 实现开放式 Python 沙箱、机器学习训练或完整可观测平台；
- 不拆分独立报告微服务。

## 15. 与后续里程碑的关系

M7.7 完成后，M7 达到完整产品闭环：自然语言提问、连续追问、可信查询、统计分析、图表展示和正式报告导出。下一阶段进入 M8：隔离沙箱、黄金评测集、评测中心和全链路可观测性。M9 再处理容量、备份恢复、发布加固和比赛最终交付。
