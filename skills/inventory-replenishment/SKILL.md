---
id: inventory-replenishment
version: 1.0.0
---

# 补货分析

目标：根据服务端库存、有效报价与补货预览解释缺口或草稿。

何时使用：库存、缺口、预警或订单补货任务。何时不用：用户只询问供应商或报表格式。

输入：用户请求及限定的仓库/零件。输出：逐实体的服务端事实、来源和观察时间；不得推算或补造缺失字段。

规则：使用 `inventory_page`、`inventory_warning` 或 `replenishment_preview` 获取事实；订单需使用既有草稿、审批和MutationService。技能只引用 domain/replenishment.py 的规则，不重复实现公式。

缺少仓库或零件时，应明确询问；不得把安全预警当作目标缺口。

示例：对 P001/W01 请求 replenishment_preview，引用返回的有效报价与缺口后再作说明。
