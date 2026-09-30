# 智析 Data Agent 项目状态与剩余流程

更新：2026-09-28。M7.7-D6已复验当前源码的隔离全栈报告闭环，M8仍在开发，M9已进入质量与部署验收；另有[M9入口及官方赛题差距审计](acceptance/M9-entry-gap-audit-2026-09-28.md)。历史切片数字保留在各自验收记录与Git历史。

## 当前结论

2026-09-30 ADV-B2a：训练数据准备拒绝把查询脱敏标记当作类别特征或目标；3项专项和全量后端1023通过、1项跳过，覆盖率90.73%。专用20,000行受权查询仍未实现。详见[ADV-B2a记录](acceptance/ADV-B2a-masked-training-boundary-2026-09-30.md)。

2026-09-30 ADV-B4e：补齐主机容器取消/超时/清理替身测试和来源撤权时排队任务终态处理；全量后端1020通过、1项跳过，覆盖率90.73%。确认当前来源虽拒绝截断查询，但常见查询最多1000行，尚非20,000行专用训练查询。真实Docker/MinIO/PG及预测/会话闭环仍未完成。详见[ADV-B4e记录](acceptance/ADV-B4e-host-lifecycle-revocation-2026-09-30.md)。

2026-09-30 ADV-B5c：新增默认关闭的受控建模任务HTTP接口，支持受权提交、幂等重投、本人查询和取消；撤权与存储故障安全响应。4项专项及全量后端1011通过、1项跳过，覆盖率90.48%。真实PG/MinIO/Docker联合、会话和网页验收未完成，默认仍关闭。详见[ADV-B5c记录](acceptance/ADV-B5c-guarded-model-api-2026-09-30.md)。

2026-09-30 ADV-B4d：增加独立主机进程的有限批量轮询、过期租约回收和私有MinIO对象适配；8项专项通过，全量后端1007通过、1项跳过，覆盖率90.46%。尚无真实PostgreSQL/MinIO/Docker联合验收，未开放API或网页。详见[ADV-B4d记录](acceptance/ADV-B4d-host-polling-object-store-2026-09-30.md)。

2026-09-30 ADV-B4c：新增按持久化任务ID领取、快照重验、固定容器执行、取消/撤权轮询、结果完整性验证及事务性版本发布的内部主机流程。4项离线编排测试通过，全量后端999通过、1项跳过，覆盖率90.60%。当前Docker与真实MinIO验收、常驻代理及API/对话入口仍未完成。详见[ADV-B4c记录](acceptance/ADV-B4c-host-job-runtime-2026-09-30.md)。

2026-09-30 ADV-B4b：主机专用容器启动策略已固定镜像ID、资源、无网络、非root与挂载边界，6项专项测试通过；主机代理和当前Docker实测尚未完成，不对外开放。详见[ADV-B4b记录](acceptance/ADV-B4b-fixed-host-container-policy-2026-09-30.md)。

2026-09-30 ADV-B5b：当前授权来源到完整快照对象与排队任务的内部服务已接通，同键重投不重复写对象、撤权/存储期间撤权阻断入队；使用替身存储和来源进行专项测试，尚无真实MinIO/主机代理/API公开入口。详见[ADV-B5b记录](acceptance/ADV-B5b-snapshot-to-job-service-2026-09-30.md)。

2026-09-30 ADV-B5a：训练快照回执、任务、模型注册表和版本的空间隔离表及0015迁移已实现；幂等入队、租约重领、撤权/取消/陈旧attempt阻止发布和对象摘要读回已通过服务层测试。当前没有网页/API/主机代理建模闭环，Docker未就绪导致完整PostgreSQL迁移尚未复验。详见[ADV-B5a记录](acceptance/ADV-B5a-model-job-persistence-2026-09-30.md)。

