# M6 智能问析工作台整体验收

- 验收日期：2026-09-09
- 结论：通过

M6-A 至 M6-D 全部完成：

1. 工作空间隔离的运行列表与完整投影；
2. 基于持久化事件的 SSE 重放、断点续传、心跳、去重和空洞恢复；
3. 桌面三栏与移动分区工作台，覆盖创建、澄清、确认、拒绝、取消和重试；
4. 真实指标卡/表格、可信等级、Evidence、验证结论与脱敏技术详情；
5. DeepSeek V4 Pro 到本地安全查询工具再到持久化证据的真实完成链路；
6. 自动化、Chrome 桌面/移动端、Docker Compose 与远端提交一致性验收。

系统没有使用前端模拟答案、固定成功结果或绕过工具的模型 SQL。断网和刷新不改变服务器事实源，密钥、凭据、内部检查点及受限推理不进入浏览器投影。

M6 验收证据分别记录于：

- `M6-A-run-projection-acceptance.md`；
- `M6-B-resumable-sse-acceptance.md`；
- `M6-C-analysis-workbench-acceptance.md`；
- `M6-D-results-evidence-acceptance.md`。
