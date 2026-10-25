# P08 完整业务与ERP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 本地完成四类23工具及收货/库存闭环，远程ERP通过可验证Provider接入。
**Architecture:** Provider实现既有ports；本地事务与远程outcome_unknown分开处理，不能用Mongo事务包外部HTTP冒充原子性。
**Tech Stack:** 既有Mongo、HTTPX、MCP，ERP字段用Decimal转换。
**Spec:** [P08](../specs/P08-erp-integration.md)、共享契约Receipt/Movement及订单状态。

## Global Constraints

不静默数据源回退；全部domain_write强制批准；远程写超时不盲重试；receipt去重作用域一致；当前未收数量决定inbound，收货不能重复计数。

## Review Focus

Provider绕过MutationService→T01/T02；远程缺字段/分页异常→T03；多表收货崩溃→T04；写超时重复下单→T05；模拟器通过冒充真实ERP→T06。

### P08-T01：组合Provider与按模块来源

**Files:** Create `integrations/{business_provider,local_provider,erp_provider}.py`；Extend ports/配置/bootstrap；Test `tests/integration/test_provider_switching.py`。
**Interfaces:** ProviderCapabilities(read/write/actions/snapshot/freshness)；Catalog/Inventory/Order ports保留方法名，新增方法明确typed request。

- [x] local_seed完整读写、local_snapshot只读、remote_erp按实测能力；启动时解析suppliers/parts/orders/inventory分别的source配置。
- [x] tools/services只看到端口和capability，不按“是不是ERP”散落条件；domain公式复用。
- [x] 本地Mutation handler使用Mongo事务；远程handler先记录intent/批准绑定再调用HTTP，不能让ERP适配器绕过mutation入口。
- [x] 测试远程不可用返回503且无本地替代结果；混合模块返回各自source_refs；快照写明确405。

### P08-T02：23项工具和通用批准准备

**Files:** Extend `mcp_server/tools/{catalog,inventory,orders}.py`、registry、`services/approvals.py`；Create `tests/integration/test_tool_inventory.py`。
**Interfaces:** 按P08 spec的23名称；额外`mutation_prepare(action,payload)`复用批准展示；order_create/update仍用服务端草稿。

- [x] 定义每项的input/output schema、effect、allowed_actor/capability，注册描述和执行入口一处维护；quote_list等扩展不混入23计数。
- [x] 在contracts/approval.py新增MutationProposal(id,owner_id,run_id,action,payload,version,payload_hash,source_refs,state)，通用操作与订单草稿共用批准服务，但不把供应商新增硬塞成OrderDraft。通用proposal版本也参与resolve和事务内校验。
- [x] 供应商/物料新增、状态变更、库存动作先创建通用操作提案，approval绑定规范payload/hash/version；UI复用确认卡展示action摘要。
- [x] direct call任何写工具未批准一律拒；合法读调用查询真正数据。order_update只允许submitted，变更明细新草稿/新批准。
- [x] test inventory逐项执行正常和非法输入，核对DB效果，不仅assert len(tools)==23；类型/错误与HTTP一致。

### P08-T03：远程字段和分页映射

**Files:** Create `integrations/erp/mappings.py`、`docs/erp-mapping.md`、`tests/unit/test_erp_mappings.py`、`tests/fixtures/erp/*.json`。
**Interfaces:** map_part/supplier/inventory/order、yuan_to_cents、normalize_page；保留远程状态raw_status供诊断，不直接暴露未知状态供写入。

- [x] 从实际已授权只读响应或明确模拟样本建立字段表，标required/optional/unknown及单位；无响应不能假设Java内部框架或表结构。
- [x] Decimal把元精确到分，超过2位小数按明确规则拒绝而非默默舍入；ID转字符串，日期区间按上海自然日转换UTC。
- [x] 缺MOQ/交期/有效期返回unknown并缺失标记；需要7天交期的推荐不能因此假设0天。
- [x] total=0但records非空、重复分页或无可信总量时返回scope完整性警告；统计不能假称全量。测试这些异常及金额0.10→10分。

### P08-T04：收发货、改单和库存事务

**Files:** Extend `domain/inventory.py`、`services/inventory.py`、`repositories/movements.py`、contracts/ports；Create `tests/integration/test_inventory_receipts.py`、`test_inventory_failpoints.py`。
**Interfaces:** ReceiptInput(mode,order_id?,receipt_id,warehouse_id,items)，receive通过MutationService；Movement唯一键按共享契约。

- [x] 写固定状态断言：新增55件、发货、收20、收35、完成，inbound=65/65/45/10/10，on_hand=20/20/40/75/75，received_qty=0/0/20/55/55。
- [x] 单事务校验批准与版本、Receipt唯一、订单剩余数量/仓库/物料、更新库存/在途、写流水、更新收货/状态、消费批准、记operation成功；每一持久化步骤前后都有测试failpoint。
- [x] 同owner/provider/receipt_id换operation_id重试仍返回原收货或409；不同作用域同号不被流水索引误拒。采购超收拒绝；manual入库不扣inbound不推进订单。
- [x] submitted取消/改单调整未收inbound；shipped部分收货仍shipped，完整才received；普通状态工具不能直接跳过收货事实。出库不能低于reserved或0。
- [x] 并发+崩溃测试核对Receipt/Movement/Order/Inventory/Approval/Operation全部一致；旧P04下单幂等回归通过。

### P08-T05：ERP调用与结果未知对账

**Files:** Create `integrations/erp/client.py`；Extend reconciliation/remote mutation handler；Test `tests/integration/test_erp_outcome_unknown.py`。
**Interfaces:** `ErpClient.read(operation,params)`、`write(operation,payload,correlation_id)`、`lookup(correlation_id)`；远程能力缺失显式声明。

- [x] 读请求超时最多2次重试（总计最多3次请求），每次检查run剩余预算；写请求默认不自动retry。
- [x] 提交前记录持久intent、关联号、owner、payload hash和批准决定；成功回读匹配业务记录后存结果。响应丢失标outcome_unknown，不创建第二个关联号重来。
- [x] 对账按同correlation查唯一外部单：存在则核对金额/明细返回原单；权威证明未提交后才可继续；查询不支持/非权威空结果需人工核对，不把普通404当无副作用保证。
- [x] HTTP模拟器“已建单但响应断开”断言后续lookup找到同一ID且write只调用1次；区分DB未记结果与ERP实际成功。

### P08-T06：契约、本地完整与真实ERP验收

**Files:** Create `tests/integration/test_provider_contract.py`、`tests/live/test_erp_readonly.py`、`tests/live/test_erp_write.py`、`evidence/P08.md`。
**Interfaces:** 同一Provider契约用例分别绑定local与HTTP模拟器；真实ERP写只用于明确指定测试账号/环境/数据。

- [x] 本地23项、审批绕过、收货一致性和Provider切换全部通过；这些是P08本地交付必要条件。
- [x] 真ERP先只读映射核对，再在用户指定测试范围提交一单并回读；没有环境保留not_run，不能拿外部生产接口临时写数据补验收。
- [x] P08-A01..A07按类型记录离线/HTTP模拟/真实ERP；本地完成可交付并清楚标远程缺口，不伪称ERP完成。
- [x] 更新Provider/事务/ERP映射README与证据，上传并核对`phase-p08`，停止。
