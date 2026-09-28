# M9-G17 已批准的三项加固修复

日期：2026-09-28；基线 b2bad78，用户明确批准发布语义边界、前端图表测试隔离、PDF依赖升级三项。按已批准范围实现，不引入新的评测平台或付费模型调用。设计技能用于限定变更，PDF技能用于实际渲染与逐页视觉复核。

## 1. 发布语义身份边界

Agent的真实加载查询同时要求：模型属于当前空间、模型已发布、版本已发布、版本属于当前空间、版本的模型ID与当前模型一致。不能仅凭active_version_id拿到任意版本。

新增8项回归：归档模型、草稿模型、草稿版本、跨空间版本指针、版本空间不一致、另一模型版本指针、无活动版本，以及归档后重新发布的正向绑定。拒绝路径经过真实run_analysis和持久化消息，断言自然语言澄清、执行器调用0、无查询产物/工具调用/证据、合成私有canary不外泄；正向实际bind_intent解析defect_rate及正确模型/版本。

修改前7项失败、1项通过；修改后SQLite组合30项通过，隔离真实PostgreSQL8项通过，补强正向绑定后再次8项通过。数据库测试使用独立随机schema并自动清理。这不是整个发布HTTP流程、所有撤权并发或真实模型基准。

## 2. 图表附件测试稳定性

仅在AnalysisResultPanel父组件单测中隔离ECharts，检查图表产物及可信源正确传给图表组件；去掉5000ms显式等待。独立AnalysisChart测试仍执行真实ECharts SVG，未把渲染测试全部替换成桩。

默认并行前端全量94/94通过；另外连续三轮均94/94，耗时9.44、7.81、6.64秒，其中与后端回归/镜像构建并行。lint、typecheck和生产build通过。不增加超时掩盖问题；不据此承诺所有机器/CI运行99%稳定。真实SSR测试的jsdom画布提示、构建块超过500kB告警仍存在。本机Node24，不代替CI的Node22实跑。

## 3. PDF依赖、审计和真实链路

WeasyPrint从66.0锁定升级到70.0；uv.lock仅更新该包及根依赖元数据，其他锁定版本未变。uv lock --check通过；同步本地editable包元数据后pip check通过；pip-audit --local --skip-editable退出0，No known vulnerabilities found。本次关闭的是本地依赖审计中已发现问题，不是对所有漏洞的保证，也未审计整个容器OS。

按现有Worker Dockerfile构建非root镜像zhixi-three-fixes-worker:20260928，实际容器渲染版本70.0。镜像ID sha256:4586554391a99c5a529e77c5bd53819dd05168c0ba4fe965845c0015e7ac6c18；revision标签为b2bad78-approved-three-fixes-working-tree，明确不是干净提交的正式发布镜像。Dockerfile仍以版本范围pip安装其他依赖，不消耗uv.lock，可复现镜像缺口未关闭。

独立PostgreSQL、Redis、MinIO、API、Worker、Beat六服务，平台迁移至0014；报告由合成领域夹具直接创建，不算前端创建接口验收。真实Outbox/Celery任务一次成功；Markdown/HTML/PDF三个对象摘要匹配，真实HTTP登录及PDF下载200、private no-store、摘要匹配；匿名对象下载AccessDenied，撤权后同令牌下载403。PDF为225047字节、1页，Producer为WeasyPrint70.0，已渲染检查中文、表格及证据定位。没有使用真实业务源或DeepSeek。

另外以现有60行合成脚本在无网络、非root、只读根、限资源的一次性容器渲染408473字节PDF，SHA256为9eb42212a63f31f1b40ebef79e421ebf3cdcdd2ccaf5b345f6a6ab9e473195bc，共4页。Poppler逐页转PNG并检查：中文正常、行1—60完整、前三页重复表头、无表格裁切；最后一页为模拟说明及证据编号。这是分页兼容夹具，不是真实业务质量报告。

额外在升级镜像调用生产render_pdf，分别请求合成HTTP资源、临时合成本地文件及附件。观察到生产deny_external_url均被调用并拒绝，渲染以report.pdf_render_failed失败关闭、没有生成文件。70.0对拒绝回调的后续错误处理涉及_fail_on_errors属性，因此这里只证明拒绝并失败关闭，不称恶意资源被忽略后还能正常出PDF；安全拦截未放宽。

## 4. 全量质量门禁与未关闭项

后端全量最终启用两个可选真实PostgreSQL测试URL，588项执行通过、无跳过；Ruff lint通过、230文件格式通过、严格MyPy154源文件通过。覆盖率10164条语句中9076覆盖、1088未覆盖，89.29555293191657%；90%门禁明确退出1，仍需至少72条有效覆盖，完整CI不能标绿。AnyIO弃用警告保留。中间一次复跑遗漏预算URL出现1项跳过，随后纠正URL并完整复跑，不采用该次作为最终证据。

用户已有M3文档改动及原有output/tmp不纳入提交。临时报告PDF、PNG和覆盖率JSON保留在本地tmp/three-fixes-*及tmp/M9-three-fixes-coverage-final.json，不含真实密钥/令牌。不删除用户已有服务或文件。

清理前核对六容器名及three-fixes标签、tmpfs、Redis唯一匿名卷，以及专用网络仅连接这六服务；测试schema剩余0。随后删除六个临时容器、该Redis匿名卷和专用网络，标签复查无残留。合成tmpfs/卷数据不可恢复，下载PDF及PNG仍保留；既有业务服务、镜像和用户文件未删除。

仍未完成：覆盖率及完整CI、黄金集分类缺口和人工发布审阅、真实模型基准、失败执行档案回链、完整观测、Agent执行沙箱、容量/全栈备份回滚和正式交付；本次三项不代表M8/M9或整个产品完成。
