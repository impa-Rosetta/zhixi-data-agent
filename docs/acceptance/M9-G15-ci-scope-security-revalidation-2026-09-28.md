# M9-G15 完整静态门禁范围与依赖安全复核

日期：2026-09-28，基线`cc0be43813a92c32887706099e140d032da20192`。只运行已有CI命令、读取代码及上游公告；不修改依赖、CI范围、覆盖阈值或用户数据。

## 实际结果

以`.github/workflows/quality.yml`为权威范围：

| 本机命令 | 结果 | 证明边界 |
|---|---|---|
| `ruff check apps packages tests scripts` | 通过 | 包含文稿与验收脚本 |
| `ruff format --check apps packages tests scripts` | 229文件通过 | 没有缩减CI目录 |
| `mypy apps packages scripts` | 154源文件通过 | pyproject启用strict |
| `npm audit --omit=dev --audit-level=high --registry=https://registry.npmjs.org` | 0漏洞，退出0 | 本机锁定的生产依赖，不含dev或镜像OS包 |
| `pip-audit --local --skip-editable` | 失败，退出1 | 本机虚拟环境；不等于全镜像或Linux安装解析结果 |
| `docker compose --env-file .env.example config --quiet` | 通过，退出0 | 仅配置语法；没有构建或启动正式Compose |

G12/G13只执行`mypy`默认packages范围（147源文件）及不含scripts的Ruff格式范围，不能单独作为完整CI静态门禁依据。本次补足scripts的真实检查；不覆盖或改写当时记录。

最新后端测试保持G13的579通过、1跳过、89.29555293191657%；本次未重跑pytest，覆盖门槛仍未过90%。前端保持G14的94/94单次本地通过，偶发超时仍未关闭。没有取得远端Actions/Linux全绿证据，也没有把本机结果替代远端CI。

## PDF依赖安全：未修复

pyproject、uv.lock及本机都使用WeasyPrint66.0。pip-audit输出5行告警，但按ID去重只有3个，不称为5个独立漏洞：

| 审计ID | 别名 | 审计fix_versions | 上游核对（2026-09-28） |
|---|---|---|---|
| PYSEC-2026-2034（重复2行） | CVE-2025-68616 / GHSA-983w-rhvv-gwmv | 68.0 | 受影响<68.0，修复>=68.0 |
| PYSEC-2026-3412（重复2行） | CVE-2026-49452 / GHSA-jhhc-3hcp-qhm5 | 空 | 上游列受影响<=68.1、修复>=69.0；审计元数据未列修复版本 |
| PYSEC-2026-3940 | CVE-2026-55073 / GHSA-jf6q-chmf-3h3v | 70.0 | 上游列受影响<=69.0、Patched versions None，与审计fix_versions不一致 |

直接依据维护者公告：[重定向绕过](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-983w-rhvv-gwmv)、[presentational hints CSS注入](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-jhhc-3hcp-qhm5)、[write_pdf资源通道绕过](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-jf6q-chmf-3h3v)。没有复制漏洞利用代码或执行针对现有服务的攻击。

当前`render_pdf`固定使用`HTML(string=..., url_fetcher=deny_external_url).write_pdf()`；未传入公告涉及的攻击者控制stylesheets/xmp_metadata，也没有开启presentational_hints。这降低相关路径的暴露面，不证明全部漏洞不可利用，不允许忽略审计告警。Compose的通用Worker含数据库/对象存储配置及网络依赖，不能因历史无网络PDF冒烟就声称正式Worker无网络或无凭据。

建议升级候选70.0并同步锁文件，但升级后的实际审计、中文PDF、安全资源拒绝及真实报告回归才决定是否关闭；不得提前承诺70.0解决所有告警。若仍有未解决风险，不添加ignore或放宽门禁，应保留阻塞并另审隔离方案。

## 交付与剩余边界

只读目录核查显示docs/submission有方案、S2修订版和组员参考资料；没有发现最终PPTX、演示视频或备份/恢复执行脚本。仅文件目录证据，不推断团队在其他路径没有材料，也不把参考稿视为最终成品。PostgreSQL已有G9隔离恢复证据，MinIO/配置密钥及跨组件一致性恢复未关闭。

本次不关闭M8/M9。语义发布边界、图表单测稳定性和依赖升级方案仍待明确确认；高级建模、沙箱、全链路观测、真实模型基准、性能及最终交付仍须按官方范围完成。
