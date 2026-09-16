# M7 多轮会话与交互式分析实施计划

- 状态：执行中
- 日期：2026-09-15
- 规格：`docs/superpowers/specs/2026-09-15-m7-multi-turn-conversation-design.md`
- 当前入口：M7.2 真实 DeepSeek 多轮验收与 M7.3-B 恢复强化

## 执行规则

每个切片依次执行失败测试、最小完整实现、Ruff、严格 MyPy、全量 Pytest、前端测试与构建、迁移往返、真实服务链路、Compose 部署、验收记录、精确提交和 GitHub 推送。用户已有未提交文件不纳入提交。真实模型测试限制问题数量和调用预算，DeepSeek 密钥只从现有 Worker 环境在内存中传递。

## M7.1 会话领域与兼容投影

### M7.1-A：领域模型与迁移

状态：已完成（验收记录：`docs/acceptance/M7.1-A-conversation-persistence-acceptance.md`）

- 在 Agent persistence 中增加 `AnalysisConversation`、`AnalysisTurn`、状态和关系枚举；
- 为 `AnalysisRun` 增加可空 `conversation_id`、`turn_id`，并建立工作空间一致的索引与外键；
- 新增 `20260915_0010` Alembic 迁移；
- 约束 `(conversation_id, sequence)`、Turn 与 Run 一对一关系和 Conversation 活动轮引用；
- 完成 SQLite 模型测试、PostgreSQL upgrade/downgrade/upgrade 往返和现有数据兼容验证。

完成标准：历史 AnalysisRun 不需改写即可正常读取；新 Conversation/Turn/Run 可以事务性建立且无法跨空间拼接。

### M7.1-B：严格共享契约

状态：已完成（验收记录：`docs/acceptance/M7.1-B-conversation-contracts-acceptance.md`）

- 定义创建会话、发送消息、会话摘要、Turn 摘要和 Conversation View；
- Conversation context 使用严格版本化 Pydantic 模型，不接受 SQL、凭据、代码或任意扩展字段；
- 明确客户端可见字段，排除幂等键、内部队列键、检查点推理和密钥；
- 覆盖额外字段拒绝、长度、分页、状态与关系枚举测试。

完成标准：OpenAPI 和 TypeScript 可稳定消费，敏感内部字段不会进入响应。

### M7.1-C：会话领域服务与首轮创建

状态：已完成（验收记录：`docs/acceptance/M7.1-C-conversation-service-acceptance.md`）

- 原子创建 Conversation、Turn、AnalysisRun、用户消息、事件和 Outbox；
- 首次问题生成确定性会话标题；
- 相同工作空间与幂等键返回同一会话，不重复运行；
- 列表按更新时间倒序，详情严格隔离工作空间；
- 现有 `create_run` 保持兼容，不要求旧调用传 Conversation。

完成标准：首轮通过现有 Worker 正常执行，Run 级证据链不变。

### M7.1-D：会话投影与历史兼容

状态：已完成（验收记录：`docs/acceptance/M7-continuous-conversation-vertical-slice-acceptance.md`）

- 聚合 Conversation、Turn、Run View、消息、产物和运行状态；
- 历史 `/app/analysis/{run_id}` 继续使用原投影；
- 对不属于 Conversation 的历史 Run 提供只读单轮兼容投影，不在 GET 请求写库；
- 分页或窗口化返回历史轮次，避免无限会话一次加载全部大产物。

完成标准：新旧链接同时可用；每个轮次能定位原 AnalysisRun、Evidence 和 Validation。

### M7.1-E：API、权限与基础前端接线

状态：已完成（验收记录：`docs/acceptance/M7-continuous-conversation-vertical-slice-acceptance.md`）

- 增加 Conversation 创建、列表、详情和 View API；
- 所有端点复用 `Action.ANALYSIS_RUN` 并校验 workspace；
- 前端新增 Conversation 类型、API hook 和路由 `/app/conversations/{id}`；
- 首轮页面先复用现有消息与结果组件，为 M7.4 完整交互改造建立兼容入口；
- 组件和 API 测试覆盖 401、403、404、跨空间和旧链接。

完成标准：用户可以通过新会话入口提交首问并看到真实结果，现有运行页面无回归。

## M7.2 多轮继承与主题切换

### M7.2-A：Follow-up 契约与确定性分类

状态：已完成（含真实 DeepSeek 回退与五轮问题链验收）

