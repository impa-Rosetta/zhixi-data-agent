# 智析 Data Agent

A07 企业数据底座智能问析 Agent 系统。M0工程基线已验收，当前开发M1身份与权限。

## 快速开始

1. 复制 `.env.example` 为 `.env`。
2. 执行 `docker compose up --build`。
3. 打开 Web：<http://localhost:5173>。
4. API 健康检查：<http://localhost:8000/health>。

## M1认证接口

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
