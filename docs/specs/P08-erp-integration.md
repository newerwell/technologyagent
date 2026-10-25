# P08：完整业务工具与真实 ERP 适配

状态：本地实现、offline与P08专属browser验收通过；真实ERP `not_run`，远程字段/写能力未实测。依赖：P07。目标：补齐参考项目四类业务能力，保留本地独立运行，并为真实ERP提供可验证适配。实施范围、固定事务值、检查结果和外部限制见[evidence/P08.md](../../evidence/P08.md)。

## 任务

- [x] **P08-T01 Provider接口。** Provider按供应商、零件、库存、订单模块声明来源与能力；`local_seed`、只读`local_snapshot`与`remote_erp`独立配置，远程失败不回退本地。
- [x] **P08-T02 补齐23项工具。** 23项实际MCP工具与P08注册表schema一致；逐项执行只读或未批准写拒绝，并拒绝未声明输入；通用提案使用owner-scoped批准服务。`quote_list`与补货扩展混合远程源时明确失败。
- [x] **P08-T03 ERP字段映射。** ID、明细、金额、状态和分页适配完成；Decimal精确换分；未知状态与缺MOQ/交期/有效期不编造。由于没有真实ERP响应，`docs/erp-mapping.md`字段别名标记为待验证候选。
- [x] **P08-T04 订单生命周期与库存。** 供应商/零件、状态、改单及收发货写均需批准、版本和幂等检查；采购收货时Receipt、Movement、库存、订单已收量/状态、批准与operation在同一Mongo事务；故障注入全部回滚；receipt更换operation不能重复收货；取消/改单的inbound对账通过。
- [x] **P08-T05 远程调用和对账。** 读取至多3次并可检查剩余预算；写只发一次，超时为`outcome_unknown`，关联号查询与普通404处理保留不确定性。真实ERP写能力未验证，保持关闭。
- [x] **P08-T06 三类验收。** 本地Provider/HTTP模拟器、23项MCP、固定事务、offline与P08 browser检查通过。真实ERP无明确测试端点/账号/范围，本轮按`not_run`记录。

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

- [x] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。真实ERP无测试环境，本轮记录为`not_run`。
- [x] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [x] 提交本阶段源码、测试、文档和证据，推送到`origin/main`；创建并推送`phase-p08`标签；按`docs/delivery/GIT_WORKFLOW.md`核对远程SHA。
- [x] 向用户报告结果、实际检查、commit链接及阶段标签。真实ERP不宣称已接通。
