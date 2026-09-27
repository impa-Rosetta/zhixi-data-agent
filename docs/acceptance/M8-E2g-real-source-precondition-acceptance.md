# M8-E2g Docker 恢复与真实查询前置验收

- 日期：2026-09-27
- 状态：Docker 与独立 PostgreSQL 查询前置已恢复；不是四个 Agent 黄金案例通过

## 环境恢复

核对 Docker 的临时运行目录确切为 C:\Users\ROG\AppData\Local\Docker\run，命中既有 dockerInference 残留套接字后，执行已记录的可恢复方案。临时目录改名备份为 run.stale-20260927-100748，重新启动后 docker info 返回引擎版本 28.4.0。没有删除镜像、容器卷、项目数据库，也没有执行 factory reset 或终止普通 Ubuntu 发行版。

## 独立查询环境

新建合成 PostgreSQL 16.4 测试容器 zhixi-m8-eval-20260927，仅将端口 55433 绑定到 127.0.0.1，与现有项目演示库分离。只读挂载 infra/postgres/source-init.sql 初始化独立 factory_demo 数据库；初始化文件 SHA-256 为 75c9cd5883d9bceef5fb32be41807e88bea05f685806451747f44f663778fc97。

只读账号 zhixi_reader 的 superuser、createdb、createrole 与表 INSERT/UPDATE/DELETE 权限均为 false。独立网络 zhixi-m8-evaluation 为该库提供 source-evaluation 别名。生产连接器禁止回环地址的规则保持原样；真实执行在该独立容器网络完成，不修改生产网络授权逻辑。

新增 scripts/verify_evaluation_source.py，调用现有 validate_sql 和 execute_read_only，经实际 SQL AST 门禁与真实 PostgreSQL 只读事务读取合成数据，不使用替身查询执行器。固定校验逐行核对月份、缺陷数、检验数和不良率；额外行、重复月份、缺失、错误数字或截断均不能通过。

| 月份 | 缺陷数 | 检验数 | 不良率 |
|---|---:|---:|---:|
| 2026-07 | 7 | 400 | 1.75% |
| 2026-08 | 11 | 400 | 2.75% |
| 2026-09 | 12 | 400 | 3.00% |

实际生产门禁/只读执行器验证返回 passed，3 行，truncated=false。SQL门禁摘要：e4ae12bd0920cd175e2e33fade819b56471e8510772fae4c50c3f05f897ce3f9。

测试 Worker 使用现有镜像，仅只读挂载 apps、packages、scripts 三个代码目录，不挂载项目 .env 或其他团队材料。一次性校验容器退出后自动移除；独立测试数据库仍保留运行，供下一切片接入 Agent。

## 复验命令

在项目根目录、Docker 已恢复且上述独立库运行时：

```powershell
docker run --rm --network zhixi-m8-evaluation --mount "type=bind,source=$PWD\scripts,target=/app/scripts,readonly" --mount "type=bind,source=$PWD\packages,target=/app/packages,readonly" --mount "type=bind,source=$PWD\apps,target=/app/apps,readonly" --entrypoint python zhixi-data-agent-worker:latest -m scripts.verify_evaluation_source
```

该命令只查询独立测试库，不使用生产环境文件或调用模型供应商。使用的明文账号密码只属于 source-init.sql 中的公开合成夹具，不得用于生产。

## 代码验证与剩余

后端全量 Pytest：361 项通过；严格 MyPy（含两个评测脚本）：111 个源文件通过；变更范围 Ruff 通过。脚本测试覆盖合法 SQL、正确行、错误数值、空值、重复/缺失/多余行和截断。

本轮仅验证真实数据源、SQL安全门禁及只读执行器。尚未接入黄金案例的发布语义映射、同会话多轮执行和最终回答证据判分；原 E2f 报告的 1通过/4blocked 不改写为 5通过。M7.7 的 MinIO/Worker/中文PDF、M8真实模型基准及M9仍未完成。原有 M3 用户文档改动未纳入提交。
