# 安全一键启动与演示就绪检查验收记录

日期：2026-10-07
依据：`docs/superpowers/specs/2026-10-07-safe-demo-startup-design.md`

## 已完成的静态与隔离验证

- Windows PowerShell 5.1 下运行 `Invoke-Pester -Path tests/powershell/StartupReadiness.Tests.ps1`：9 项通过，0 项失败。
- 启动器、就绪模块、测试文件均通过 PowerShell AST 解析：0 语法错误。
- 本次涉及的已跟踪文件通过定向 `git diff --check`。仓库全局检查仍报告用户原有 M3 验收文档的一处行尾空格，本批未改动该文档。
- `scripts/check_secrets.py` 扫描通过，无高置信度凭据模式。
- 代码审查确认默认启动器不再调用 `docker-preflight.ps1 -Recover`；Compose 与状态查询均有界，关键服务未就绪不会打开网页。

## 真实栈验收限制

只读运行 `scripts/docker-preflight.ps1` 返回已知故障：检测到 `dockerInference` 和 `userAnalyticsOtlpHttp.sock` 瞬态套接字，Docker Engine 当前不可用。因此本轮**未执行真实 Compose 启动与浏览器端到端验收**。没有运行 `-Recover`、没有停止 Docker Desktop/WSL、没有移动目录或修改数据卷。待用户安排恢复 Docker 后，需补做一次正常栈启动与故障服务诊断的手工验收。
