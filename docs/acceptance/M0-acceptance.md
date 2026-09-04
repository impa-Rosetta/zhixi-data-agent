# M0 工程基线验收

- 状态：通过
- 日期：2026-09-04

## 验收项

- [x] API单元测试通过
- [x] 前端单元测试通过
- [x] Python静态检查通过
- [x] TypeScript与ESLint通过
- [x] 前端生产构建通过
- [x] Docker Compose配置校验通过
- [x] 数据库迁移可执行
- [x] API、Worker及依赖服务健康检查通过
- [x] `.env.example`与开发说明完整
- [x] 关键技术决策已更新

## 结果

M0工程基线验收通过。验证结果：

- Ruff、Mypy、Pytest、ESLint、TypeScript、Vitest及前端生产构建全部通过；
- Pytest共3项测试通过，当前覆盖率87%；前端Vitest共1项测试通过；
- `docker compose up -d --build`可从空数据卷自动执行Alembic迁移并启动完整服务栈；
- API `/health`返回200，Web首页返回200；
- PostgreSQL迁移版本为`20260904_0001`，Redis返回`PONG`，Celery Worker返回`pong`；
- PostgreSQL、Redis、MinIO、API与Worker健康检查均通过，迁移任务以退出码0完成。

说明：M0只验证工程与交付底座，不代表A07业务功能已经完成；下一阶段进入M1身份、工作空间与权限。
