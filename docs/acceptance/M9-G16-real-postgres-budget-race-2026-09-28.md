# M9-G16 真实PostgreSQL预算并发与全量回归

日期：2026-09-28，基线`2c2e199`。执行已批准E4a底座的现存可选测试`tests/test_evaluation_model_budget_postgres.py`，不新增测试实现、产品代码或依赖，不调用DeepSeek。

## 环境

专用容器`zhixi-m9-budget-g16-20260928`，标签`zhixi.acceptance=M9-G16`，镜像postgres:16.4-alpine。数据库仅绑定127.0.0.1:55439，合成账号与独立空库；PostgreSQL数据目录为256MiB tmpfs，无bind或持久卷。未接入用户平台库、已有源库、对象存储或队列。

当前本机源码及虚拟环境执行Alembic全链迁移至`20260927_0014`。测试的专用连接只通过`EVALUATION_BUDGET_POSTGRES_URL`传给现有测试；迁移临时DATABASE_URL在结束后恢复。没有配置或读取供应商密钥。

## 现存断言与实测

每次构造独立合成用户/空间及live轨道预算记录（max_calls=1），用ThreadPoolExecutor两线程调用真实`reserve_call`与PostgreSQL事务。一个获得receipt，另一个收到`evaluation.budget_exceeded`；数据库核对仅1条receipt，calls_reserved=1、tokens_reserved=100。

对成功receipt用合成30-token用量结算：第一次返回True，重复返回False；数据库核对calls_used=1、tokens_used=30、预留数均0。这里的calls_used与tokens_used是测试输入模拟结算，不是实际模型usage或费用，没有调用供应商。

局部测试连续5次通过，耗时0.75、0.75、0.73、0.73、0.78秒。5次测试均执行两线程争用并重复结算，不能据此宣称所有并发、超时、断连或99%恢复目标达成；测试没有记录严格同时进入临界区的时间。

5次结束后真实SQL查询确认evaluation_runs、evaluation_model_calls、workspaces、users四表计数均0，夹具自行清理完成。

## 全量门禁

带专用真实数据库URL运行：

`pytest --cov=apps --cov=packages --cov-report=term --cov-fail-under=90 --cov-report=json:tmp/M9-G16-coverage.json -o cache_dir=tmp/pytest-cache-g16-all`

- 580通过，无跳过，37.66秒；此前G13的唯一可选数据库跳过本次实际执行。
- Starlette/AnyIO弃用警告仍存在；使用本地tmp缓存路径后没有此前缓存写入告警。
- 10,164条语句、9,076覆盖、1,088未覆盖，89.29555293191657%，与G13相同；真实数据库验证增强持久化/事务证据，不凭空增加覆盖语句。
- 90%覆盖门禁明确失败，退出1；同分母仍需至少72条覆盖。测试通过不等于完整CI通过。
- 本次无生产代码变动，静态门禁和依赖审计保持G15证据，不声称重复执行这些检查。

全量结束后四个合成业务表计数仍为0；核对容器名、标签、tmpfs及无持久挂载后删除唯一临时容器，标签过滤确认无残留。tmpfs合成数据不可恢复；没有删除已有数据库、持久卷、网络、镜像或用户文件。覆盖报告留在本地tmp，不纳入提交。

## 未关闭边界

这是预算底座的真实PostgreSQL并发与幂等结算测试，不是公开live评测入口、模型网关调用计费、Worker崩溃恢复、真实模型基准或HTTP并发验收。黄金集发布、失败档案回链、全链路观测、沙箱、M9安全/性能/备份交付仍未完成。三项已提出的小改动方案仍等待用户确认，未把自动目标续跑当作批准。
