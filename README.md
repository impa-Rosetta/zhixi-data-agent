# 智析 Data Agent

A07 企业数据底座智能问析 Agent 系统。项目已实现身份权限、PostgreSQL/MySQL 安全接入、版本化目录、质量语义模型、安全查询、持续会话、证据定位、可信图表和报告生成。M8 评测与高级建模仍按切片验收；受控建模 API 默认关闭，不能将代码存在等同于生产可用。各能力的最新完成边界、剩余验收和测试证据以[项目状态](docs/project-status.md)为准。

## 快速开始

1. 安装 Docker Desktop（Windows 请启用受支持的 WSL 2），确认 `docker info` 能返回 Engine 信息。
2. 将 `.env.example` 复制为本机 `.env`；示例密钥和密码仅供本地开发，不可用于公开部署。若要调用真实模型，在本机 `.env` 配置 `DEEPSEEK_API_KEY`，不要提交该文件。
3. 执行 `docker compose up -d --build`，再用 `docker compose ps --all` 确认服务状态。
4. 检查 API：<http://localhost:8000/health>；打开 Web：<http://localhost:5173>。全新平台请在 `/setup` 创建首个管理员和工作空间，仓库不提供预设登录账号。

GitHub 仓库不包含本机 `.env`、Docker 数据卷、已创建的账号或数据库中的演示会话；重新克隆不会自动恢复这些数据。模型密钥留空时，真实模型问析会明确失败，不会用模拟答案冒充成功。

### Windows 桌面一键启动

双击桌面的“智析 Data Agent”快捷方式，或运行仓库根目录的
启动智析DataAgent.cmd。启动器会检查并按需启动 Docker Desktop、构建并启动
Compose 服务，核对平台数据库、演示数据源、Redis、MinIO、Worker、迁移任务、
API 与 Web 的就绪状态，然后打开
<http://127.0.0.1:5173/app>。启动日志保存在
%LOCALAPPDATA%\ZhixiDataAgent\logs。若 Docker Engine 未就绪，启动器只提示
只读预检，不会自动重启 Docker、终止 WSL 或清理瞬态目录；已知故障的显式恢复
步骤见 `docs/runbooks/docker-desktop-recovery.md`。脚本不会保存登录密码或模型 API Key。

### Windows / Docker Desktop 故障排查

先区分“网页能打开”和“整套系统可用”：浏览器可能显示先前加载的页面，但 API、数据库或 Worker 已停止。一键启动器会检查关键服务、API 与 Web；若检查未通过，它不会打开网页。直接用 Compose 启动时，请自行核对服务状态。

