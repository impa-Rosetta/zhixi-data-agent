# M6-B 可重放 SSE 与客户端恢复验收

- 日期：2026-09-08
- 状态：通过
- 产品提交：bfb388a
- 上游验收：docs/acceptance/M6-A-run-projection-acceptance.md

## 交付范围

- 新增 AnalysisRun text/event-stream 接口；
- 支持数据库历史事件分批重放、Last-Event-ID 和 after 游标；
- 事件 id 与持久化 sequence 一致，事件名称与 JSON 信封双重校验；
- 非终态连接发送心跳，终态事件完整发送后关闭；
- 使用异步等待与每轮独立短数据库会话，避免长事务和轮询占满线程池；
- 新增带 Bearer Token 和单飞令牌刷新的前端流式请求；
- 新增分块 CRLF 解析、断线退避重连、重复事件去重和序号空洞投影恢复；
- 未知事件只保留在技术时间线，不影响稳定运行投影。

## 自动化证据

- Ruff：通过；
- 严格 MyPy：83 个源文件通过；
- Pytest：195 项通过；
- ESLint 与 TypeScript：通过；
- Vitest：14 个测试文件、33 项测试通过；
- SSE 定向覆盖历史重放、游标续传、心跳、分块解析、类型/序号校验、重连、去重和空洞处理。

## 真实运行证据

- API 与 Web 生产镜像从提交 bfb388a 构建成功并健康部署；
- 本地演示工作空间创建并取消真实 AnalysisRun，产生两个持久化事件；
- 全量流包含 id 1 和 id 2；
- 使用 Last-Event-ID 1 重连后不再收到 id 1，只收到 id 2；
- Content-Type 为 text/event-stream，Cache-Control 禁止缓存和转换；
- 流内容不包含 restricted_reasoning；
- 验收后临时构建目录与归档均已删除。

## 验收结论

M6-B 完成。事件链路可重放、可续传、可去重且不会把连接正确性绑定到进程内状态。下一切片进入 M6-C 三栏问析工作台。
