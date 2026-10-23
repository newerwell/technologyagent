# contracts 共享契约

## 职责

P00/P01 的跨层数据、请求/响应和分页契约：

- `common.py`：Envelope、Meta、AppError、PageQuery、Page、RequestContext、Clock。
- `domain.py`：Part/Supplier/Quote/Inventory、历史草稿/订单、SourceRef、补货请求/预览、InventoryView/QuoteView/InventorySummary。
- `domain-schema.v1.json`：由脚本生成的 JSON Schema，供跨语言/后续阶段使用。

## 生成

```powershell
uv run python -m scripts.export_contracts
uv run python -m scripts.export_contracts --check
```

生成目标同时包括 `frontend/src/lib/domain-types.ts`。不要手改生成文件；改 Pydantic 模型后重新生成并提交差异。

## 边界

- 金额字段一律整数分，币种固定 CNY。
- 时间使用带时区 datetime，JSON 输出 ISO 8601 UTC。
- 字段变更需要同步调用方、生成类型、夹具与测试；`--check` 防止静默漂移。
