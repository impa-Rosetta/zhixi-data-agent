# M4 MySQL连接器与双数据库兼容验收

- 状态：通过
- 日期：2026-09-05
- 范围：MySQL安全连接、元数据扫描、跨方言目录契约和真实版本差异

## 已实现

- 运行依赖采用`PyMySQL>=1.1,<2`，开发环境加入匹配的严格类型桩；
- `MySQLConnector`完整实现既有连接测试与元数据扫描协议，控制面不包含方言分支；
- DNS解析后仅连接网络策略授权IP，TLS握手仍使用原始主机名完成SNI和可选身份校验；
- 支持`disable/prefer/require/verify-ca/verify-full`五种TLS策略，强制模式会复核真实TLS状态；
- 会话设置连接、读取、写入、查询与锁等待超时，并在元数据查询前启动只读事务；
- 只读验证覆盖全局、库、表和列级直接授权，仅接受`USAGE/SELECT/SHOW VIEW`；带`INSERT`等写权限的账户不能进入就绪状态。当前对启用MySQL角色的账户默认拒绝，避免未展开角色权限时产生安全绕过；
- 扫描配置database内的表、视图、字段、默认值、注释、主外键、唯一/检查约束和索引；
- MySQL类型映射到方言无关类型；系统库和跨database扫描范围被拒绝；
- PostgreSQL与MySQL对等结构通过同一`MetadataDocument`验证、对象计数和可移植签名契约。

## 真实环境验收

- 使用固定的MySQL 8.4.11 LTS官方镜像和独立`factory_demo`样例数据源；
- 只读账户通过TLS强制连接，服务器版本、TLS状态和最小权限验证正确；
- 错误密码稳定映射为`connector.authentication_failed`；
- 带`INSERT`权限账户稳定映射为`connector.read_only_required`；
- 真实扫描识别1个Schema、3个关系、16个字段、6个约束和5个索引；
- 完整API→Outbox→Celery→MySQL→目录链路成功发布快照v1；
- 临时新增`production_orders.m4_acceptance_marker`后发布快照v2，共17个字段；
- 相邻快照产生且仅产生1条Diff，稳定对象键为`column/factory_demo/production_orders/m4_acceptance_marker`；
- 验收字段、用户和工作空间均已清理，平台数据库无临时租户残留。

## 失败与质量门禁

- 单元测试覆盖TLS缺失、写权限、认证/权限/TLS/超时/断连错误映射、跨库范围和对象超限；
- 跨方言契约测试覆盖相同结构的可移植字段类型、约束、索引与对象计数；
- 全量后端测试共98项通过，总覆盖率90.32%；
- Ruff、格式与严格Mypy通过，前端Lint、4项测试和生产构建通过；
- Compose配置校验、固定版本MySQL容器健康检查和完整服务镜像构建通过。

## 下一切片

实现授权式安全采样、敏感字段识别、有限画像和定时刷新；所有画像绑定具体目录快照，默认不采集原始业务数据。
