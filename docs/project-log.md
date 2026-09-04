# 项目日志

## 2026-09-04：M0启动

- 依据已确认的产品设计和实施计划启动工程基线；
- 初始化Python/FastAPI、React/TypeScript、Celery、PostgreSQL、Redis和MinIO结构；
- 建立Docker Compose、迁移、健康检查、测试与CI基线；
- 当前阶段不实现业务功能，先验证开发与交付链路。

## 2026-09-04：M0验收通过

- 完成模块化单体API、独立Celery Worker、React Web及Sandbox边界骨架；
- 完成PostgreSQL + pgvector、Redis、MinIO、Alembic和Docker Compose一键启动；
- 数据库迁移作为启动前置任务自动执行，失败时API与Worker不会继续启动；
- 本地与容器生产构建、静态检查、单元测试和全栈健康检查全部通过；
- Docker Desktop启动异常由残留运行时套接字目录引起，已保留旧目录并重建临时运行目录，未清除镜像、容器或数据卷；
- 下一阶段按计划实施M1身份、工作空间与统一Policy Engine。

## 2026-09-04：M1身份与权限核心切片

- 实现平台初始化、登录、访问/刷新令牌、令牌轮换与退出撤销；
- 实现工作空间邀请、自助注册、成员列表、角色变更和五类角色；
- 建立默认拒绝的Policy Engine、跨空间隔离与管理员委派保护；
- 新增身份、成员、邀请、会话和审计数据表，真实PostgreSQL迁移通过；
- 单元及接口测试增至9项，后端覆盖率提升至91%；
- 发现并清理M0遗留的本地Uvicorn进程，Docker API现正确发布到8000端口。
