# M2 数据源运维手册

## 适用范围

本手册覆盖 PostgreSQL/MySQL 数据源接入、连接验证、元数据扫描、版本目录、字段画像、采样与刷新策略、生命周期管理、故障处理和验收。生产环境只允许最小权限只读账号。

## 启动与升级

1. 从 `.env.example` 复制本地配置；生产环境必须替换主密钥、口令和私网白名单。
2. 执行 `docker compose up -d --build`。Compose 会先运行 Alembic 迁移，迁移成功后才启动 API、Worker 和 Scheduler。
3. 执行 `docker compose ps`，确认 API、Web、Worker、PostgreSQL、Redis、MinIO 和两个样例源健康。
4. 执行 `docker compose exec -T api alembic current`，确认数据库位于预期 head。
5. 检查 `http://127.0.0.1:8000/health` 与 `http://127.0.0.1:5173`。

升级前应备份平台 PostgreSQL 数据卷和 `DATA_SOURCE_MASTER_KEYS`。不要在没有备份的生产库直接执行 downgrade。

## 数据源日常操作

1. 以数据管理员或更高角色进入“数据管理”。
2. 新建数据源时选择 PostgreSQL 或 MySQL，填写地址、数据库、TLS 和只读账号。
3. 创建后观察真实连接任务；只有只读验证成功才进入 `ready`。
4. 在详情页选择业务 Schema 发起扫描。系统 Schema、任意 SQL 和跨库扩张均不接受。
5. 从不可变快照浏览 Schema、表、字段、约束和索引，并比较相邻版本差异。
6. 采样默认关闭。确需画像时只授权当前目录中的普通表，并设置行数、样例、字符、字节和超时预算。
7. 刷新计划使用 IANA 时区；保存后核对后端计算的下次执行时间。
8. 编辑凭据时只填写新值；平台从不回显现有账号或密码。
9. 停用会阻止新任务。启用会重新验证连接。删除为软删除并销毁密文，需要精确名称确认。

## 任务控制

- 排队或执行中的任务可请求取消；取消是协作式的，任务在安全检查点终止。
- 失败或已取消任务可显式重试，并必须提供 `Idempotency-Key`。
- 相同幂等键重复提交返回同一任务，防止重复扫描。
- 配置更新使用版本号；旧版本写入返回 `409 data_source.version_conflict`，客户端应刷新后重试。

## 常见错误码

| 错误码 | 含义 | 处置 |
|---|---|---|
| `connector.authentication_failed` | 账号或密码错误 | 轮换凭据并重新测试 |
| `connector.read_only_required` | 账号具备写权限 | 新建最小权限只读账号 |
| `connector.connection_timeout` | 连接超时 | 检查网络、DNS、防火墙和端口 |
| `connector.connection_failed` | 连接失败或目标不可达 | 检查地址、允许 CIDR、TLS 和服务状态 |
| `data_source.version_conflict` | 客户端版本过期 | 刷新详情后重新提交 |
| `data_source.conflict` | 活动数据源名称重复 | 使用不同名称或处理现有活动记录 |
| `scan_job.worker_lost` | Worker 失联且恢复耗尽 | 检查 Worker/Redis 后显式重试 |

## 本地质量与真实验收

完整本地门禁：

```powershell
./scripts/quality.ps1
```

真实 A5 错误矩阵通过环境变量传入本地演示密码：

```powershell
$env:A5_ADMIN_PASSWORD = '<demo-admin-password>'
$env:A5_READER_PASSWORD = '<sample-reader-password>'
$env:A5_WRITER_PASSWORD = '<sample-writer-password>'
python scripts/accept_a5_live.py
```

浏览器验收：

```powershell
$env:E2E_PASSWORD = '<demo-admin-password>'
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE = '<chrome-or-edge-executable>'
npm run test:e2e
```

以上变量只设置在当前终端，不应写入仓库。验收脚本会清理临时数据源。

## Docker Desktop 陈旧套接字恢复

若 Windows 报错指向 `%LOCALAPPDATA%\Docker\run\dockerInference` 且普通重启无效：

1. 停止 Docker Desktop 进程和 `docker-desktop` 专用 WSL 实例；
2. 确认 `run` 目录只包含 Docker 临时套接字；
3. 将整个 `run` 目录重命名为带时间戳的 `run.stale-...` 备份，不要删除；
4. 重新启动 Docker Desktop，确认 Engine 管道与 `docker info` 恢复；
5. 项目稳定运行后再决定是否清理备份目录。

不要使用“恢复出厂设置”处理此问题，因为它可能删除本地镜像、容器和卷。

## 安全边界

- 模型 API 密钥、数据库密码和主密钥只通过环境变量或部署 Secret 注入；
- 不在问题描述、日志、截图、验收结果或 Git 中保存秘密；
- 数据源凭据使用版本化 AES-256 主密钥加密，读取路径默认脱敏；
- 网络策略、只读验证、目录白名单与任务预算均在后端执行，前端不是安全边界；
- 发现疑似秘密时运行 `python scripts/check_secrets.py`，工具只报告位置与类型。