2026-09-28 ADV-B1：新增六算法核心任务/结果/预测/内部模型文件协议、参数白名单及生产依赖精确版本和锁文件；112项专项通过，全量后端848通过、1项条件跳过、覆盖率90.58%，本地依赖审计通过。当前没有训练执行、模型加载、API或对话入口，不能宣称六算法可用；下一步B2数据准备与B3真实训练。详见[ADV-B1记录](acceptance/ADV-B1-model-contracts-2026-09-28.md)。

2026-09-28 ADV-A4：独立真实 PostgreSQL 数据源完成五轮高级分析、方法切换与解释、IQR 检测、Outbox/Celery/MinIO 三格式报告及桌面/移动浏览器验证。修复高级分析续问遗漏和图表覆盖可信查询上下文问题；新增四项回归，后端736通过、1项条件跳过，覆盖率90.43%，真实浏览器2/2通过。第一批主链路联合验收补齐；使用固定离线意图响应，不宣称真实模型准确率或分析 Celery 分发已验收。六算法建模和完整C4仍未完成。详见[ADV-A4记录](acceptance/ADV-A4-real-stack-browser-2026-09-28.md)。下方旧记录为历史。

2026-09-28 ADV-A3接入相关性/IQR报告章节、计算与来源重验、真实静态SVG及模板1.1.0兼容。后端733通过无跳过、覆盖率90.42%，前端99通过及静态/构建通过；Ruff245文件格式/MyPy161源文件通过。真实非root无网络容器两类PDF渲染冒烟通过，本地API/Worker/Web已更新健康。完整真实会话/源SQL/报告对象存储联合验收仍待完成，六类建模未实现，C4不整体关闭。详见[ADV-A3记录](acceptance/ADV-A3-advanced-report-integration-2026-09-28.md)；下方旧记录保留历史。

ADV-A2本地API/Worker/Web已重新构建并启动健康，网页入口和API健康检查HTTP200；中文目录构建使用现有COMPOSE_BAKE=false兼容设置，未重置Docker或删除主业务卷。

2026-09-28 ADV-A2接通相关性/IQR会话执行、自然语言结果、可信重算解释、方法续问、散点图与异常标记。后端711通过无跳过，覆盖率90.33%；前端98通过及静态/构建通过，Ruff241文件格式/MyPy158源文件通过。真实源SQL/模型问答/完整浏览器联合验收和高级分析报告导出仍待完成，六算法建模未实现；不宣称全部完成。详见[ADV-A2记录](acceptance/ADV-A2-advanced-analysis-runtime-2026-09-28.md)。下方ADV-A1及旧数字为历史记录。

2026-09-28 高级分析三批规格获批并进入开发。ADV-A1 完成 Pearson/Spearman/IQR 数学引擎、严格工具处理器及当前授权/查询证据读取器；修复新读取器的会话缓存导致外部撤权、账号停用、源禁用不刷新问题。新增79项回归，后端699通过无跳过、覆盖率90.29%，Ruff238文件格式/MyPy157源文件及密钥扫描通过。工具尚未绑定生产会话、未展示新图表；六算法训练/推理及持续对话整合未完成。详见[ADV-A1记录](acceptance/ADV-A1-advanced-analysis-foundation-2026-09-28.md)。下方G19及更早数字保留历史证据。

M9-G19按批准范围新增32项报告存储/PDF故障、语义映射与发布拒绝回归，生产逻辑及门槛不变。最终后端620通过无跳过，覆盖率90.10%首次达到90%门槛；真实PostgreSQL可选预算及发布身份测试启用。Ruff232文件格式/MyPy154源文件、密钥扫描、本地后端依赖审计通过；前端94/94、静态/类型检查、构建及生产依赖审计通过，Compose配置通过。完整远端CI/全部镜像构建仍未验证，不能宣布生产就绪。当前数字以[G19记录](acceptance/M9-G19-report-semantic-regression-2026-09-28.md)为准，下方G10—G18等内容保留历史证据。

