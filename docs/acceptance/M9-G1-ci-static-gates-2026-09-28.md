# M9-G1 完整CI静态门禁收敛（未关闭）

日期：2026-09-28。此切片修复原有GitHub CI命令暴露的历史脚本缺陷；不缩减检查路径或降低阈值。

## 修改

- 对`apps packages tests scripts`按项目当前Ruff规则统一格式；修复文稿生成脚本的超长行和导入顺序，不改变文稿文字。
- 将文稿脚本实际使用的`python-docx==1.2.0`加入开发依赖与锁文件，避免CI只安装`.[dev]`时找不到模块。采用官方[PyPI发布页](https://pypi.org/project/python-docx/)核对版本。
- 为文稿脚本加具体的Word对象类型，纠正`Document`工厂被误用作类型、`Path`与`save`参数不匹配，以及报告验收脚本的HTTP响应变量复用；渲染夹具的时间戳改为显式UTC `datetime`。未改变业务输出或安全边界。

## 实际复验

- `ruff check apps packages tests scripts`：通过。
- `ruff format --check apps packages tests scripts`：223个文件通过。
- `mypy apps packages scripts --strict`：154个源文件通过。
- `scripts/check_secrets.py`：通过。
- 后端`pytest`：通过；覆盖率命令总覆盖85.75%（10161条语句中1448未覆盖），低于CI规定90%，明确失败。需补足关键路径测试，不能修改阈值替代测试。
- 前端lint、typecheck、build通过；全量Vitest一次为70/71，图表测试触发5秒超时与jsdom canvas告警；该测试文件单独重跑7/7通过。尚未证明全量运行稳定，需排查测试环境和并发。
- 停止并发的后端覆盖率任务后，前端全量Vitest重跑71/71（20个测试文件）通过；首次超时仍保留为历史记录，不据一次复跑宣称并发稳定性已证明。
- 覆盖率缺口集中于真实PostgreSQL草案适配器185行、查询服务90行、报告渲染54行、模型网关51行、语义服务49行、查询执行器43行等。下一步针对关键逻辑补真实断言测试，不删文件或下调90%门槛。
- Compose配置校验通过，前端生产依赖`npm audit --omit=dev --audit-level=high`报告0项；未因此推断镜像构建或生产部署通过。
- 后端依赖审计未通过：本地`pip-audit --local --skip-editable`对`WeasyPrint 66.0`报告5条告警（输出含重复条目）。其中上游[安全公告](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-r543-q48m-4c9j)确认`<=69.0`受影响，`>=70.0`修复；需要先升级并重跑PDF回归及依赖审计。尚未升级，不能称安全门禁通过。

未重新完成Compose构建、空环境部署及真实浏览器验收；不能称整条CI绿或M9完成。历史用户M3文档及中间证据未改动。