- 增加 `FollowUpRelation`、安全 ContextPatch 和分类结果；
- 确定性处理“按月”“换成”“与上月相比”“为什么”、能力和目录等高频表达；
- 其余表达通过 Model Gateway 产生严格候选；
- 本地验证关系、字段和上下文，不接受模型生成 SQL、工具名或权限。

### M7.2-B：跨运行 Intent 构建

状态：已完成（含显式时间补丁、指标兼容时间维度绑定与真实问题链）

- 从上轮 `context_after` 白名单继承指标、维度、时间、过滤、比较和 Artifact 引用；
- continue/refine/explain/compare 分别执行明确合并规则；
- switch_topic 清理冲突字段并产生可见主题切换事件；
- 歧义进入自然语言澄清，不静默混合主题。

### M7.2-C：完成态后的继续发送

状态：已完成

- Conversation 消息接口在任何非归档状态可写；
- 当前 Turn 澄清回复继续原 Run，其他稳定状态创建下一 Turn 和 Run；
- 失败轮不更新有效 Artifact 引用，但保留安全意图供修正；
- 每轮重新鉴权并冻结当前发布版本。

## M7.3 串行排队与恢复

### M7.3-A：活动轮和排队事务

状态：基础串行队列已完成；并发版本冲突强化仍待后续切片

- 同一 Conversation 只允许一个活动 Turn；
- 运行中收到的新消息写入 queued Turn；
- 前轮完成后事务更新上下文并激活下一轮 Outbox；
- 并发提交通过 Conversation 版本和唯一序号处理。

### M7.3-B：取消、重试和恢复

- 取消活动轮不删除排队轮；
- 可重试失败保留检查点，永久失败允许下一轮；
- 增加恢复扫描，补发“稳定前轮但下一轮未激活”的事务缺口；
- 验证 Worker 重启、Outbox 重投和重复事件不产生重复 Turn。

### M7.3-C：会话级可重放 SSE

- 建立 Conversation Event 单调序号；
- 事件携带 turn/run 定位字段；
- 支持 Last-Event-ID、心跳、空洞检测和断线恢复；
- 不在事件中发送内部推理或敏感上下文。

## M7.4 连续会话前端

状态：核心纵向切片已完成；主题切换提示、完整无障碍和真实移动端验收待 M7.2 与 M7.4 收尾

- 左栏从运行列表升级为会话列表；
- 按 Turn 内联用户消息、Agent 回复、结果附件和证据入口；
- 输入框在空闲、运行、澄清、失败、取消和越界后均可使用；
- 运行中发送显示排队位置；
- 主题切换显示轻量提示；
- 保留运行技术详情和旧 `/app/analysis/{run_id}` 兼容入口；
- 完成键盘、屏幕阅读、桌面和 390px 移动端测试。

## M7.5 推荐追问

- 基于能力清单、语义支持维度和结果形状生成最多三个确定性建议；
- 建议按钮发送普通消息，重新经过 Agent、Policy Engine 和工具链；
- 缺映射、权限拒绝和越界只推荐当前可执行操作；
- 为建议来源、点击和最终执行结果增加审计事件；
- 通过真实问题链验证连续追问和主题切换。

## M7.6 统计与交互式图表

- 接入趋势、排行、对比和描述统计工具；
- 定义受限 ChartSpec 与字段/Evidence 校验；
- 图表作为 Turn 附件内联，切换展示方式不重新查询；
- 修改指标、时间或过滤创建新 Turn；
- 图表失败不丢失回答、表格和证据。

## M7.7 报告组装

- 从用户选择的已验证 Turn/Artifact 组装报告；
- 输出 Markdown、HTML 和 PDF；
- 报告引用原查询、语义版本、目录快照和验证记录；
- 生成失败保留所有既有分析产物；
- 完成中文排版、下载权限、桌面与移动端验收。

## M7 完成门禁

- 每次回答后均可在同一会话继续提问；
- 多轮上下文保持成功率不低于 90%；
- 运行中连续发送严格按序执行，重复轮次为 0；
- 刷新、SSE 断线和 Worker 重启可恢复；
- 每个结果和图表可定位独立 Run、Artifact、Evidence 与 Validation；
- 权限与危险操作阻断率保持 100%；
- Ruff、严格 MyPy、Pytest、ESLint、TypeScript、Vitest、Playwright、迁移往返、Compose 健康和真实 DeepSeek 链路全部通过；
- 验收文档、Git 提交与部署镜像一致。
