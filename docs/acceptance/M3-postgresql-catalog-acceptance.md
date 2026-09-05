# M3 PostgreSQL版本目录验收

- 状态：通过
- 日期：2026-09-05
- 范围：PostgreSQL元数据扫描、不可变快照、目录查询与确定性结构差异

## 已实现

- Connector协议加入`scan_metadata`，输出方言无关的`MetadataDocument`；
- PostgreSQL扫描默认排除`pg_*`与`information_schema`，并支持管理员显式选择业务Schema；
- 扫描表、普通视图、物化视图、字段顺序与类型、可空性、默认表达式、注释、主外键、唯一/检查约束和索引；
- 使用授权DNS结果固定实际连接地址，扫描事务保持只读并继承连接、语句和锁超时；
- 单次扫描设置对象数量硬上限，未知Schema、对象超限和无效文档使用稳定安全错误码；
- 连接首次成功后自动投递初始扫描，手动扫描支持Schema范围和`Idempotency-Key`；
- 队列载荷仍然只包含任务ID，凭据只在Worker局部生命周期解密；
- 快照采用递增版本、`building/published/rejected`状态和规范化内容摘要；
- 目录实体按工作空间、数据源和快照隔离，历史发布版本不可变；
- 发布过程在平台数据库事务中完成，失败不替换上一活动快照；
- 使用稳定对象键和规范值比较生成新增、删除与变化记录，差异不依赖模型；
- 重投的运行中任务复用原构建快照，瞬时连接和平台持久化失败进入受控重试。

## API验收

- `POST /data-sources/{id}/scans`返回`202`扫描任务资源；
- `GET /data-sources/{id}/snapshots`返回版本历史与真实对象计数；
- `GET /data-sources/{id}/catalog`支持当前或指定已发布快照；
- `GET /data-sources/{id}/diffs`按目标快照分页返回确定性差异；
- 尚无已发布目录时返回`catalog.not_available`，构建中或被拒绝快照不可作为目录读取；
- 管理员和数据管理员可触发扫描；分析员与审计员只能读取已发布目录。

## 自动化验收

- 覆盖稳定摘要、字段新增/删除/类型变化、重复扫描、系统Schema拒绝、对象超限和文档完整性；
- 覆盖扫描成功、终态失败、瞬时失败重试、运行中任务重投、配置缺失和平台持久化失败；
- 覆盖扫描API幂等、快照/目录/diff查询、Outbox路由以及Worker只接收任务ID；
- Pytest共75项通过，总覆盖率90.10%；
- Ruff、Ruff Format和Mypy全量通过。

## 真实环境验收

- Alembic成功升级至`20260905_0004 (head)`；
- API、Worker和调度器保持非root运行，完整Compose栈健康；
- 真实API→Outbox→Celery→PostgreSQL→平台目录链路成功发布快照v1；
- 样例库结果为1个Schema、2张表、12个字段、6个约束和5个索引；
- 对`production_orders`临时增加字段后，第二次扫描成功发布快照v2；
- 差异接口仅返回1条预期新增字段记录，稳定键为`column/public/production_orders/m3_acceptance_marker`；
- 临时字段、验收用户、工作空间、数据源、密文、任务、快照和审计数据均已清理。

## 下一切片

实现MySQL连接、TLS与只读权限验证，输出相同`MetadataDocument`，并建立PostgreSQL/MySQL双数据库契约和真实集成测试。
