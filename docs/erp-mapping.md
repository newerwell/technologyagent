# ERP 字段映射与待验证项

状态：适配器代码已实现；真实ERP接口映射 `not_run`。本地/HTTP模拟器输入不能证明具体ERP字段名。

| 领域字段 | 适配器当前识别的输入字段 | 转换与缺失策略 | 真实ERP状态 |
|---|---|---|---|
| Supplier.id | `id` / `supplier_id` / `code` | 字符串化；缺失列入`missing_fields` | not_verified |
| Supplier.code/name/status | `code`/`supplier_code`、`name`/`supplier_name`、`status`/`state` | 保留raw_status；未知状态不得写入 | not_verified |
| Part.id/code/name/unit | `id`/`part_id`/`code`，`code`/`part_code`，`name`/`part_name`，`unit`/`unit_name` | 单位缺失列入`missing_fields` | not_verified |
| Inventory | `inventory_id`、`part_id`/`material_id`、`warehouse_id`/`warehouse_code`、`on_hand`/`quantity`/`stock_qty`、reserved/inbound别名 | 数量不做小数转整；缺字段列出 | not_verified |
| PurchaseOrder | `id`/`order_id`、`number`、`status`、`total_yuan`、`items`/`details` | ID字符串；金额`Decimal*100`；未知状态映射unknown并保留raw_status | not_verified |
| Order item | `part_id`/`material_id`、`quantity`/`qty`、单价/行额yuan别名、received_qty别名 | 元精确换分；数量保持原类型由业务校验拒绝非整数 | not_verified |
| Page | `records`/`data`、`total` | total异常/缺失给scope警告，不声称全量 | not_verified |
| Quote supplement | unit price字段；MOQ、lead days、valid until别名 | 未提供时返回None与missing_fields；不推断MOQ/交期/有效期 | not_verified |

真实连接前必须用经授权的测试账号取得只读样本并逐字段核对：分页页码、total语义、日期/时区、状态映射、金额精度和行明细。当前没有实际ERP测试环境，因此没有任何具体ERP端点/响应字段被标为实测。写接口暂未开启远程写能力；远程写响应丢失由`ErpOutcomeUnknown`阻止自动重试，普通404不是未提交证据。