M9-G17已按用户批准完成三项：语义发布身份边界（含真实PostgreSQL拒绝及重新发布绑定）、父组件图表测试隔离且保留真实SVG测试、WeasyPrint70.0升级与真实三格式报告/下载撤权闭环。前端默认并行连续三轮94/94，静态检查和构建通过；后端588通过无跳过，Ruff230文件格式/MyPy154源文件通过，本地依赖审计与锁检查通过。覆盖率仍89.30%，完整CI未关闭。历史G15审计失败及G10偶发超时保留为修复前证据；当前验收和剩余边界以[G17记录](acceptance/M9-G17-approved-hardening-batch-2026-09-28.md)为准，不代表整个产品完成。

M9-G15按CI实际目录补跑包含scripts的静态门禁：Ruff通过、229文件格式通过、MyPy154源文件通过；前端生产依赖审计0项，Compose配置语法通过。后端WeasyPrint66.0审计失败，5行去重为3个公告，审计与上游修复版本存在不一致，不承诺仅升级70即可全部关闭。G12/G13限定检查范围的历史数字保留；完整CI、安全、备份/交付仍未关闭。详见[M9-G15复核](acceptance/M9-G15-ci-scope-security-revalidation-2026-09-28.md)。

M0—M6已形成产品主链路，完成结论沿用各阶段既有验收，不表示今天重新验证了所有环境。M7.7报告闭环已在当前源码的隔离真实环境复验；M8仍在开发，M9已开始但远未关闭，整个项目不能标为生产就绪或全部完成。

最新未发布黄金草案为0.1.19，共144条。隔离离线评测及实际API/Outbox/Celery链路均144/144，多轮20/20，付费模型调用0；这些结果不能标为DeepSeek准确率。最近一次后端全量回归580项通过、无跳过（G16独立真实PostgreSQL预算测试启用）；G15包含scripts的Ruff与229文件格式检查通过，严格MyPy154源文件通过。覆盖率89.30%低于90%，完整CI仍失败。首次0.1.10为65/69，其失败证据保留；0.1.11依据单行指标卡原则修正四条单点输出断言，数值/上下文/Evidence要求不变。

最近前端全量94/94、静态检查及构建通过；E3d趋势桌面/390px移动合成API浏览器夹具2/2通过，不代替真实后端联合验收。此前发现的并行图表测试超时风险仍未关闭。

2026-09-28按当前GitHub CI原命令本地复核发现完整门禁不通过：Ruff lint 61错（主要为历史文稿脚本长行），format仍有历史文件不符合，MyPy把`scripts`计入后154文件中6文件38错。此前的Ruff通过与MyPy 124文件通过仅指当时限定范围，不能声称整个CI已绿。官方赛题列举的高级建模、未知源端到端适配和最终材料也没有充分的终态验收；具体见上述审计。

M9-G1已将上述Ruff lint、全库format及严格MyPy问题修复，静态门禁本地通过；完整CI仍未通过：总覆盖率85.75%低于90%，前端全量测试首次70/71、无后端并发时重跑71/71。仍需补覆盖率、证明测试稳定性并完成依赖审计与Compose验证。详见[M9-G1静态门禁记录](acceptance/M9-G1-ci-static-gates-2026-09-28.md)。

M9-G1追加审计：Compose配置通过、前端生产依赖审计0项；后端依赖审计对当前`WeasyPrint 66.0`报5条告警（含重复），其中至少一项上游确认需升级至70.0。安全升级及PDF实测尚未完成；仍不能说依赖审计或完整CI通过。

M9-G2新增查询执行边界测试8项，全量覆盖率由85.75%增至86.16%，仍低于90%并明确失败；Ruff、格式和严格MyPy仍通过。参见[M9-G2测试记录](acceptance/M9-G2-query-runtime-test-2026-09-28.md)。

M8歧义缺口不宜通过同义问法凑数；[E2aa发布边界诊断](acceptance/M8-E2aa-semantic-publication-boundary.md)在内存夹具复现归档模型、草稿激活版本、跨空间版本指针和他模型版本指针仍被Agent语义加载。产品修复与六种不同状态验收待方案确认，现有144/144不包含这些失败场景；尚未证明普通用户可写入非法指针或发生真实数据泄露。

