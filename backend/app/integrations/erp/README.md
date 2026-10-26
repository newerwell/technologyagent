# ERP HTTP 与字段映射

`client.py` 封装HTTPX请求。`read()`最多发3次请求（含首次），剩余预算不足时不再开始下一次；`write()`只发一次，超时抛`ErpOutcomeUnknown`；`lookup()`遇普通404同样保持未知结果，绝不把404当作无副作用证明。

`mappings.py` 将ERP字段转换为内部结构。金额必须可精确表达为分；未知状态保留`raw_status`并标记`unknown`，报价缺MOQ/交期/有效期保留None。分页只在单页完整且 total/pages/实体数一致时标完整；只收到末页、空越界页或重复实体均保留 incomplete 与告警。`order_statistics` 按聚合结构映射，保留 total/total_cents/by_status/scope，不再套订单实体映射。映射字段/别名见[`docs/erp-mapping.md`](../../../../docs/erp-mapping.md)。目前真实ERP环境未配置，文档列出的别名是适配代码能力，不是对某ERP的实测结论。

验证：`uv run pytest tests/unit/test_p08_erp_adapter.py tests/integration/test_provider_contract.py -q`。
