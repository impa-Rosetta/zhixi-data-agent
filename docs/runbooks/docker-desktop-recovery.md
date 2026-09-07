# Docker Desktop 快速预检与已知故障恢复

## 每次开发前

运行：

```powershell
.\scripts\docker-preflight.ps1
```

健康时脚本立即返回，不做任何修改。

## 已知 `dockerInference` 残留套接字

仅当脚本同时确认 Docker 引擎不可用，且 `%LOCALAPPDATA%\Docker\run\dockerInference` 存在时，运行：

```powershell
.\scripts\docker-preflight.ps1 -Recover
```

恢复操作只处理 Docker Desktop 自身的瞬态运行目录：停止 Docker Desktop 相关进程、终止 `docker-desktop` WSL 发行版、把 `run` 目录重命名为带时间戳的备份并重启 Docker Desktop。它不删除镜像、容器、卷或项目数据库，也不终止普通 Ubuntu WSL 发行版。

## 禁止项

- 不使用 Reset to factory defaults；
- 不删除 Docker 数据卷；
- 未命中已知错误时不使用 `-Recover`；
- 恢复后先运行 `docker info` 和 `docker compose ps`，确认引擎与现有服务状态。