M9-G3增加模型网关协议与故障测试9项，全部使用本地模拟传输、无付费调用；全量覆盖率升至86.53%，仍低于90%。详见[M9-G3测试记录](acceptance/M9-G3-model-gateway-test-2026-09-28.md)。

M9-G4增加查询服务执行与探索性SQL边界测试10项，修复无时区到期时间比较异常；跨空间、过期、目录更新在连接前拒绝，成功路径校验目录画像驱动的脱敏与证据摘要，连接失败仅留安全错误；探索性SQL验证目录白名单、行数上限和危险SQL拒绝。后端全量530项通过、1项跳过，覆盖率86.83%仍低于90%。详见[M9-G4测试记录](acceptance/M9-G4-query-service-test-2026-09-28.md)。

M9-G5新增报告后台任务3项可靠性测试，覆盖三格式发布、重复投递、存储故障重试、非法规格失败。后端全量533项通过、1项跳过，覆盖率87.21%仍低于90%；本地桩不代替真实Worker/MinIO/PDF部署验收。详见[M9-G5测试记录](acceptance/M9-G5-report-worker-test-2026-09-28.md)。

M9-G6以当前代码新构建非root、无网络Worker验收镜像并成功生成合成PDF；Windows本机因缺`libgobject-2.0-0`不能直接渲染。此为容器渲染冒烟，不是全链路或正式发布；镜像尚未绑定Git revision，且依赖安装未使用锁文件、WeasyPrint 66.0安全告警未关闭。详见[M9-G6记录](acceptance/M9-G6-pdf-container-smoke-2026-09-28.md)。

M9-G7新增报告HTTP工作流与预览安全测试2项，覆盖幂等创建、浏览、失败重试、成员撤权后拒绝和HTML预览沙箱响应头。后端全量535项通过、1项跳过，覆盖率87.43%仍低于90%。详见[M9-G7记录](acceptance/M9-G7-report-http-boundary-2026-09-28.md)。

M9-G8新增语义查询服务3项合成测试，验证已发布确认映射生成持久化可信查询、失效映射和草稿版本拒绝。后端全量538项通过、1项跳过，覆盖率87.69%仍低于90%；不包含待确认的跨空间发布指针修复。详见[M9-G8记录](acceptance/M9-G8-semantic-query-service-2026-09-28.md)。

M9-G9从当前源码构建非root API镜像，在无主机端口、无持久卷的专用容器网络中完成PostgreSQL空库迁移到0014、最新迁移降级至0013再升级、API连接检查，以及带合成工作空间的整库备份/独立恢复/ORM回读；临时数据库、备份和网络均已清理。尚不等于全栈空环境部署、MinIO/密钥备份或正式灾备。详见[M9-G9记录](acceptance/M9-G9-empty-deploy-postgres-restore-2026-09-28.md)。

M7.7-D6以当前生产代码在专用无端口、无卷全栈中复验API、PostgreSQL、Redis、MinIO、Worker、Beat及真实Outbox报告投递；三格式对象摘要、PDF授权下载200、匿名拒绝和撤权403均通过，临时资源已清理。合成报告由数据库直接种子创建，不等于前端/创建接口或正式发布验收。详见[M7.7-D6记录](acceptance/M7.7-D6-current-source-stack-acceptance.md)。

M9-G10复核当前前端：lint、typecheck、生产构建通过；默认并行测试出现70/71的图表附件超时，单文件7/7及串行全套71/71通过，故前端测试稳定性仍未关闭，浏览器图表SVG可见性亦待验收。详见[M9-G10诊断](acceptance/M9-G10-frontend-test-stability-diagnostic-2026-09-28.md)。

M9-G11核查现存覆盖率报告：10,164条可计语句中1,251条未覆盖，按同样分母达到90%仍需至少235条；评测和分析Worker入口在该报告中均为0%，PostgreSQL评测适配器为45%。这是测试优先级诊断，不是新代码验收。详见[M9-G11记录](acceptance/M9-G11-backend-coverage-gap-audit-2026-09-28.md)。

