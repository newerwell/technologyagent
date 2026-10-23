# components/data 业务数据页

## 职责

P01 的浏览器业务数据视图：

- `DataPage`：仓库/名称筛选、分页重置、汇总、预警、错误与加载状态。
- `InventoryTable`：在手/预留/在途/可用/预计/安全/目标/缺口/预警/版本。
- `SupplierTable`、`QuoteTable`：供应商状态、报价 MOQ/交期/有效期/后端判定 is_valid。
- `ReplenishmentPreview`：选择物料/仓库/最大交期，调用后端 preview，展示候选报价与推荐；浏览器不计算补货公式。

## 接口

全部通过 `lib/api.ts` 访问同源 `/api`；金额用 `lib/format.ts` 的 `formatMoney` 展示两位小数，时间按 Asia/Shanghai 展示。筛选参数与后端 API 同名：

- `warehouse_id`、`part_name`、`page`、`page_size`。
- 改仓库/名称时 page 重置为 1；请求失败会清空旧数据与旧金额。

## 边界

- 无订单创建/审批/聊天/模型调用；`actionable=false` 只表示预览不可下单。
- 表格横向滚动限制在 `.table-scroll` 内，页面主体不被撑宽。
- P01 的 Playwright E2E 不启用；组件测试使用 Vitest + Testing Library。

## 验证

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
```
