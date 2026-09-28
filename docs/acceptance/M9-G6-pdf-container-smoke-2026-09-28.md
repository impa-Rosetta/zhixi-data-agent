# M9-G6 当前代码镜像 PDF 渲染冒烟

日期：2026-09-28；源码提交`f17ef7d`。本轮只使用合成HTML，无业务数据、密钥、数据库或对象存储。Docker引擎版本28.4.0，现有Compose服务未启动，不把此次冒烟称为全链路验收。

1. Windows本机`.venv`直接调用`render_pdf`失败，稳定错误为`report.pdf_renderer_unavailable`，原因为缺少`libgobject-2.0-0`原生库。这是本机运行环境缺口，不能据此判定Linux部署失败。
2. 历史报告验收镜像`zhixi-report-verification:20260927-d4`在`--network none`下生成`%PDF-1.7`、3720字节；只证明历史镜像。
3. 从当前工作树以`apps/worker/Dockerfile`构建隔离镜像`zhixi-m9-verification:20260928-g5`，镜像ID`sha256:112ddbf9b3a4d94894f09717b4c21d31ff0025c6ecc4974897a3979ca7b9109f`。以`--network none --memory 512m --cpus 1`运行并调用当前代码的`render_pdf`，生成`%PDF-1.7`、3719字节；镜像用户`zhixi`、UID 999。另在无网络容器中成功导入Celery应用及报告、分析、评测三类任务模块。构建时当前提交无源码改动，Dockerfile只复制`apps`、`packages`和`evaluations`，不复制`.env`或文档。构建器未自动捕获Git提交元数据，因此镜像本身还没有可核验的revision标签。

边界：未验证真实Worker、MinIO、数据库、下载撤权、复杂中文排版、并发或新镜像部署。此镜像仍安装`WeasyPrint 66.0`，已知依赖安全告警尚未解决；不能作为正式发布镜像。`pip install .`依据版本范围在构建时重新解析依赖，而不是严格使用锁文件，正式构建的可复现性也未达标。
