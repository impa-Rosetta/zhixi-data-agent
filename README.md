# 智析 Data Agent

A07 企业数据底座智能问析 Agent 系统。当前仓库处于 M0 工程基线阶段。

## 快速开始

1. 复制 `.env.example` 为 `.env`。
2. 执行 `docker compose up --build`。
3. 打开 Web：<http://localhost:5173>。
4. API 健康检查：<http://localhost:8000/health>。

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