| 现象 | 可能原因与只读检查 | 建议处理 |
| --- | --- | --- |
| Docker Desktop 一直显示启动中，`docker info` 无响应 | Engine/WSL 尚未就绪；运行 `wsl --version`，再运行 `./scripts/docker-preflight.ps1`。仅凭网页打不开不能判定是 Docker 故障。 | 查看 Docker Desktop 错误与诊断日志，核对 WSL 版本和虚拟化条件。Docker [WSL 说明](https://docs.docker.com/desktop/features/wsl/)建议保持 WSL 更新；不要直接重置或删除数据卷。 |
| 提示 `dockerInference` 或 `userAnalyticsOtlpHttp.sock` 无法访问 | 本项目在 Windows 上多次观察到 Engine 不可用且这些瞬态套接字存在；只读预检会报告检测结果，但“文件存在”本身不证明所有故障都由它造成。 | 先按[恢复说明](docs/runbooks/docker-desktop-recovery.md)核对条件。`-Recover` 是**单独的显式操作**，会中断 Docker Desktop 及其专用 WSL 实例；安排好其他容器任务后再执行。启动器不会自动执行。 |
| 5173 网页能打开，但登录、问析或报告失败 | API、Worker、PostgreSQL、Redis 或 MinIO 可能未就绪；查看 `docker compose ps --all` 和 <http://localhost:8000/health>。 | 按失败服务查看本机容器日志；不要把含凭据的完整日志公开上传。确认服务健康后重试，不要把 Web HTTP 200 当作全链路验收。 |
| 新克隆后无法使用原账号或历史数据 | `.env` 和 Docker 数据卷不随 Git 克隆；首次初始化与旧机器的状态彼此独立。 | 在 `/setup` 新建管理员；若需要迁移旧数据，使用经过验证的备份/恢复流程，而不是复制截图或重新克隆。 |
| 问析提示模型未配置或供应商连接失败 | `.env` 中模型密钥可能为空，或供应商网络不可用；查看安全错误码和 Worker 状态。 | 在本机配置有效密钥、检查网络与调用额度；不要把密钥写入 Git、问题单或截图。 |

Docker Desktop 的[官方排障文档](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/)提供日志与诊断入口。不要使用“Reset to factory defaults”作为常规修复；它会重置本机 Docker Desktop 状态。上述本机套接字现象不是对所有 Windows 安装的普遍故障判断。

## M1认证接口

- `GET /api/v1/auth/bootstrap-status`：判断平台是否已经初始化；
- `POST /api/v1/auth/bootstrap`：首次初始化平台；
- `POST /api/v1/auth/login`：登录；
- `POST /api/v1/auth/refresh`：轮换访问令牌和刷新令牌；
- `POST /api/v1/auth/logout`：撤销刷新会话；
- `GET /api/v1/auth/me`：当前用户与工作空间；
- `GET /api/v1/workspaces`：当前用户的工作空间；
- `POST /api/v1/workspaces/{workspace_id}/invitations`：创建一次性邀请；
- `GET /api/v1/workspaces/{workspace_id}/members`：成员查询；
- `PATCH /api/v1/workspaces/{workspace_id}/members/{membership_id}`：角色管理。

交互式接口文档：<http://localhost:8000/docs>。

## M2数据源安全配置

- `DATA_SOURCE_MASTER_KEYS`：JSON格式的版本化AES-256主密钥表，值为32字节Base64；
- `DATA_SOURCE_ACTIVE_KEY_VERSION`：新凭据使用的主密钥版本；
- `DATA_SOURCE_ALLOWED_PRIVATE_CIDRS`：允许连接的私网CIDR，默认生产配置应为空并按部署环境显式开放；
- `DATA_SOURCE_ALLOWED_PORTS`：允许的数据源端口，当前示例为PostgreSQL `5432`与MySQL `3306`。
- `METADATA_SCAN_MAX_OBJECTS`：单次元数据扫描允许发布的最大对象数，默认`10000`；超限时拒绝快照发布。

`.env.example`中的密钥和私网范围只用于本机Docker开发。生产部署会拒绝开发主密钥，并应采用独立随机密钥与最小CIDR白名单。

## M2数据源接口

- `POST /api/v1/workspaces/{workspace_id}/data-sources`：保存加密配置并异步测试；
- `GET /api/v1/workspaces/{workspace_id}/data-sources`：分页查询；
- `GET/PATCH /api/v1/workspaces/{workspace_id}/data-sources/{id}`：脱敏详情与乐观锁更新；
- `POST /api/v1/workspaces/{workspace_id}/data-sources/{id}/test`：幂等连接测试；
- `POST /api/v1/workspaces/{workspace_id}/data-sources/{id}/scans`：按Schema范围幂等投递元数据扫描；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/snapshots`：查询不可变快照版本；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/catalog`：读取当前或指定版本目录；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/diffs`：分页读取相邻快照的确定性结构差异；
- `GET/PUT /api/v1/workspaces/{workspace_id}/data-sources/{id}/sampling-policy`：读取或版本化更新默认关闭的表级采样授权与硬预算；
- `GET/PUT /api/v1/workspaces/{workspace_id}/data-sources/{id}/schedule`：读取或更新每日/每周IANA时区刷新计划；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/catalog/snapshots/{snapshot_id}/profiles`：读取快照字段画像与脱敏样例；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/catalog/snapshots/{snapshot_id}/profiles/{column_id}`：读取单字段画像；
- `POST /api/v1/workspaces/{workspace_id}/data-sources/{id}/disable|enable`：停用或重新测试；
- `DELETE /api/v1/workspaces/{workspace_id}/data-sources/{id}?version=...`：软删除并销毁密文；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/jobs`：数据源任务历史；
- `GET /api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}`：轮询真实任务状态。
- `POST /api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}/cancel`：协作式取消排队或运行中的任务；
- `POST /api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}/retry`：使用`Idempotency-Key`显式重试失败或取消的任务。

Compose中的`source-postgres`与`source-mysql`是本地只读集成样例，宿主机端口分别为`55432`和`53306`。二者只用于开发验收，不作为平台业务数据库或生产凭据示例。MySQL默认只扫描配置的数据库，不允许借助Schema范围跨库扩张扫描边界。

安全采样只接受已发布目录中的普通表，不接受用户SQL。每次任务冻结策略版本和表范围，并同时限制每表行数、每字段样例数、单值字符、表级字节、任务字节和语句超时。敏感或复杂字段失败关闭，敏感原值不会进入画像、任务参数、Outbox、审计或日志。可使用`scripts/accept_m5_live.py`在空的本地Compose平台库上执行双数据库真实闭环验收；管理员密码和样例源密码分别通过`M5_ADMIN_PASSWORD`、`M5_SOURCE_PASSWORD`环境变量提供。

## M5 Agent运行配置与接口

DeepSeek 通过供应商无关 Model Gateway 接入。生产和本地真实模型运行均需以部署 Secret 或环境变量 DEEPSEEK_API_KEY 提供密钥；禁止提交到 Git、写入数据库或输出到日志。默认模型为 deepseek-v4-pro，Base URL 为 https://api.deepseek.com。

- POST /api/v1/workspaces/{workspace_id}/analysis-runs：使用 Idempotency-Key 创建运行；
- GET /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}：读取可恢复状态、预算和结果引用；
- GET /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/events：按序读取运行事件；
- POST /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/messages：追加澄清消息；
- POST /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/confirm：确认或拒绝高影响计划；
- POST /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/cancel：幂等取消；
- POST /api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/retry：从可恢复失败继续。

