# ADV-A4：高级分析真实源、持续会话、报告与浏览器联合验收

日期：2026-09-28。第一批 Pearson/Spearman/IQR 主链路联合验收通过；不代表六算法建模、完整 C4 或全项目完成。

## 实测中修复的问题

1. `conversation_runtime._previous_intent_run` 未纳入 correlation/anomaly_detection，导致方法续问与解释被误判为新主题。补齐分析类型，保留原有主题切换规则。
2. 完成后的上下文原先选择最新产物，可能选择 chart_spec 而非 query_result，解释时无法通过可信查询读取器。高级分析上下文现在固定引用查询产物，解释重新授权并重算派生结果，不放宽证据校验。

新增四项回归，先在旧代码上全部失败，修复后通过；覆盖两类分析的 refine/explain 以及后生成图表不覆盖可信来源引用。

## 隔离环境与真实执行范围

- Compose 项目仅 `zhixi-advanced-acceptance`：独立 PostgreSQL 平台/源库、Redis、MinIO、API、Worker、Beat、Web。源/平台/对象存储为临时内存数据，未操作主业务数据库和卷。
- API、Worker、Web 从基线 `14d9353544b9dd81a2d1efa8d13c1b20773171cb` 构建并标注 revision；本次会话修复文件只读挂载到验收进程。此记录不声称镜像标签已经包含随后提交的补丁。
- 平台空库迁移到 0014；真实 PostgreSQL 目录扫描和语义发布；独立 advanced_fixture schema，12 天模拟检验数据，最后一天人为设置不良率 60、返工率 55。
- 对话创建/续问调用现有领域服务；分析执行使用实际 Worker 运行时及生产 SQL 执行器，不模拟查询和计算。意图响应为固定离线协议，不经过 Celery 分发分析任务，不能宣称真实 DeepSeek 理解能力或其准确率。
- 报告通过真实登录和 HTTP 创建，经 Outbox/Redis/Celery Worker 生成，保存至 MinIO；HTTP 下载 Markdown、HTML、PDF。付费模型调用为零。

验收过程中只重建了上述临时平台/源容器，失败尝试的模拟数据不可恢复，正式业务数据未删除。不会将这种临时库重建用于日常服务启动。

## 数值和五轮验证

同一会话 `3fb7361f-755f-49af-aabc-c7a7a6fd75bc`：

1. 按天分析不良率与返工率相关性：12 条真实 SQL 结果，Pearson 与 Python statistics 独立结果误差小于 1e-12。
2. 改用 Spearman 重新计算：真实重查与重算，系数 1.0。
3. 解释这个结果：保留相关性上下文，重新校验来源并解释，不编造因果。
4. 新主题：按天检查不良率异常：IQR 下界 -3.5、上界 18.5，唯一候选值 60。定位按 SQL 结果的实际排序验证，不假设第 12 行。
5. 解释这个结果：保留异常上下文并复核结果。

五轮均 completed；三个查询均 12 行且未裁剪。报告 `72d25313-ed2a-4812-940f-f93a9c93e8dd` succeeded，attempt_count=1。三种格式均真实下载，HTML 包含静态 SVG 和红色异常点，PDF 具有有效文件头。

桌面和移动浏览器下载的 PDF SHA256 均为 `cd93e534fcff96e7a4fce6e3931b326d7475196dbf84926a59196540f9b220cb`。

## 浏览器验证

Playwright 使用已安装 Chrome，连接独立 Web 58142/API 58141，不拦截 API。桌面 1440×1000 和手机 390×844 两项均通过：

- Pearson/Spearman 两张结果卡、IQR 候选和真实绘制的三张 SVG 图表可见；
- 报告 iframe 的真实 SVG 至少 24 个散点及唯一红色异常点；
- PDF 实际下载成功；刷新后分析记录及底部续问输入框仍存在；
- 页面无横向溢出。

截图保存在 `test-results/playwright`，为本地验收产物，没有上传用户会话内容。截图工具受本机权限辅助进程异常影响，未完成额外人工式图片布局复核；可见性与几何检查以实际浏览器断言为准。

## 可重复验收

脚本 `scripts/accept_advanced_stack.py` 仅允许独立平台 URL、固定源主机，拒绝已有 fixture 和配置付费模型的环境。执行前须保留正式服务，并只在上述独立 Compose 项目建立干净的临时环境。

1. 设置 ADVANCED_ACCEPTANCE_REVISION 为当前 Git SHA；构建独立 Compose 的三个镜像，启动平台/源/Redis/MinIO/API/Web/Beat，不启动 Worker；空库执行 alembic upgrade head。
2. 使用 api-advanced 服务 run --rm --no-deps，设置 PYTHONPATH=/app，将本脚本只读挂载至 /tmp/accept_advanced_stack.py 并运行。
3. 脚本输出 report_id 后，在另一终端启动该项目 worker-advanced；脚本等待最多 50 秒并校验三格式下载。
4. 设置 E2E_BASE_URL 为 http://127.0.0.1:58142、ADVANCED_CONVERSATION_ID 为脚本输出 ID、E2E_EMAIL 为 evaluation@example.test、E2E_PASSWORD 为脚本中的独立模拟密码，运行 playwright test advanced-analysis.spec.ts。

脚本因失败留下模拟数据时不得改指向正式库绕过拒绝；仅核对独立项目标签和 tmpfs 后重建该项目的模拟平台/源容器。

## 门禁与剩余项

- 后端：736 通过，1 个需另行设置 PostgreSQL 环境的集成测试跳过；覆盖率 90.43%。
- Ruff、严格 MyPy、前端 lint/typecheck 通过；前端生产代码本批未改，已有 99 测试全绿及构建通过。
- 新增浏览器专项 2/2 通过；远端 CI 以本批提交实际运行结果为准，不用上一次全绿替代。

第一批真实 SQL/数学计算/图表/多轮/报告主链路已补齐。六算法训练和推理、隔离建模代理、模型版本、训练确认与模型报告仍未实现；真实 LLM 验收、未知数据源、任意脚本沙箱、正式性能/灾备和最终材料仍是独立缺口。
