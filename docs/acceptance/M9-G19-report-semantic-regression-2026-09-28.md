# M9-G19 报告存储与语义服务风险回归

日期：2026-09-28；基线b53da11。用户批准G18有限变更范围后新增测试，生产实现、依赖、CI阈值和排除规则均未修改。brainstorming技能用于限定本批现有路径，不扩展新功能。没有调用DeepSeek或读取真实业务数据。

## 新增32项与证据边界

- 报告15项：真实MinioReportObjectStorage包装器的HTTPS/HTTP参数、桶已存在/创建、非法端点不初始化SDK、上传字节/长度/类型、删除、最大下载字节及读失败/超限后的close与release_conn、年龄边界/无时区/不完整元数据；render_pdf的依赖不可用、渲染失败、生产deny_external_url拒绝file/HTTP及正常字节转换。
- 语义17项：真实SQLite ORM执行候选精确匹配/词元匹配、排序和每属性前三条、无匹配、空间过滤、跨空间模型/快照拒绝；发布时重新验证未确认/外空间/不存在物理映射、版本冲突和空模型；合法确认映射通过真实草稿更新后发布且不可再次发布；非法关系/维度/指标/映射引用在模型创建前拒绝；更新与新草稿状态/乐观锁拒绝。核对模型版本、活动指针、版本数量和审计记录无新增副作用。

对象存储SDK及WeasyPrint模块为故障替身，执行的是生产包装器，不是实际网络或实际PDF渲染；G17的真实Outbox/Celery/MinIO/PDF链路证据保留，不用本批替身替代。空间过滤案例包括故意不一致的合成目录行/快照，用于证明读取边界，不宣称所有关联表一致性已解决。SQLite夹具沿用现有query_db，不代表本批所有32项均在PostgreSQL执行。

首次局部运行24通过1失败：新增测试中model/snapshot目标条件写反，实际catalog.not_found正确而预期错误；修正夹具后25/25。后续加入7项非法引用/状态冲突案例，最终32/32。未因失败修改生产规则或削弱拒绝断言。

## 全量回归与覆盖门槛

首次全量612通过、1项可选PostgreSQL测试跳过，覆盖90.02%，退出0。最终在新增7项后启用EVALUATION_BUDGET_POSTGRES_URL和SEMANTIC_BOUNDARY_POSTGRES_URL，620通过、无跳过，57.90秒；原有发布身份8项及预算并发测试实际在独立PostgreSQL运行，其余仍按各自夹具执行。

最终命令保留--cov=apps --cov=packages及--cov-fail-under=90；仅关闭pytest缓存并覆写默认重复-q以显示完整统计，未缩小测试收集范围。10164条语句、9158覆盖、1006未覆盖，90.10232192050374%；相对G17新增82条有效覆盖，分母不变，90%门槛通过。整个报告生成模块94%，语义服务97.546%；尚有未覆盖分支，不称完全无漏洞。详细JSON仅保留在本地tmp/M9-G19-coverage-final.json。

## 其他门禁

- Ruff检查通过、232文件格式通过；严格MyPy覆盖apps/packages/scripts的154源文件通过。
- 全仓库密钥扫描通过，不打印密钥；pip-audit --local --skip-editable无已知漏洞（editable项目正常跳过）。
- 前端默认并行94/94、lint、typecheck和build通过，生产依赖audit为0；本机Node24，不替代GitHub Node22实跑。
- Compose配置校验退出0。本批未重新构建全套镜像，也没有获取GitHub Actions私有运行结果，不据此称完整远端CI全绿。
- AnyIO弃用、真实SSR的jsdom画布提示和超过500kB构建块告警仍保留。

## 独立数据库与清理

创建唯一容器zhixi-m9-g19-20260928，标签zhixi.acceptance=M9-G19，postgres16.4-alpine，127.0.0.1:55441，合成账号/空库、256MiB tmpfs、无持久或bind挂载。第一次pg_isready尚未就绪，后续同一容器确认ready后执行Alembic完整迁移到0014，不重复创建或修复用户Docker配置。

最终SQL核对users/workspaces/evaluation_runs/evaluation_model_calls及临时semantic_boundary_* schema均0。核对名称、标签、tmpfs、端口和无挂载后删除该临时容器，标签复查无残留。tmpfs合成数据不可恢复；用户平台数据库、既有服务、镜像及文件均未删除。

## 项目仍未完成

本批关闭后端90%覆盖门槛，不关闭完整M8/M9。黄金集歧义配额及人工审阅、真实模型基准、失败档案回链、观测/沙箱、赛题常见建模与未知源纵向验收、容量/正式备份回滚和最终比赛材料均需按原范围完成。用户已有M3文档改动、未追踪历史评测证据、output和tmp不纳入提交。
