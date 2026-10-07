# 安全的一键启动与演示就绪检查设计

日期：2026-10-07  
状态：待审阅  
范围：Windows 本地 `启动智析DataAgent.cmd`、`scripts/start-zhixi.ps1` 及其启动验收；不改变 Docker Compose 服务拓扑、业务 API 或数据。

## 1. 背景与目标

省赛演示期间曾出现 Web 端口仍可打开，而 API、平台数据库、Redis 和对象存储不可用的状态。现有启动器只在 `docker compose up` 返回后检查 API `/health` 与 `/app` HTTP 200；遇到 Docker Engine 无响应时，它还可能自动调用 `docker-preflight.ps1 -Recover`。该恢复会停止 Docker Desktop 进程、终止 `docker-desktop` WSL 发行版并移动 Docker 的瞬态运行目录，虽然不删除卷，但会影响本机其他容器任务。这与现有运维说明要求的“明确诊断、显式恢复”不一致。

目标是：一键启动仍可按需打开 Docker Desktop 和启动本项目 Compose 栈，但**默认绝不自动执行 Docker 故障恢复**；只有关键服务确实就绪才打开网页。失败时用户能在控制台和日志中看到具体阶段、服务和下一步，不会误以为系统已经可用。

## 2. 范围与非目标

本批覆盖：Docker Engine 有界等待、Compose 启动有界等待、服务状态核验、HTTP 就绪核验、可操作的失败提示、启动器回归测试与运维说明同步。

本批不覆盖：修复 Docker Desktop 自身、自动重启 WSL 或删除/移动任何 Docker 文件、修改业务数据库、伪造 Agent 回答、改动 Web 页面、修改生产部署方式。用户若决定执行已知套接字恢复，仍须独立、显式运行 `scripts/docker-preflight.ps1 -Recover`，先阅读其影响说明。

## 3. 用户流程

1. 用户双击桌面快捷方式或运行 `启动智析DataAgent.cmd`。
2. 启动器获取单实例锁并检查 `docker.exe`、`compose.yaml`。
3. 若 Engine 未响应，仅在 Docker Desktop 尚未运行时启动其程序；最多等待 300 秒，每次 Engine 探测限时 5 秒。超时则停止本启动流程，提示查看 Docker Desktop 错误和运行只读预检；**不调用 `-Recover`**。
4. Engine 可用后，在项目目录执行 `docker compose up -d` 或 `docker compose up -d --build`。`-NoBuild` 最多等待 5 分钟，构建启动最多等待 20 分钟；超时或非零退出时停止后续动作并记录命令阶段和退出状态。
5. 启动器读取 Compose 服务状态，确认本演示依赖的 `postgres`、`source-postgres`、`source-mysql`、`redis`、`minio`、`api`、`worker`、`scheduler`、`web` 正常；`migrate` 必须成功完成。带 healthcheck 的服务必须为 healthy，未定义 healthcheck 的 `scheduler`、`web` 至少为 running。
6. 同时确认 API `/health` 返回 HTTP 200 且 JSON `status=ok`，Web `/app` 返回 HTTP 200。每 3 秒检查一次，最长等待 5 分钟；单次 HTTP 请求限时 4 秒。
7. 只有全部就绪且未指定 `-NoBrowser` 时打开网页；否则输出失败服务/阶段与日志位置，不打开网页。

## 4. 组件与接口

### 4.1 启动器

保留现有 `-NoBuild`、`-NoBrowser` 参数和桌面快捷方式入口。把 Docker Desktop 的“启动”与“恢复”严格分开：前者是正常启动路径，后者只由人工显式调用预检脚本。启动器不新增隐含恢复开关。

外部命令均使用受控子进程和超时；超时后只结束本次启动器创建的子进程树，不按名称杀掉全部 Docker Desktop 或其他任务。日志保留时间、阶段、退出码、服务名与状态，不写 `.env`、凭据、模型密钥或完整环境变量。

### 4.2 Compose 状态适配

通过 `docker compose ps --all --format json` 获取服务状态。适配层兼容单个 JSON、逐行 JSON 和 JSON 数组形式，并把缺失服务、非运行状态、health 非 healthy、`migrate` 非成功退出分别归一为稳定的诊断代码。若命令本身不可用或输出不可解析，视为检查失败，不能静默跳过。

### 4.3 HTTP 就绪检查

API 检查响应体中的 `status`，不仅依赖 HTTP 200；Web 检查 `/app` HTTP 200。每次轮询同时记录最新 Compose/HTTP 状态，最终失败仅输出可读的摘要，不把每次重试刷屏。该检查代表本地演示栈就绪，不宣称外部模型供应商或企业数据源必然可用。

## 5. 失败处理与安全边界

| 阶段 | 条件 | 结果 |
| --- | --- | --- |
| Docker 检查 | Engine 超时或 CLI 出错 | 失败退出；提示只读预检与 Docker Desktop 错误界面；不恢复、不重置 |
| Compose 启动 | 非零退出或超时 | 失败退出；记录阶段与安全摘要；不打开网页 |
| 服务就绪 | 必需服务缺失、退出或不健康 | 等待至期限；报告服务名、状态、健康状态 |
| HTTP 就绪 | API/Web 未通过 | 等待至期限；报告具体端点，不声称可演示 |
| 用户取消 | 关闭窗口或中断 | 不移动 Docker 文件、不删除数据卷 |

`docker-preflight.ps1 -Recover` 保持独立操作，继续保留已知故障的只读条件检查与可恢复备份；本批不扩张它的恢复对象。

## 6. 测试与验收

- 使用隔离的假 `docker.exe`/Compose 输出和本地假 HTTP 响应测试启动器，不要求测试机运行 Docker Desktop。
- 覆盖：Engine 不可用时不触发恢复；Docker Desktop 已运行时不重复启动；Compose 失败/超时；缺失或不健康服务；`migrate` 失败；API 虽为 200 但 `status` 非 `ok`；全部就绪且 `-NoBrowser` 时成功退出。
- 对状态解析单独覆盖 Compose 的逐行 JSON 与数组 JSON，禁止解析失败时误判成功。
- 在有健康本地栈时执行一次手工端到端验收：启动器显示就绪，API 与 Web 可访问，浏览器按参数打开；断开某个关键服务后再次启动应给出准确失败诊断。
- 运行适用的脚本语法/静态检查和现有项目质量检查，记录无法执行的环境依赖。测试不得使用真实密码，不能调用恢复、重置或清理命令。

## 7. 完成标准

1. 默认启动路径没有任何 `-Recover`、Docker 进程强制停止、WSL 终止或 Docker 运行目录移动行为。
2. 关键服务未就绪时启动器返回非零、不给用户打开“看似可用”的网页，并提供定位信息。
3. 正常栈从快捷方式可一键启动；`-NoBuild`、`-NoBrowser` 行为不回退。
4. 自动化回归覆盖关键成功、失败和安全分支，运维文档与脚本行为一致。

## 8. 自检

本规格只承诺本机演示栈的可用性检查；不把 `/health` 等同于模型调用成功，不把真实数据源连接可用性隐含在 Web 200 中。恢复操作仍由用户显式触发。项目现有未提交的 M3 文档和省赛材料均不属于改动范围。
