# M9-G11 后端覆盖率缺口审计（未关闭）

日期：2026-09-28。源码基线：`fe127ce`。读取本地 `.coverage`（最后写入 2026-09-28 12:53），本轮未重新执行全量测试；数值沿用 M9-G8 的 538 通过、1 跳过、87.69% 原始结果，`coverage report` 整数显示为 88%。

## 门禁差距

CI 命令为 `pytest --cov=apps --cov=packages --cov-report=term-missing --cov-fail-under=90`。当前 10,164 条可计语句、1,251 条未覆盖，即覆盖 8,913 条；按不减少语句总数估算，达到 90% 至少还需覆盖 235 条。不能通过降低阈值、排除高风险模块或只跑局部测试宣布通过。

| 模块 | 当前覆盖 | 未覆盖语句 | 后续验证重点 |
|---|---:|---:|---|
| `packages/evaluation/postgres_draft_adapter.py` | 45% | 185 | PostgreSQL 合成案例全流程、失败与清理；目前很多实际部署验收在 CI 覆盖率之外 |
| `apps/worker/tasks/evaluations.py` | 0% | 39 | 禁用环境、非法/非离线任务、版本漂移、失败归档、恢复任务 |
| `apps/worker/tasks/analysis_runs.py` | 0% | 17 | 模型网关装配、运行、会话同步与事务边界；测试必须替代实际付费调用 |
| `apps/api/routes/analysis_conversations.py` | 54% | 36 | 授权、持续追问、撤权与错误响应 |
| `apps/api/routes/analysis_runs.py` | 61% | 37 | 执行、取消、结果与 Evidence 的 HTTP 边界 |
| `packages/reporting/generation.py` | 76% | 49 | 三格式与异常输入；真实 PDF 仍需容器验收 |

以上排序是风险和覆盖缺口的诊断，不等于各模块已缺少全部业务测试。优先补 Worker 入口和 HTTP 边界的可重复合成测试，再决定 PostgreSQL 适配器应纳入哪一级 CI；实际容器链路不能由 mock 测试替代。最终仍须重新执行 CI 原命令并保留覆盖率产物。

本次未修改代码、数据库、CI 阈值或生产配置，不涉及真实模型调用。
