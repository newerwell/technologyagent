# domain 纯业务规则

## 职责

P01 只包含确定性、可单测的规则，不访问数据库、HTTP 或模型：

- `money.py`：`line_total(quantity, unit_price_cents)` 使用整数分；拒绝 bool/负数/非整数，单价必须 >0。
- `replenishment.py`：`stock_state(inventory)`、`calculate_replenishment(...)`、`summarize_inventory(...)`。
  - available = on_hand - reserved
  - projected = available + inbound
  - shortage = max(0, target_stock - projected)
  - warning = projected < safety_stock（等于阈值不预警）
  - 报价过滤顺序：供应商 active → valid_until > now（等于 now 过期）→ max_lead_days → 按单价/交期/supplier_id/quote_id 排序
  - 建议数量 = max(shortage, MOQ)，MOQ 不是包装倍数

## 调用例子

```python
line = calculate_replenishment(inventory, quotes, suppliers, 7, fixed_now)
print(line.recommended_quote_id, line.quantity, line.total_cents)
```

## 边界

- 不做数据库读取；由 service 注入已加载实体。
- 无有效报价时返回 `missing_fields=["valid_quote"]`、quantity/total=0、actionable=false。
- 无缺口时 quantity=0、recommended_quote_id=None、actionable=false。
- 非法库存（reserved>on_hand、target<safety、负数）抛 ValueError。

## 验证

```powershell
uv run pytest tests/unit/test_money.py tests/unit/test_replenishment.py -q
```
