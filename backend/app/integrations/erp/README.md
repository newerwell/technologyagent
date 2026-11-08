# ERP HTTP 与字段映射

`client.py` 封装HTTPX请求。`read()`最多发3次请求（含首次），接收当前剩余查询时限；`write()`只发一次，超时抛`ErpOutcomeUnknown`；`lookup()`遇普通404同样保持未知结果，绝不把404当作无副作用证明。当前P09只接通严格校验的远程读取，写capability为空。

`provider_queries.py` 是 API/MCP 共用入口，使用这些映射后还会按项目现有 DTO 校验实体。分页逐页核对响应声明的 page/page_size/pages/total、每页记录数和跨页实体ID；缺字段、缺页、越界、重复ID、total变化或触及100页/10000条安全上限都会失败关闭，不会返回看似完整的页。聚合会在运行时限内完成，并将剩余时间传给每次HTTP读取。金额必须可精确表达为分；未知状态不能进入订单 DTO，报价缺MOQ/交期/有效期保留None。`order_statistics` 按聚合结构映射，不套订单实体映射。字段/别名见[`docs/erp-mapping.md`](../../../../docs/erp-mapping.md)。目前真实ERP环境未配置，文档列出的别名是适配代码能力，不是对某ERP的实测结论。

验证：`uv run python -m pytest tests/unit/test_provider_queries.py tests/unit/test_p08_erp_adapter.py tests/integration/test_provider_contract.py tests/integration/test_provider_switching.py tests/integration/test_provider_queries_r5.py -q -rs`。真实ERP未调用，保持`not_run`。
