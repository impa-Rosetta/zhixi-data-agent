# M8-E3c 失败回溯持久化缺口核查

日期：2026-09-27。性质：只读诊断，不是功能验收通过。

## 实际证据

对实际平台report_acceptance查询评测任务`a2fc7f5c-fe13-4ff5-a93e-c94a9e4afd63`的EvaluationCaseResult.run_references，并按UUID左连接平台analysis_runs：保存引用93条，存在的Agent运行0条，同工作空间存在的Agent运行0条。此任务的92条判分通过不代表93条运行引用可回溯。

原因：postgres_case_factory每个案例创建自有临时平台结构，draft_case_factory使用内存SQLite；两者在上下文结束后清理。run_offline_suite只返回结构化判分与run_ids，execute_offline_run把这些ID存入主平台，却没有保留对应的技术执行记录。cleanup不是异常，不应停止清理公共或私有夹具来伪装修复。

另一权限边界：AUDITOR具备EVALUATION_READ，但没有ANALYSIS_RUN；普通Agent详情API使用ANALYSIS_RUN。直接给评测页面加普通分析链接既会失效，也不能为此放宽审计员的分析权限。

## 当前结论

M8-E3的失败回链尚未完成。现有聚合、案例断言、错误码和UUID可用于评测定位，但UUID不是可用的详情页证据。不能从已删除的运行补造历史Trace或Evidence。这个问题不推翻已有确定性评分结果，但收窄其可追溯性证明。

## 推荐后续方案（待确认，未实施）

在夹具清理前提取严格白名单的只读执行归档：原始运行ID、阶段、状态、安全化错误码、工具名称、Evidence/Validation引用及类型/结果，不复制问题、回答正文、SQL、源数据、凭据或供应商请求。归档随案例尝试号持久化到主平台，经工作空间EVALUATION_READ授权；页面显示“已归档执行记录”，而非假装原始Agent运行仍存在。有效且另有分析权限的实际平台运行才可提供普通分析链接。

旧历史记录明确显示“归档未保留”，不伪造补档。新增迁移往返、跨空间/审计员/撤权、夹具清理后归档仍可读、多轮逐运行定位、凭据canary不外泄和真实失败案例验收。详细规格需确认后编写审阅。

本次未修改产品行为、未调用模型、未改动任何数据库内容；用户原有文档改动保留。
