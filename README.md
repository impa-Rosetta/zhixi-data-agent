# 智析 Data Agent

A07 企业数据底座智能问析 Agent 系统。M0工程基线与M1身份、权限及企业工作台已验收；M2已完成数据源安全底座、PostgreSQL/MySQL双连接器与版本化元数据目录。

## 快速开始

1. 复制 `.env.example` 为 `.env`。
2. 执行 `docker compose up --build`。
3. 打开 Web：<http://localhost:5173>。
4. API 健康检查：<http://localhost:8000/health>。

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
- `POST /api/v1/workspaces/{workspace_id}/data-sources/{id}/disable|enable`：停用或重新测试；
- `DELETE /api/v1/workspaces/{workspace_id}/data-sources/{id}?version=...`：软删除并销毁密文；
- `GET /api/v1/workspaces/{workspace_id}/data-sources/{id}/jobs`：数据源任务历史；
- `GET /api/v1/workspaces/{workspace_id}/scan-jobs/{job_id}`：轮询真实任务状态。

Compose中的`source-postgres`与`source-mysql`是本地只读集成样例，宿主机端口分别为`55432`和`53306`。二者只用于开发验收，不作为平台业务数据库或生产凭据示例。MySQL默认只扫描配置的数据库，不允许借助Schema范围跨库扩张扫描边界。

## M1产品界面

- `/`：按平台状态自动进入首次初始化、登录或工作台；
- `/setup`：创建首个系统管理员和工作空间；
- `/login`：企业账号登录；
- `/invite?token=...`：接受一次性工作空间邀请；
- `/app`：受保护的Agent问析工作台；
- `/app/members`：成员邀请和角色管理。

前端不会模拟尚未实现的Agent回答。数据接入、语义模型和Agent执行将在后续里程碑按真实纵向切片开放。

## 本地质量检查

```powershell
./scripts/quality.ps1
```

## 目录

- `apps/web`：React + TypeScript 前端；
- `apps/api`：FastAPI 服务；
- `apps/worker`：Celery Worker；
- `apps/sandbox`：受限分析执行服务占位；
- `packages`：Agent与数据领域包；
- `infra`：容器和数据库初始化；
- `docs`：设计、决策、计划和验收记录。
