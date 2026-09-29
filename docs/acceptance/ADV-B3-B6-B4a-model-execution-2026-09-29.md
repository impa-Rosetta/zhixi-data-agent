# 六算法真实训练、安全加载与隔离镜像验收

日期：2026-09-29。依据已批准高级分析与建模三批规格及实施计划。

## 本次实现

- B3：线性回归、决策树、随机森林、逻辑回归、KMeans、Isolation Forest；决策树/随机森林同时覆盖分类和回归，合计八种算法任务组合。
- 固定种子、20%留出验证、时间或设备分组划分；训练集拟合缺失填补/编码/标准化，统一 Pipeline。时间边界同时间戳不跨训练/验证；分类两侧必须包含全部类别。
- 回归 MAE/RMSE/R²；分类 macro precision/recall/F1 与混淆矩阵；监督任务与均值/多数类基线比较。常量验证目标的 R²显示不可计算原因。聚类输出中心、规模与 silhouette；无监督异常输出分数/标签/占比，不声称准确率。
- 特征重要性、系数、真实验证预测及原始行映射。分类拒绝连续小数标签。全部数据为固定模拟数据，不代表企业实证。
- B6 底层：内部 skops 文件摘要/大小/依赖版本校验；固定安全类型白名单为 numpy.dtype 与 sklearn.tree._tree.Tree，未知类型拒绝，绝不依据文件声明自动信任。
- 加载前检查 ZIP 膨胀上限、成员重复及加密标记；加载后检查 Pipeline、预处理器、估计器及规格参数一致性。推理按冻结特征顺序读取，拒绝字段/类型变化与版本不匹配；允许缺失值及新类别，不偷偷重训。
- B4a：独立镜像固定全部直接与间接依赖及基础镜像摘要。严格文件协议只接受 train/predict 与任务/attempt 标识，拒绝用户命令、路径、镜像和未知参数。不在 API/Worker 进程直接训练。

## 实际验收

真实容器对八种任务分别训练及保存后推理，共16次执行，全部成功。输入为1000条固定模拟明细，新样本单独推理。实际 inspect 验证：UID 10001、无网络、只读根目录、禁止权限提升、capabilities全部丢弃、2 CPU、1 GiB、128 PID、128 MiB临时目录；未挂Docker socket及业务服务凭据。所有临时容器和本次专用目录在验收后清理，既有数据库及卷未变更。

证据：[真实容器运行记录](evidence/ADV-B4a-container-2026-09-29.json)。复验入口：`python -m scripts.accept_modeling_container`。镜像构建入口：`docker build -f infra/modeling/Dockerfile -t zhixi-modeling:b4a .`。

完整后端969通过、1条件跳过，覆盖率90.54%，达到CI门槛；Ruff及140模块严格MyPy通过，密钥扫描通过。额外文件入口测试另列于后续检查记录，不将本地结果说成远端CI通过。

## 明确未完成

本次不是网页建模闭环，能力清单不能因此开放 model.train/predict。

1. B2：专用完整查询提取、数据库不可变快照回执及实际对象存储链路。
2. B4：生产主机代理只接收持久化任务ID；真实300秒超时/运行中取消、输出文件系统限额、代理启动与恢复验收。本脚本的超时与清理只是验收保护，不替代生产代理。
3. B5/B6：任务/模型/不可变版本数据库迁移、租约与attempt幂等发布、对象存储、当前权限/源状态重验。底层文件安全加载不等于授权安全完成。
4. B7：六算法真实API/后台/存储/推理完整验收、撤权和陈旧任务输出拒绝。
5. C：对话建模意图/确认/上下文、真实进度与取消、模型结果和代码卡片、报告引用、多轮浏览器验收。

项目整体另外仍有通用脚本隔离、未知源适配、真实LLM基准与预算授权、观测、性能、发布恢复及比赛材料证据更新等独立门禁。不能由此次固定建模镜像自动关闭。

## 下一步执行顺序

先完成B5持久化与授权租约，再接B4代理和存储发布，最后接C对话展示与B7联合验收。无代理时明确返回服务未配置，不能降级为宿主机或API直接训练。用户现有M3文档、未知评测JSON、output/tmp不纳入开发提交。
Final CI-scope recheck (2026-09-29): 973 passed, 1 conditional skip, coverage 90.73%; Ruff lint/format and strict MyPy passed. The four additional executor-file tests cover fixed mounts, exclusive writes, sanitized failure output and refusing an unconfigured host process. Remote CI and production modeling delivery remain unverified.
