# M2 PostgreSQL连接闭环验收

- 状态：切片二通过
- 日期：2026-09-05
- 范围：数据源控制面、PostgreSQL Connector、异步连接测试与生命周期

## 已实现

- 工作空间管理员和数据管理员可创建、查询、更新、测试、启停和软删除PostgreSQL数据源；
- 数据源更新使用版本号进行乐观锁控制，连接测试支持`Idempotency-Key`；
- API契约禁止未知字段，规范化主机与名称，凭据只进入请求且不会出现在响应；
- 凭据整体加密保存，Outbox和Celery消息只包含任务ID；
- PostgreSQL连接按授权DNS结果设置`hostaddr`，建连后复核实际地址；
- 支持`disable`、`prefer`、`require`、`verify-ca`和`verify-full` TLS模式；
- 会话强制只读、连接超时5秒、语句超时10秒、锁超时5秒；
- 只读校验拒绝超级用户、建库/建角色/复制权限、数据库或Schema创建权限及业务表写权限；
- 认证、TLS、权限、超时、网络策略和内部错误使用稳定安全错误码；
- 瞬时错误指数退避且最多重试2次，认证、权限和配置错误不重试；
- 独立调度器周期投递事务Outbox，重复消息由任务终态短路；
- 停用/删除后的运行中任务不能恢复数据源，运行中测试阻止连接配置竞态更新。

## 自动化验收

- 数据源API覆盖完整生命周期、响应脱敏、权限、版本冲突、幂等和密文销毁；
- Worker领域测试覆盖成功、不可重试失败和可重试失败；
- PostgreSQL Connector模拟测试覆盖TLS、只读校验、DNS重绑定、CA临时文件清理和安全错误分类；
- Connector模块测试覆盖率95%；
- Pytest共53项通过，后端总覆盖率90%；
- Vitest共4项通过，全量Ruff、Mypy、ESLint和TypeScript生产构建通过。

## 真实环境验收

- Docker Compose新增独立`postgres:16.4-alpine`样例数据源；
- 初始化两张制造业样例表、主外键、约束、索引和有限测试数据；
- `zhixi_reader`只有连接、Schema使用和表查询权限；
- Connector直接连接结果：PostgreSQL 16.4、TLS关闭状态被准确识别、只读校验通过；
- 高权限`source_admin`被`connector.read_only_required`拒绝；
- 错误密码被`connector.authentication_failed`拒绝且不自动重试；
- 正式API创建后，Outbox自动发布、Worker消费并将任务更新为`succeeded/100%`、数据源更新为`ready`；
- 临时验收工作空间、用户、密文、任务、Outbox和审计数据在验证后清理。

## 运行安全

- API、Worker和调度器使用非root容器用户；
- Worker并发固定为2，避免连接测试挤占企业数据库；
- 样例数据库端口`55432`及其凭据只用于本地开发；
- 生产环境必须使用受信CA验证TLS、独立最小权限账户和精确私网CIDR。

## 下一切片

复用已验证连接器，扫描PostgreSQL Schema、表、视图、字段、主外键、索引和注释，生成不可变版本目录与确定性结构差异。