M8-E3d在用户批准后实现最近最多30次同冻结条件的历史趋势与精确比例表；默认前端94/94、lint/typecheck/build通过，桌面及390px移动合成API浏览器夹具2/2通过。尚未以多次真实持久化运行联合验收，不关闭完整E3或图表测试稳定性缺口。详见[M8-E3d记录](acceptance/M8-E3d-evaluation-history-trend-2026-09-28.md)。

M9-G12在用户批准后整批新增20项评测/分析Worker可靠性测试，验证真实SQLite持久化、恢复、事务回滚和排队追问激活；两个任务入口语句覆盖均100%。全量558通过、1跳过，总覆盖率88.30%仍未过90%，同分母尚差至少173条；静态检查及密钥模式扫描通过。局部桩不代表真实模型或Celery并发验收。详见[M9-G12记录](acceptance/M9-G12-worker-reliability-batch-2026-09-28.md)。

M8-E3e以当前源码OCI revision标记的非root镜像，在独立空环境通过真实API、Outbox、Celery、PostgreSQL执行两次v0.1.19，均144/144、模型调用0；真实桌面/移动页面读取两条持久化趋势并刷新恢复，横向溢出0，无API结果拦截。历史趋势真实联合验收已完成；完整M8仍未关闭。详见[M8-E3e记录](acceptance/M8-E3e-real-persisted-history-2026-09-28.md)。

M9-G13按确认方案新增21项分析/持续会话HTTP回归，覆盖五角色、双空间资源边界、撤权、幂等追问、澄清恢复、确认/重试及事件游标；真实SQLite领域记录拒绝后不产生副作用。全量579通过、1跳过，覆盖率89.30%，同分母尚差至少72条；静态检查及密钥扫描通过。会话SSE有限替身仅验证路由，持续连接及并发仍待验收。详见[M9-G13记录](acceptance/M9-G13-analysis-http-regression-2026-09-28.md)。

M9-G14复核默认前端94/94及lint/typecheck/build通过，仍有jsdom画布与构建块体积告警；真实Chrome直接挂载现有图表组件，四种图表×桌面/手机共8种合成组合均验证数据路径、标签、无溢出、窗口缩放及无页面异常。此为组件诊断，不是完整会话/真实Agent图表验收，G10稳定性修复仍待确认。详见[M9-G14记录](acceptance/M9-G14-chart-browser-component-2026-09-28.md)。

M9-G16在独立空PostgreSQL/tmpfs容器执行现存预算并发测试，连续5次验证两线程只获得一次额度、重复结算只生效一次；实际调用供应商0。全量580通过、无跳过，覆盖率仍89.30%且90%门禁明确失败。合成夹具及容器均已清理，不代替真实模型计费或live入口验收。详见[M9-G16记录](acceptance/M9-G16-real-postgres-budget-race-2026-09-28.md)。

## 里程碑

| 阶段 | 当前状态 | 已实现范围 | 剩余验收 |
|---|---|---|---|
| M0工程基线 | 阶段已完成 | Monorepo、Compose、迁移、质量门禁 | M9复验CI和部署 |
| M1身份权限 | 阶段已完成 | 登录、工作空间、成员/邀请、五角色Policy Engine | M9最终越权矩阵 |
| M2数据与元数据 | 阶段已完成 | PostgreSQL/MySQL接入、凭据加密、网络策略、异步目录、版本/差异、生命周期与控制台 | M9兼容和故障回归 |
| M3语义模型 | 阶段已完成 | 版本化模型、19项制造指标、物理映射、合成数据与映射工作台 | M9最终回归 |
| M4查询 | 阶段已完成 | 语义编译、双方言、SQL安全门禁、只读执行、脱敏和证据 | M9安全/性能复验 |
| M5 Agent | 阶段已完成 | 模型网关、持久化状态图、工具计划、Outbox、多轮澄清/确认/取消/重试；此前真实模型调用验收 | M8完整基准与观测 |
| M6交互工作台 | 阶段已完成 | SSE恢复、持续会话、自然语言回答、结果与证据定位、桌面/移动端 | M9兼容与性能复验 |
| M7分析报告 | 隔离环境验收关闭 | 描述统计、可信图表、报告、PostgreSQL/Outbox/Celery/MinIO/PDF与撤权下载链路 | M9部署和容量验证 |
| M8评测可观测性 | 开发中 | 严格判分、144条草案、持久化受权评测中心、分页筛选/谨慎对照、恢复、调用预算底座、运行版本冻结 | 见下表及下一步 |
| M9产品加固交付 | 已进入质量门禁与回归测试 | 有基础技术文档与逐切片验收记录；静态检查已通过，补齐部分查询与网关安全回归，已核实完整CI阻塞项和官方需求差距 | 覆盖率达到门槛、完整CI、性能、安全、备份恢复、迁移回滚、运维及比赛最终交付 |

