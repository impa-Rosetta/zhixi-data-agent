# M4 查询安全与执行整体验收

- 日期：2026-09-07
- 迁移：`20260907_0008 (head)`
- 状态：通过

## 已验收能力

- 严格语义查询协议覆盖指标、维度、过滤、时间粒度、排序、行上限与上一周期比较；
- 编译器从不可变已发布语义版本和活动目录快照解析确认映射，生成 PostgreSQL/MySQL 参数化 SQL；
- 支持可聚合指标、ratio-of-sums、Top N、时间趋势、上一周期窗口比较和受治理关系连接；跨粒度一对多混合指标在预聚合能力上线前失败关闭，避免 fan-out 重复累计；
- SQLGlot 安全引擎只接受单条只读 Query，限制连接和子查询预算，并按目录对象白名单提取依赖；
- 多语句、写 CTE、DDL/DML、系统 Schema、危险函数、跨库、未授权表、递归 CTE、CROSS JOIN 和无条件 JOIN 均拒绝；
- 执行器 API 只接收持久化短时有效的 `validated_query_id`，目录版本变化或凭证过期后必须重新验证；
- PostgreSQL/MySQL 执行均复用 DNS/端口/私网策略、连接后地址复核、TLS、只读事务、10 秒超时和结果行硬上限；
- 敏感画像字段在结果层统一遮罩，证据固化查询摘要、结果摘要、目录快照、语义版本、依赖对象、信任标签与执行时间；
- 查询实验室明确区分“可信语义查询”和“探索 SQL”，展示验证凭证、SQL、依赖、结果及证据历史。

## 自动化证据

- 后端 Ruff、严格 MyPy 通过；
- 后端 173 项全量测试通过，其中 M4 查询协议、双方言编译器和攻击矩阵及API门禁 20 项；
- 前端 TypeScript、ESLint、23 项 Vitest 与生产构建通过；
- Playwright 桌面 Chrome 真实登录、探索 SQL 验证、ID 执行、结果与证据页面验收通过，无水平溢出；
- 容器内 Alembic 当前版本确认为 `20260907_0008 (head)`。

## 真实数据库证据

| 数据源 | 关系 | 验证 | 执行 | 返回 | 证据摘要前缀 |
|---|---|---|---|---:|---|
| MySQL | `factory_demo.order_quality_summary` | exploratory/approved | succeeded | 2 行 | `6809c2b7825510ce` |
| PostgreSQL | `public.production_orders` | exploratory/approved | succeeded | 2 行 | `8d071c51112fc382` |

验收过程中未向 API 传递数据库明文凭据，执行请求只传验证 ID；数据库凭据只从既有信封密文运行时加载。
