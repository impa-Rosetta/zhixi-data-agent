# Docker Desktop 快速预检与已知故障恢复

## 每次开发前

运行：

```powershell
.\scripts\docker-preflight.ps1
```

健康时脚本立即返回，不做任何修改。

桌面一键启动器也只会按需启动 Docker Desktop；如果 Engine 在 5 分钟内仍
不可用，它会失败退出并提示运行上述只读预检，不会自动调用 `-Recover`。
Docker Compose 构建启动最多等待 20 分钟（`-NoBuild` 最多 5 分钟），随后
最多等待 5 分钟核对关键容器、API 和 Web。未就绪时不会自动打开网页；
启动日志位于 `%LOCALAPPDATA%\ZhixiDataAgent\logs`。

## 已知残留套接字

仅当脚本同时确认 Docker 引擎不可用，且检测到以下至少一个已知瞬态套接字时，运行恢复：

- `%LOCALAPPDATA%\Docker\run\dockerInference`；
- `%LOCALAPPDATA%\Docker\run\userAnalyticsOtlpHttp.sock`。

```powershell
.\scripts\docker-preflight.ps1 -Recover
```

恢复操作只处理 Docker Desktop 自身的瞬态运行目录：停止 Docker Desktop 相关进程、终止 `docker-desktop` WSL 发行版、把 `run` 目录重命名为带时间戳的备份并重启 Docker Desktop。它不删除镜像、容器、卷或项目数据库，也不终止普通 Ubuntu WSL 发行版。2026-09-09 的复现表明两个套接字可能依次阻塞启动，因此预检必须覆盖二者，不能只清理首个报错文件。

## 禁止项

- 不使用 Reset to factory defaults；
- 不删除 Docker 数据卷；
- 未命中已知错误时不使用 `-Recover`；
- 恢复后先运行 `docker info` 和 `docker compose ps`，确认引擎与现有服务状态。
