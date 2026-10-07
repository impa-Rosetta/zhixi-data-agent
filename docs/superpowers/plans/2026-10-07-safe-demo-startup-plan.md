# 安全的一键启动与演示就绪检查实施计划

依据：`docs/superpowers/specs/2026-10-07-safe-demo-startup-design.md`（用户已确认）。

1. 为 Compose 状态解析与就绪判定编写 Pester 回归测试：覆盖 JSON 数组/逐行对象、缺失服务、非健康状态和迁移失败。先运行并确认失败。
2. 增加纯函数启动就绪模块，输出稳定的 `Ready/Issues` 结构；运行上述测试直至通过。
3. 为启动器编写安全分支检查：默认流程不得调用 `-Recover`，Compose 与状态查询必须有界；实现受控命令运行、Docker Desktop 只启动不恢复、服务及 HTTP 双重检查。
4. 更新 Windows 启动与 Docker 恢复运维说明，明确何时需人工运行只读预检及显式恢复；不修改已有报告材料。
5. 运行 Pester、PowerShell 语法检查、相关静态检查与有条件的本地真实栈验收；记录无法在当前环境执行的项目。

安全约束：不调用 Docker 恢复、WSL 终止或清理命令；不打印 `.env` 内容；仅修改本计划对应的脚本、测试、README 与 runbook。
