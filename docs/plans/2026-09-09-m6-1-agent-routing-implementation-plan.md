# M6.1 Agent 路由与自然澄清实施计划

- 状态：执行中
- 日期：2026-09-09
- 规格：`docs/superpowers/specs/2026-09-09-m6-1-agent-routing-design.md`
- 当前入口：M6.1-D 指标默认策略与多轮修订

## 执行规则

每个切片执行测试先行、最小完整实现、静态检查、全量回归、真实链路、验收记录、Compose 部署、精确提交和 GitHub 推送。默认使用 Fake Gateway；真实 DeepSeek 只在显式开关与受限预算下验收。模型不得选择未授权工具，不得生成或执行任意 SQL。用户已有未提交文件不纳入任何提交。

## M6.1-A：路由与澄清契约

状态：已完成并通过验收（2026-09-09）。验收记录见 docs/acceptance/M6.1-A-routing-clarification-contracts-acceptance.md。

- 扩展 Intent 任务类型，增加严格 `RouteDecision`、`ClarificationRequest`、候选与默认值契约；
- 实现确定性 RoutePolicy，区分能力咨询、目录探索、可信指标查询、高级分析待接入和越界问题；
- 将低置信度从独立阻断条件改为审计信号，只有阻断性歧义或无法唯一解析才澄清；
- 澄清错误携带安全、可行动的结构化原因；
- 覆盖路由矩阵、歧义分类、唯一绑定、默认值和严格 Schema 测试。

验收：能力咨询与目录探索不再进入指标绑定；“分析不良率”在唯一语义模型下可继续；真正的多候选仍暂停并返回具体问题。

## M6.1-B：能力咨询闭环

状态：已完成并通过验收（2026-09-09）。验收记录见 docs/acceptance/M6.1-B-capability-help-acceptance.md。

- 建立版本化 `CapabilityManifest`，列出当前可用、受限和计划中能力；
- 实现无数据访问的能力处理器与确定性中文回答；
- 写入 `assistant_message` Artifact、`capability_manifest` Evidence 和 `capability_scope` Validation；
- 接入现有计划、步骤、工具调用、预算和事件生命周期；
- 覆盖幂等、恢复、能力不越界和无数据库访问测试。

验收：“这是个什么 Agent”和“你能做什么”直接完成并产生可审计回答，不触发目录或查询工具。

## M6.1-C：授权目录探索闭环

状态：已完成并通过验收（2026-09-09）。验收记录见 docs/acceptance/M6.1-C-catalog-exploration-acceptance.md。

- 为 `catalog.search` 实现数据库处理器，检索当前工作空间已发布目录快照；
- 支持数据源、Schema、表/视图和字段的有限搜索及确定性摘要；
- 复用采样开关、敏感识别和脱敏结果，默认不返回原始样例；
- 写入 `catalog_result` Artifact、目录快照 Evidence 和授权/敏感输出 Validation；
- 覆盖 PostgreSQL/MySQL、跨空间隔离、未发布目录、重名候选、数量上限与脱敏测试。

验收：“有哪些数据源”“表格中有什么数据”“inspection 表有哪些字段”返回真实目录内容及快照证据。

## M6.1-D：指标默认策略与多轮修订

状态：待实施。

- 实现 `defaults_applied`，对普通指标查询默认全量时间范围、整体粒度和表格输出；
- 将用户补充解析为严格 ContextPatch，与已有 Intent 合并；
- 区分补充条件与更换任务目标，目标切换时使旧绑定和计划失效；
- 新增 `run.route_selected`、`run.defaults_applied` 和 `run.intent_revised` 事件；
- 覆盖多轮指标保留、目标切换、事件重放、预算和检查点恢复。

验收：“分析不良率”直接完成；需要澄清的问题可通过候选或自由文本从原检查点继续，且不丢失前文。

## M6.1-E：前端呈现与整体验收

状态：待实施。

- 展示 `assistant_message` 和 `catalog_result` Artifact；
- 澄清卡展示具体问题、候选快捷按钮、建议回答和自由文本；
- 技术详情展示路由、默认值和 Intent 修订，不泄露受限上下文；
- 增加组件、状态恢复和 Playwright 桌面/移动端测试；
- 用真实 DeepSeek、PostgreSQL/MySQL 和 Compose 完成产品验收；
- 更新 ADR、README、项目状态、项目日志与 M6.1 验收记录。

验收：规格中的八类产品问题均得到正确回答或具体澄清；刷新、断线和移动端可恢复；全量门禁、Compose 与 GitHub 提交一致。

## M6.1 完成定义

五个切片全部通过；Agent 能稳定路由能力咨询、授权目录探索和可信指标查询；普通指标问题不被可选条件阻塞；真正歧义具有具体可操作的多轮澄清；所有回答均有 Artifact 和适用的 Evidence/Validation；权限、脱敏、预算、恢复与审计边界不退化；自动化、真实浏览器、真实模型和 Docker 部署全部通过。
