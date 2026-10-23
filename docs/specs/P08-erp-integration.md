# P08：完整业务工具与真实 ERP 适配

状态：待实施。依赖：P07。目标：补齐参考项目四类业务能力，保留本地独立运行，并为真实ERP提供可验证适配。

## 任务

- [ ] **P08-T01 Provider接口。** `integrations/business_provider.py` 定义供应商、零件、库存、订单方法，`local_provider.py`与`erp_provider.py`实现；启动配置每模块data_source，单次run记录各模块来源，不允许远程失败时静默切到本地。本地快照模式的写能力显式unsupported。
- [ ] **P08-T02 补齐23项工具。** 按下表注册工具及schema，所有本地工具真实实现；quotes与补货为本项目扩展，不计入参考23项。写工具全部复用MutationService与审批，不把“注册成功”当“功能成功”。
- [ ] **P08-T03 ERP字段映射。** `integrations/erp/mappings.py` 映射ID、订单明细、金额、状态、分页；金额元→分用Decimal精确转换。根据接口实测建立`docs/erp-mapping.md`；报价MOQ/交期/有效期若远程缺失返回unknown，不编造。报价可明确来自本地补充表，但结果必须说明混合来源。
- [ ] **P08-T04 订单生命周期与库存。** 本地实现供应商/零件新增、状态变更、采购改单、收发货与库存流水；order_update生成新的变更草稿，批准后按expected_version执行；submitted之外不允许修改明细。使用共享事务同时校验并更新operation、审批、Receipt、库存数量/inbound/version、InventoryMovement、订单received_qty/status，异常全部回滚；receipt_id唯一校验不能被更换operation_id绕过；实现收货前后及取消/改单的在途量对账。
- [ ] **P08-T05 远程调用和对账。** `integrations/erp/client.py` 配置鉴权、超时，读取最多重试2次且不超过run预算；写入不盲重试。按ERP能力使用幂等键或业务关联号查订单；不能查询唯一结果时标outcome_unknown，人工核对后才能重试。
- [ ] **P08-T06 三类验收。** `tests/integration/test_provider_contract.py`对本地和HTTP模拟器跑同一契约；真实ERP先执行只读联调，写联调只在明确配置的测试环境/账号/数据范围完成并核对持久结果。没有测试ERP时保留not_run，P08本地部分仍可独立验收。

## 参考23项工具覆盖表

| 模块 | 工具名 | 关键验证 |
|---|---|---|
| 供应商5项 | supplier_query / supplier_page / supplier_get / supplier_create / supplier_update_status | 查询分页正确，重复code拒绝，停用供应商不能新下单 |
| 零件5项 | part_query / part_search / part_by_supplier / part_page / part_create | 外键有效，单位明确，重复code拒绝 |
| 订单7项 | order_create / order_update / order_page / order_get / order_search_details / order_statistics / order_update_status | 有审批和版本检查，统计不漏页，非法状态转换拒绝 |
| 库存6项 | inventory_warning / inventory_page / inventory_check / inventory_inbound / inventory_outbound / inventory_get | 库存数量正确，流水幂等，不出现负库存 |

order_create沿用P04草稿接口，order_update接受变更草稿；其余写工具也先通过统一`mutation_prepare(action,payload)`生成可展示批准的操作，再执行。既有业务名称相同，不要求与参考项目内部JSON字符串签名相同。

## 验收

| ID | 操作 | 通过条件 |
|---|---|---|
| P08-A01 | 枚举schema并执行本地23项契约测试 | 数量/名称正确，每项至少有正常与非法输入断言，写入核对数据库 |
| P08-A02 | 未批准直调任一写工具 | 一律无业务效果，包括供应商、零件和库存写操作 |
| P08-A03 | 同一出入库操作并发重复提交；同owner/provider/receipt_id换operation_id再次入库；不同owner或provider使用同号receipt；在库存/流水/订单写入间注入崩溃 | 全部提交或全部回滚，流水与库存只改变一次；同作用域重复receipt返回原结果或409；不同作用域合法收货不被索引误拒绝；超可用库存出库拒绝 |
| P08-A04 | 新增P001订单55件→发货→收20→收35→完成；另测试submitted取消/改单 | inbound依次65/65/45/10/10，on_hand依次20/20/40/75/75；订单received_qty为0/0/20/55/55；取消/改单按未收数量调整inbound；未收全不能received |
| P08-A05 | 远程超时、total错误、元金额、未知状态 | 展示真实来源与明确错误；已知分页异常不声称全量；金额精确，未知状态拒绝写入 |
| P08-A06 | 测试ERP中创建一单，模拟响应丢失 | 根据关联号找到同一单，不重复创建；无法确认则outcome_unknown |
| P08-A07 | 报价缺MOQ/交期，用户要求7天到货 | 明确缺失交期，不能保证达标；不伪造推荐依据 |

## 本阶段结束后

本地具备参考项目四类业务工具的完整闭环。真实ERP只在对应读取/写入测试完成后标记通过；外部接口不支持必要查询或字段时，记录能力缺口，不把模拟器通过写成真实系统已接通。

## 阶段 Git 交付

- [ ] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [ ] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [ ] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p08` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [ ] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
