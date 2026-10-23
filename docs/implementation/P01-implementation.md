# P01 本地业务与补货 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 真实本地数据、精确补货规则与可核对的业务页面。
**Architecture:** repository拉数据，service组织用例，domain纯函数计算，HTTP/UI只展示。
**Tech Stack:** P00锁定环境；新增pytest规则测试，不引入模型。
**Spec:** [P01](../specs/P01-domain-data.md)、共享契约第2–4节；接口见[映射](./INTERFACES.md)。

## Global Constraints

整数分；UTC存储/上海展示；种子6物料、3供应商、8报价、8库存、2历史单；MOQ是最小量不是包装倍数；缺失数据不能编造；本阶段不提供订单执行入口。

## Review Focus

阈值相等/无报价→T03；分页当全量→T02/T04；seed覆盖用户订单→T01；浮点误差→T03；界面筛选与后台不同→T05/T06。

### P01-T01：DTO、索引与合成数据

**Files:** Create `backend/app/contracts/domain.py`、`fixtures/v1/{parts,suppliers,quotes,inventories,drafts,orders}.json`、`fixtures/v1/manifest.json`、`scripts/seed.py`；Modify repositories/indexes.py；Test `tests/integration/test_seed.py`。
**Interfaces:** 共享Part/Supplier/Quote/Inventory/OrderDraft/PurchaseOrder；`seed(database,fixture_dir)->SeedSummary`，默认只upsert合成ID，不清库。

- [ ] 写seed两次的数量/外键/唯一code断言，以及seed后已有新订单仍存在的断言。manifest包含各记录数、按仓库汇总和canonical数据hash。
- [ ] 填写P001固定案例，历史单支撑10件在途；其余记录满足阈值和无报价案例，固定时钟2026-10-23T02:00:00Z。
- [ ] 用Pydantic先验证全批数据再写DB；索引管理集中，不散落路由；`--reset`只允许专用测试库并显式指定，默认不删除数据。
- [ ] 执行`uv run pytest tests/integration/test_seed.py -q`；运行`uv run python -m scripts.seed`并核对manifest输出。

### P01-T02：可替换的查询端口与仓储

**Files:** Create `ports/catalog.py`、`ports/inventory.py`、`repositories/{catalog,inventory}.py`、`services/catalog.py`；Test `tests/integration/test_catalog.py`。
**Interfaces:** CatalogReader/InventoryReader按接口映射；Mongo实现接收db/clock，可注入后续Provider。

- [ ] 写分页测试：8条page_size3，返回3页且无重复；名称+仓库筛选total正确；非法page/page_size422，查不到ID404，空查询不是失败。
- [ ] 所有分页排序固定为id，Mongo查询计数与records共用同一个filter。`list_scope`返回全部指定范围，不用第一页替代。
- [ ] 汇总可用aggregation或全范围读取，但所有计算复用数值规则；返回来源local_seed、as_of与scope。
- [ ] 执行`uv run pytest tests/integration/test_catalog.py -q`并补catalog/库存仓储README，记录字段查询和索引。

### P01-T03：纯计算与报价选择

**Files:** Create `domain/money.py`、`domain/replenishment.py`、`tests/unit/test_replenishment.py`、`tests/unit/test_money.py`。
**Interfaces:** calculate_replenishment签名见映射；`line_total(quantity:int,unit_price_cents:int)->int`拒绝bool/负数/非整数。

- [ ] 先写固定断言，确认实现前失败：

```python
line = calculate_replenishment(inv_p001, quotes, suppliers, 7, fixed_now)
assert (line.available, line.projected, line.shortage) == (15, 25, 55)
assert (line.recommended_quote_id, line.quantity, line.total_cents) == ('Q01', 55, 66000)
```

- [ ] seed明确Q01=S01报价、Q02=S02报价；无交期限制选Q02/60500。先过滤供应商inactive、过期、交期，再按单价/交期/id排序。valid_until==now视为过期。
- [ ] 补阈值相等、MOQ大于缺口、无有效报价、不存在物料、非法库存数据；无补货需求quantity=0且actionable=false，不生成零数量采购单。
- [ ] 执行`uv run pytest tests/unit/test_replenishment.py tests/unit/test_money.py -q`。只写纯函数，不访问DB/LLM。

### P01-T04：业务服务、API与类型生成

**Files:** Create `services/replenishment.py`、`api/catalog.py`、`api/inventory.py`、`scripts/export_contracts.py`；Generate `frontend/src/lib/domain-types.ts`；Test `tests/integration/test_inventory_api.py`。
**Interfaces:** POST preview请求和PreviewResult见映射；路径GET /api/inventory、/api/inventory/warnings、/api/inventory/summary；其余按共享契约。

- [ ] 写HTTP测试核对P001两种推荐、分页/预警/汇总、缺失数据；每个响应含meta，来源/时间/范围可追踪。
- [ ] preview一次拉齐范围、库存、报价、供应商，调用纯函数；保存snapshot_versions与SourceRef，为P04审批校验预留真实字段。
- [ ] schema导出为稳定排序文件并生成TypeScript类型，提供`--check`仅检测差异，不在CI静默重写；不让前端手写另一套金额/状态类型。
- [ ] 执行API测试和`uv run python -m scripts.export_contracts --check`，生成文件差异必须随源码提交。

### P01-T05：数据浏览与预览UI

**Files:** Create `frontend/src/app/data/page.tsx`、`components/data/{InventoryTable,SupplierTable,QuoteTable,ReplenishmentPreview}.tsx`、对应README和测试。
**Interfaces:** 使用lib/api和生成类型；筛选参数与API保持一套，金额通过共用formatMoney展示两位小数。

- [ ] 写UI测试：改仓库时page重置1；空结果/错误不显示上一次查询金额；100页请求被API拒绝时显示真实错误。
- [ ] 创建四类数据视图，展示仓库、在手/预留/在途、阈值、报价有效期与建议；点击预览请求API，不在浏览器算补货公式。
- [ ] 执行Vitest/typecheck/build；浏览器核对P001在7天限制下55件/660元及数据源标签。
- [ ] 保留表格内部滚动，页面主体不横向撑开；记录浏览器步骤而不是仅写“静态通过”。

### P01-T06：阶段回归与交付

**Files:** Modify verify_stage manifest、STATUS、P01 spec；Create `evidence/P01.md`。
**Interfaces:** `verify_stage P01 --mode offline`包含P00仍必要检查、规则/API/schema/UI测试。

- [ ] 用全新测试库seed后跑全部P01检查，确认不依赖本机手工改过的数据。
- [ ] 将P01-A01..A06逐条映射到测试名或浏览器步骤；无模型/订单执行验收写not_run/not_applicable。
- [ ] 更新模块README、根运行示例与真实状态，做diff检查。
- [ ] 提交推送并核对`phase-p01`；报告P001数值和证据后停止。
