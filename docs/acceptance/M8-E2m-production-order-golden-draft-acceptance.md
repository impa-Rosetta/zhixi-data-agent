# M8-E2m 生产工单指标扩展验收

- 日期：2026-09-27
- 范围：在已批准的 M8 离线黄金集方案中，将标准问题从质检主题扩展到合成生产工单主题。
- 结论：0.1.5 未发布草案共 28 条，真实合成 PostgreSQL 28/28，受权 API/Outbox/Worker 28/28；结果不是 DeepSeek 实测或 140 组正式黄金集。

## 案例与口径

1. 新版本保留 0.1.4 前 16 条不变，新增 12 条标准案例，覆盖 2025 年 10/12 月及 2026 年 1/3/7/9 月的计划产量和生产产量。问题包含“生产产量、实际产量、完工数量”和“计划产量、计划数量”等不同说法，检验语义别名绑定。
2. 生产工单的物理映射为 `production_orders.planned_quantity → production_order.planned_quantity`、`completed_quantity → produced_quantity`、`started_at → start_time`；工单编号映射 `order_no → order_id`。评测器只提供固定模型意图，数值由现有 Agent、语义编译、SQL 安全门禁、只读 PostgreSQL 查询和证据链产生。
3. 预期数值从合成 `public.production_orders` 直接聚合核对：六个月生产产量依次为 955、962、951、944、972、947 件，每月计划产量 1000 件。新版本数据集标识为 `synthetic-factory-source-init-quality-orders-v3`，明确区别于之前仅质检主题的草案。

## 验证

- 新增 12 条在隔离真实 PostgreSQL 12/12；完整 28 条 28/28，标准 21、多轮 1、歧义 1、异常 3、安全 2。机器可读结果见 `evidence/M8-E2m-2026-09-27-postgres-v0.1.5.json`。
- 产品 API 可发现 0.1.5、案例数 28，`live_enabled=false`。受权运行 `989de4c1-66ea-429c-ba6c-b41d95bf2a75` 经 Outbox 分发 1 项，Worker 完成 28/28；逐案例分页为 25＋3，全部通过。数据库记录本运行案例 28、模型调用 0、待分发评测事件 0。
- 源表未改变：质检表 24 条、检验量 4800、缺陷量 101；工单表 12 条、计划量 12000、完工量 11486；临时 `eval_*` schema 数 0。
- 后端全量 443 通过、1 条可选真实 PostgreSQL 测试因本地环境变量未设置而跳过；严格 MyPy、Ruff 通过。前端 ESLint、TypeScript、71 项测试及正式构建通过；构建仍提示部分图表代码块超过 500 kB，留待 M9 性能优化。本切片未修改前端页面。

## 未完成

0.1.5 仍为 `published=false`，团队人工审阅尚未完成；距批准规格的 60/20/20/20/20 共 140 条仍少 112 条。真实模型基准需单次预算授权，M8 可观测性、沙箱和 M9 产品加固与交付仍未完成。