## 黄金评测覆盖：未发布、未完成人工审阅

| 类别 | 当前 | 最低目标 | 最低缺口 | 证明边界 |
|---|---:|---:|---:|---|
| 标准 | 66 | 60 | 0 | 固定意图、真实合成源查询，指标集合覆盖模板全部19项 |
| 多轮 | 20 | 20 | 0 | 同会话细化、解释、寒暄后续问、时间范围及指标变更 |
| 歧义 | 14 | 20 | 6 | 自然澄清、精确缺失字段、重复口径、无激活草稿与跨空间口径 |
| 异常 | 24 | 20 | 0 | 空集/零分母/缺字段、模型及供应商故障、数值/时间及生产比例边界；不是完整风险覆盖 |
| 安全 | 20 | 20 | 0 | 系统门禁；不等于模型提示注入或Agent行为证明 |
| 合计 | 144 | 140 | 6 | 按分类缺口求和；标准和异常超额不能抵消其他类别 |

按分类仍缺歧义6条；总数超额不代表分类达标。设备五项指标已有聚合验证，但未证明排名/分组或时间趋势；部分质量批次比例相同，仍需异质批次检验加权。数量达标仍需业务多样性、人工审阅和真实模型基准。

安全评测包含合法SELECT正向对照，不能以全拒绝取得安全通过；18种SQL攻击及跨工作空间请求验证稳定错误码、无执行器调用、无平台产物副作用及合成canary不外泄。仍须补充模型绕权、提示注入、未授权目录与敏感字段探测的Agent行为证明，不能因为20条系统门禁就关闭安全评测。

## M8子阶段与下一步

1. E2继续补齐歧义及异常/Agent行为安全风险；团队逐条核对预期和来源后才能发布黄金集。当前0.1.19为草案，历史套件保持不可变。标准/多轮/异常/安全数量达标不代表所有业务维度、源断连、时区、业务数据质量和提示注入等风险全部覆盖。计划达成率已有不等计划量加权、零计划、零实际产量和超额达成验证。语义歧义验证直接构造持久化状态，不等于发布流程或非法active_version指针验证。已复现不支持维度被绑定、未知维度误报指标的问题，产品修复待确认，尚未计入通过案例。
2. E3受权API、持久化、Outbox/Celery、取消/恢复、分页/分类筛选、谨慎版本对照已有验收；历史趋势页面经E3d合成边界测试及E3e两次真实144案例运行联合验收。稳定失败回链仍需补齐，不能把全部E3视为完成。实际E2v任务保存93个运行引用，但在主平台0个可解析；临时夹具清理后未保存执行档案。参见[E3c回溯缺口](acceptance/M8-E3c-trace-retention-gap.md)，归档方案待确认，不添加失效链接或放宽审计员分析权限。
3. E4a预算预留、实际usage计量、未知用量暂停为底座；live公开入口关闭。管理员真实模型入口、执行器与基准未完成，每批付费运行需另行明确授权。
4. M8-04全链路观测尚未实施，也不在已批准评测中心规格范围内。推荐本地OpenTelemetry、Prometheus与脱敏结构化日志；等待方案确认和详细规格审阅，不自动接入外部观测平台。
5. M8-01一次性无网络、无凭据、非root、限资源沙箱尚未设计实施；现有确定性工具继续优先，未给Agent任意Python权限。
6. 随后推进M9容量/性能、安全、备份恢复、升级回滚、发布运行手册及真实比赛材料；不得以AI效果图替代实际实现证据。

