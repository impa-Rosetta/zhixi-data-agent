# A5 M2 数据治理控制台整体验收

- 验收日期：2026-09-07
- 结论：通过
- 范围：M2-04 数据源管理页面与 M2 切片六整体验收
- 部署入口：Web `http://127.0.0.1:5173`，API `http://127.0.0.1:8000`

## 产品结果

- PostgreSQL 与 MySQL 演示源均保持 `ready`，目录与画像数据可在产品界面浏览；
- 桌面 1440×1000 与移动端 390×844 的 Playwright 真实浏览器流程各通过 1 项；
- 数据源列表、详情、版本目录、结构差异、字段画像、采样策略、刷新计划、编辑、复测、启停和删除入口形成闭环；
- 凭据编辑字段始终为空，不从详情接口回显；页面根节点横向溢出不超过 1 像素；
- 移动端顶栏经过本轮视觉回归调整，不再挤压品牌、工作空间和用户操作区。

## 后端错误矩阵

可重复脚本：`scripts/accept_a5_live.py`。脚本只从环境变量读取本地验收密码，响应检查不会打印凭据，所有临时数据源通过 `finally` 清理。

| 场景 | 实际结果 |
|---|---|
| MySQL 错误密码 | `failed / connector.authentication_failed` |
| MySQL 含写权限账号 | `failed / connector.read_only_required` |
| Compose 网段不可达地址 | `failed / connector.connection_failed` |
| 旧版本配置写入 | HTTP `409 / data_source.version_conflict` |
| 软删除后同名重建 | 成功，生成不同资源 ID |
| 取消与幂等重试 | 自动化 API 测试通过 |

验收完成后查询结果为 `a5_active=0`；永久演示源仅保留“产品前端验收 PostgreSQL”和“产品前端验收 MySQL”。

## 数据库迁移与缺陷修复

真实错误矩阵发现软删除记录仍占用工作空间名称唯一约束。修复采用活动记录部分唯一索引：

- 迁移 `20260906_0006` 删除全量唯一约束；
- 新索引只对 `deleted_at IS NULL` 的记录保证 `workspace_id + name` 唯一；
- 活动同名创建返回稳定 `409 data_source.conflict`；
- 软删除后允许安全复用名称；
- 已在隔离 PostgreSQL 数据库完成 `0005 → 0006 → 0005 → 0006` 往返；
- Compose 真实库已升级至 `20260906_0006 (head)`。

## 供应链与安全门禁

- Python：`cryptography 50.0.1`、`pip 26.2.1`；`pip-audit --local --skip-editable` 为 0 个已知漏洞；
- Node：生产依赖与完整依赖 `npm audit` 均为 0 个已知漏洞；
- 新增高置信度秘密扫描，发现时只输出文件、行号和类别，不回显命中值；
- 既有测试令牌改为明确无效占位符，扫描规则未设置白名单；
- API、Worker、迁移镜像构建时先升级到 `pip>=26.2`；
- CI 固化 `npm ci`、依赖审计、秘密扫描、严格类型检查和 90% 后端覆盖率门槛；
- 用户提供的模型 API 密钥未写入文件、日志、命令、环境模板或 Git。

## 自动化与运行验收

- 后端：151 项测试通过，总覆盖率 90.57%；
- 前端：10 个测试文件、22 项测试通过；
- Ruff、Ruff format、严格 MyPy、ESLint、TypeScript、Vite 生产构建全部通过；
- Playwright：桌面与移动端共 2 项通过；
- Compose：API、Web、Worker、PostgreSQL、MySQL、Redis、MinIO 均健康，Scheduler 正常运行；
- HTTP：`GET /health` 返回 `status=ok`，Web 首页返回 200；
- 运行容器确认 `cryptography 50.0.1` 与 `pip 26.2.1`。

## 工具与主机故障记录

Windows UI 自动化工具初始化连续失败，错误为本地 kernel assets 路径缺失，因此按工具规则停止 UI 自动化，改用仓库内 Playwright 完成真实浏览器验收。

Docker Desktop 因陈旧 `dockerInference` AF_UNIX 临时端点无法启动。停止 Docker 专用进程后，将 `%LOCALAPPDATA%\Docker\run` 可恢复地重命名为 `run.stale-20260907-a5`，Docker 随后正常重建运行目录并恢复 Engine。未删除镜像、卷或数据库。

## 完成判定

M2-04 与 M2 切片六全部完成。M2 数据源与元数据里程碑达到产品级完成定义，下一阶段进入 B1：语义模型领域与迁移。
