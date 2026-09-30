# 高级分析与建模：实施计划

依据：已批准的 `docs/superpowers/specs/2026-09-28-advanced-analysis-modeling-design.md`。
执行原则：先写失败测试，再实现；逐批保留真实证据，不把基础模块通过当作产品闭环完成。

## 批次一：相关性与统计异常

- A1 严格协议与数学引擎：独立 `packages/analysis_engine/advanced.py`，Pearson/Spearman（平均秩）、IQR（线性插值四分位数），字段/数值/样本/体积边界；不引入重量级训练依赖。
- A2 工具处理器：`packages/analysis_engine/tools.py`，通过受信任的授权产物读取器加载数据，只接收来源 ID 和算法参数，校验引用匹配，严格拒绝未知输入；更新默认工具 schema 和版本。持久化/权限校验由生产读取器负责，不以测试读取器代替。
- A3 授权与持久化：API/Worker 读取器验证当前成员、源/目录/语义版本、摘要、完整结果及查询证据；写入真实 ToolCall/Artifact/Evidence/Validation，拒绝路径无副作用。
- A4 图表与展示：散点数据和异常标记产物、受限 ChartSpec，真实浏览器 SVG 可见，桌面/移动可用；完成批次验收记录。

A1/A2 先运行专项 pytest，再运行 Ruff/MyPy 和全量回归。测试覆盖同值、反向、并列秩、配对缺失、布尔、非有限数、恶意未知字段、数据裁剪和大数稳定性。

## 批次二：六算法训练与推理

- B1 严格 ModelSpec/结果协议、算法/参数白名单；锁定 scikit-learn/skops 依赖并安全审计，避免依赖只装在开发环境。
- B2 完整授权查询/快照、规模与缺失记录、模拟明细数据生成脚本及说明；不覆盖现有数据库数据。
- B3 Pipeline、先拆分再预处理、回归/分类/聚类/异常六算法、基线/评估/解释，固定合成数据真实训练测试。
- B4 固定镜像与主机代理、严格输入输出清单、资源/网络限制、取消/超时；API 和 Worker 不获得 Docker socket。验证实际容器行为，不仅断言参数字符串。
- B5 迁移、模型权限、模型/版本/任务、租约/attempt 幂等发布、对象存储；验证迁移可回退及旧流程兼容。
- B6 内部 skops 白名单、摘要/依赖兼容、推理字段契约，撤权/跨空间/坏文件拒绝。
- B7 六算法实际 API/后台/存储/推理闭环、运行中取消/陈旧任务拒绝，提交独立验收记录。

## 批次三：持续对话整合

- C1 扩展 Intent/路由/上下文、结构化提取与计划生成；先离线协议验收，真实 LLM 需另行预算授权。
- C2 A/B 工具生产绑定、自然语言澄清/错误、训练确认/幂等重投、数据与模型上下文继承/切换清理。
- C3 保留底部对话框、真实进度/取消、相关性/异常/模型卡片、代码查看/建议追问；响应式及真实浏览器验证。
- C4 报告新产物/证据引用、六算法演示问法、五轮会话/基本聊天查询回归；能力清单仅开放真实绑定且验收通过的工具。

## 门禁与完成记录

每批运行后端测试/Ruff/严格 MyPy；前端变化运行 lint/typecheck/test/build；新增依赖审计/锁一致性；检查密钥/Git diff。单独提交并推送，不包含用户现有 M3 文档、未知评测 JSON、output 和 tmp。Docker 主业务服务不做工厂重置或删卷。

最终关闭前 A3/A4、B7、C4 必须有真实链路验收。离线模型协议桩不宣称 DeepSeek 准确率。任意脚本沙箱、未知源适配、正式发布/性能/灾备和最终材料仍是独立事项。

## 当前进度

2026-09-28 ADV-B1：核心ModelSpec/结果/预测/模型文件协议、六算法参数白名单及四项生产依赖精确锁定完成，112专项/848全量通过，1条件跳过，覆盖率90.58%，本地依赖审计通过。尚无训练或对话入口；B2/B3及后续隔离发布仍待实现。详见 `docs/acceptance/ADV-B1-model-contracts-2026-09-28.md`。

2026-09-28 ADV-A4：第一批真实源查询、五轮会话、相关/异常计算、报告HTTP/Outbox/Celery/MinIO和桌面/移动图表下载联合验收通过；修复两处高级分析上下文遗漏。后端736通过、1项条件跳过，覆盖率90.43%，浏览器2/2通过。下一批B六算法训练与推理仍待实现，C4不整体关闭。详见 `docs/acceptance/ADV-A4-real-stack-browser-2026-09-28.md`。

