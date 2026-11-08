# ERP 字段映射与待验证项

状态：适配器代码已实现；真实ERP接口映射 `not_run`。本地/HTTP模拟器输入不能证明具体ERP字段名。

| 领域字段 | 适配器当前识别的输入字段 | 转换与缺失策略 | 真实ERP状态 |
|---|---|---|---|
| Supplier.id | `id` / `supplier_id` / `code` | 字符串化；缺失列入`missing_fields` | not_verified |
| Supplier.code/name/status | `code`/`supplier_code`、`name`/`supplier_name`、`status`/`state` | 保留raw_status；未知状态不得写入 | not_verified |
| Part | `id`/`part_id`/`code`，`code`/`part_code`，`name`/`part_name`，`unit`/`unit_name`，`active`/`enabled` | id/code/name/unit/active必需；active要求原始bool | not_verified |
| Inventory | ID：`id`/`inventory_id`；物料：`part_id`/`material_id`；仓库：`warehouse_id`/`warehouse_code`；现存：`on_hand`/`quantity`/`stock_qty`；预留：`reserved`/`reserved_qty`；在途：`inbound`/`inbound_qty`；以及`safety_stock`、`target_stock`、`version` | 顺序为规范字段优先、再按表中别名；映射、缺失判断与原始整数校验共用同一字段表。缺ID、所有现存数量别名、null、bool整数伪装、负计数或非法版本均拒绝；0是合法事实且不被别名覆盖。无默认单位/目标值 | not_verified |
| PurchaseOrder | `id`/`order_id`、`number`、`owner_id`、`draft_id`、`supplier_id`、`warehouse_id`、`status`、`total_cents`/`total_yuan`、`version`、`created_at`、`items`/`details` | 使用既有PurchaseOrder DTO；必需字段缺失/未知状态/不一致金额失败；yuan以`Decimal*100`转换 | not_verified |
| Order item | `part_id`/`material_id`、`quantity`/`qty`、`quote_id`、单价/行额yuan别名、received_qty别名 | 必需字段缺失失败；数量保持原始整数；元精确换分 | not_verified |
| Page | `records`/`data`、`page`、`page_size`、`pages`、`total` | 所有分页字段必须存在且与请求/页集一致；缺页、重复ID、条数矛盾、变更total或触及100页/10000条上限时失败 | not_verified |
| Quote supplement | unit price字段；MOQ、lead days、valid until别名 | 未提供时返回None与missing_fields；不推断MOQ/交期/有效期 | not_verified |

API与MCP通过同一`ProviderQueries`入口做严格DTO映射和完整页集聚合。单页数据不代表完整结果；页码、页数、total、每页记录数、唯一实体ID必须相互一致。若远程响应缺少字段，返回字段缺失错误，不得补0、单位、版本或虚构完整实体。远程查询受剩余时限及MCP run deadline约束。

P09 C02在本地HTTP模拟器中分别经REST与实际MCP业务分发验证`inventory_id`+`quantity`映射为相同的I01/P01/W01事实；删除全部现存数量别名时两个入口均返回`REMOTE_DATA_INVALID`，不回退Mongo。详见`evidence/P09-C02.md`。该模拟只验证适配契约，不证明真实ERP字段。

真实连接前必须用经授权的测试账号取得只读样本并逐字段核对：分页页码、total语义、日期/时区、状态映射、金额精度和行明细。当前没有实际ERP测试环境，因此没有任何具体ERP端点/响应字段被标为实测。写接口暂未开启远程写能力；远程写响应丢失由`ErpOutcomeUnknown`阻止自动重试，普通404不是未提交证据。