恢复运行前核对冻结的模型、工具与提示版本；发生漂移按`evaluation.runtime_changed`阻断，不把不同版本混入结果。旧历史记录保持原样，应新建新版本任务。

## 当前权威证据

- [E2z质量多轮](acceptance/M8-E2z-quality-conversation-acceptance.md)，[144条结果](acceptance/evidence/M8-E2z-2026-09-27-postgres-v0.1.19.json)。
- 最新实际部署任务`0b8eea2c-157b-4d86-914a-d1ffbd3d5f2c`：completed、144/144、多轮20/20、调用0，工具版本`draft-postgres-quality-conversations-v15`。宿主机临时58125端口连接失败，API从容器内部HTTP验收，不算浏览器验收。
- [E2y五项设备指标](acceptance/M8-E2y-equipment-metric-acceptance.md)保留为历史指标覆盖验证。
- [E2x八项质量指标](acceptance/M8-E2x-quality-metric-acceptance.md)保留为历史质量指标验证。
- [E2w语义状态歧义](acceptance/M8-E2w-semantic-ambiguity-acceptance.md)保留为历史歧义验证。
- [E2v生产比例边界](acceptance/M8-E2v-production-boundary-acceptance.md)保留为历史边界验证。
- [E2u计划达成率业务评测](acceptance/M8-E2u-completion-rate-acceptance.md)保留为历史业务验证。
- [E2t缺失信息路由澄清](acceptance/M8-E2t-route-clarification-acceptance.md)保留为历史追问验证。
- [E2s数值与时间边界](acceptance/M8-E2s-numeric-boundary-acceptance.md)保留为历史边界验证。
- [E2r同会话条件变更](acceptance/M8-E2r-conversation-condition-change-acceptance.md)，[首次65/69失败记录](acceptance/evidence/M8-E2r-2026-09-27-postgres-v0.1.10.json)保留为历史验证和预期修订证据。
- [E2q供应商故障与自然引导](acceptance/M8-E2q-provider-failure-acceptance.md)保留为历史故障处理证据。
- [E2p安全矩阵与执行版本](acceptance/M8-E2p-api-security-matrix-acceptance.md)为历史安全分类和版本修复证据。
- [E2o模型输出故障](acceptance/M8-E2o-model-output-failure-acceptance.md)、[E2n多轮澄清](acceptance/M8-E2n-conversation-clarification-acceptance.md)。
- [E3a离线评测持久化](acceptance/M8-E3a-durable-evaluation-center-acceptance.md)、[E3b浏览筛选对照](acceptance/M8-E3b-evaluation-browse-acceptance.md)、[E4a预算底座](acceptance/M8-E4a-live-budget-gate-acceptance.md)。
- [已批准M8评测设计](superpowers/specs/2026-09-25-m8-evaluation-center-design.md)、[实施计划](plans/2026-09-25-m8-evaluation-center-implementation-plan.md)。

临时E2z验收API/Worker在终态验证后清理，原有数据库、队列及源服务保留。用户原有M3文档改动、output和tmp不纳入开发提交；不记录真实密钥或令牌。
# Latest delivery update: 2026-09-29

ADV-B3/B6 foundations and B4a fixed image are verified with eight real algorithm/task combinations, each trained and reloaded for prediction in a restricted container (16 runs). This is NOT a website modeling release. See [current acceptance and remaining gates](acceptance/ADV-B3-B6-B4a-model-execution-2026-09-29.md). Production persisted jobs, trusted host agent, leases/cancellation, object storage and conversation/report integration remain open; do not enable model tools yet.
