# Sandbox service

M0仅保留服务边界。任意Python执行不会在API或Worker进程内开放；受限执行将在M8按独立容器、无网络、无数据库凭证和资源配额实现。