2026-09-28 ADV-A3：C4相关性/IQR报告整合代码和来源重验完成，静态SVG与真实PDF容器冒烟通过；后端733通过无跳过、覆盖率90.42%，前端99通过及静态/构建通过。完整报告API/对象存储/浏览器联合验收、第一批真实会话联测与批次B仍待完成，不关闭完整C4或三批。详见 `docs/acceptance/ADV-A3-advanced-report-integration-2026-09-28.md`。

2026-09-28 ADV-A2：A3生产会话工具绑定、真实领域写入及A4结果组件/SSR图表已接通，C1/C2加入相关性、异常与方法切换及可信解释。后端711通过无跳过、覆盖率90.33%；前端98通过及静态/构建通过。真实浏览器/源查询联合验收及高级分析报告C4仍待完成，不关闭完整第一批；B六算法尚未实现。详见 `docs/acceptance/ADV-A2-advanced-analysis-runtime-2026-09-28.md`。

2026-09-28：A1/A2 数学引擎、严格协议和工具绑定完成；A3 的当前权限与真实持久化证据读取器完成，生产任务写入/绑定仍待接通。新增79项回归，后端699通过无跳过、覆盖率90.29%。A4、B/C 尚未完成，不能宣称网页可使用新能力。验收见 `docs/acceptance/ADV-A1-advanced-analysis-foundation-2026-09-28.md`。
# Execution update: 2026-09-29

See [ADV-B3/B6/B4a acceptance](../acceptance/ADV-B3-B6-B4a-model-execution-2026-09-29.md). Eight algorithm/task combinations pass real fixed-image training and reloaded prediction. B3 and internal-file B6 foundations are implemented; B4a fixed image/file protocol is verified. Production B2/B4/B5/B6 authorization/publication, B7 and conversation batch C remain incomplete. Next: persisted job/version/lease service, then trusted host agent and object storage, then conversation integration. No website capability is opened by offline/container acceptance alone.

# Execution update: 2026-09-30

B5a persistence schema and lease/attempt state transitions are implemented with SQLite-isolated 0015 upgrade/downgrade and lifecycle tests. See [ADV-B5a acceptance](../acceptance/ADV-B5a-model-job-persistence-2026-09-30.md). Production PostgreSQL full-chain migration, MinIO, host agent, API/worker and conversation integration remain open. Do not enable model tools.

B5b trusted API-side snapshot-to-job service now handles current authorization, object-write ordering and idempotent replay; see [ADV-B5b acceptance](../acceptance/ADV-B5b-snapshot-to-job-service-2026-09-30.md). The service is not a public API and does not execute training.

B4b now has a code-owned Docker create policy with a fixed image ID and resource/isolation flags. See [B4b acceptance](../acceptance/ADV-B4b-fixed-host-container-policy-2026-09-30.md). No live host agent or new Docker acceptance yet.

B4c now has a trusted-host, persisted-job-ID execution flow, fixed-directory file exchange, authorization/cancellation polling, validated output and transactional version publication. See [B4c acceptance](../acceptance/ADV-B4c-host-job-runtime-2026-09-30.md). Four offline orchestrator tests pass; Docker Desktop and real MinIO remain unavailable/unverified, and a long-lived host agent plus API/Worker/conversation wiring remain open.

B4d adds a separately launched polling process and a private MinIO adapter for model objects. See [B4d acceptance](../acceptance/ADV-B4d-host-polling-object-store-2026-09-30.md). Protocol/polling substitutes pass eight tests; real PG/MinIO/Docker integration, host operations and all user-facing routes remain open.

B5c adds default-disabled authenticated HTTP create/status/cancel for model jobs. See [B5c acceptance](../acceptance/ADV-B5c-guarded-model-api-2026-09-30.md). No user-visible modeling capability is enabled; next gates are real-stack API-to-host validation, then conversation/prediction/report integration.

B4e closes deterministic queued revocation to a terminal state and adds mocked Docker normal/cancel/timeout/cleanup tests. See [B4e acceptance](../acceptance/ADV-B4e-host-lifecycle-revocation-2026-09-30.md). The current complete-query artifact path is at most 1,000 rows, not the approved 20,000-row dedicated training-data path; B2 remains open.
