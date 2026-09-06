# A1 结构差异界面验收

- 日期：2026-09-06
- 状态：通过
- 规格：`docs/superpowers/specs/2026-09-06-a07-remaining-product-delivery-design.md`
- 计划：`docs/plans/2026-09-06-a07-remaining-product-delivery-implementation-plan.md`

## 交付内容

1. 在数据源详情页加入确定性结构变化面板；
2. 可选择任意目标快照并明确展示相邻版本；
3. 支持变化类型、影响级别和对象类型筛选；
4. 支持服务端分页，并显示本页筛选结果数量；
5. 新增、删除和修改使用稳定标签，破坏性、警告和提示分级展示；
6. 每项变化可展开查看完整 before/after 结构证据；
7. 页面只展示后端确定性差异，不调用模型解释或改写。

## 自动化门禁

- 前端 7 个测试文件、15 项测试全部通过；
- ESLint、TypeScript和Vite生产构建通过；
- 后端Ruff、格式检查、严格MyPy通过；
- 后端148项测试通过，总覆盖率90%。

## 真实 PostgreSQL 验收

在本地样例库 `production_orders` 上临时增加字段并扫描：

- 目录 v3 产生 `added / column` 差异；
- 删除临时字段并再次扫描；
- 目录 v4 产生 `removed / column` 差异；
- 最终样例数据库结构已恢复；
- 两个不可变快照保留新增和删除证据，可由界面选择查看。

验收过程未使用模型生成差异，未输出访问令牌或数据库凭据。