没有配置模型密钥时，运行会明确进入 failed_retryable/model.not_configured，不会使用模拟答案冒充成功。M5 的正式验收见 docs/acceptance/M5-agent-core-overall-acceptance.md。

## 产品界面

- `/`：按平台状态自动进入首次初始化、登录或工作台；
- `/setup`：创建首个系统管理员和工作空间；
- `/login`：企业账号登录；
- `/invite?token=...`：接受一次性工作空间邀请；
- `/app`：受保护的Agent问析工作台；
- `/app/data`：数据源列表、PostgreSQL/MySQL安全接入向导与真实连接任务进度；
- `/app/data/:dataSourceId`：脱敏详情、Schema范围扫描、任务取消/重试、历史快照切换、Schema/表/字段/约束/索引浏览、确定性结构差异、安全字段画像、表级采样策略、时区刷新计划，以及配置编辑、复测、启停和受保护删除；
- `/app/semantic`：制造质量语义模型、指标口径、目录字段映射与不可变版本发布；
- `/app/members`：成员邀请和角色管理。

前端不会模拟 Agent 回答。正式问析工作台已接入 AnalysisRun 全生命周期、SSE 断线续传、真实结果、可信等级、Evidence、验证结论和默认折叠的脱敏技术详情。统计摘要和图表均从已验证查询产物派生，并通过受限 ChartSpec 防止任意脚本或未验证数据进入渲染层。报告编排与导出已有独立验收；建模与评测的开放范围和未完成事项请查阅[项目状态](docs/project-status.md)。

## 本地质量检查

```powershell
./scripts/quality.ps1
```

Windows 启动器的无 Docker 依赖回归测试：

```powershell
Invoke-Pester -Path tests/powershell/StartupReadiness.Tests.ps1
```

## 浏览器与真实链路验收

```powershell
$env:E2E_PASSWORD = '<demo-admin-password>'
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE = '<chrome-or-edge-executable>'
npm run test:e2e
```

A5错误矩阵通过`A5_ADMIN_PASSWORD`、`A5_READER_PASSWORD`和`A5_WRITER_PASSWORD`环境变量运行`python scripts/accept_a5_live.py`。密码只应存在于当前终端。详细操作见`docs/runbooks/m2-data-source-operations.md`，验收证据见`docs/acceptance/A5-m2-overall-acceptance.md`。

## 目录

- `apps/web`：React + TypeScript 前端；
- `apps/api`：FastAPI 服务；
- `apps/worker`：Celery Worker；
- `apps/sandbox`：受限分析执行服务占位；
- `packages`：Agent与数据领域包；
- `infra`：容器和数据库初始化；
- `docs`：设计、决策、计划和验收记录。
