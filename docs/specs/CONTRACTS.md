# 跨阶段共享契约

状态：P00–P07接口已有实现代码；P06独立审查7项缺口及前置残留见 [P06补修](../implementation/P06-followup.md)，Windows通过不代替Linux CI及产物整链验收。阶段验收和未关闭条件以STATUS及对应evidence为准。P03/P04/P05前置验收独立记录，P08–P09为拟定。P05契约包括查询级依据、原始请求、决定历史与跨恢复累计预算；P06新增artifact与sandbox契约；P07新增版本化专家委派与owner-scoped显式偏好。本文固定跨阶段接口/语义，不因已有标签而放宽审批、事务与恢复要求；内部辅助接口由实施者在此契约下决定。

## 1. 项目边界与目录

单组织、本机演示，默认一个操作人；自动化通过服务端测试身份注入验证两个用户隔离。正常 API 从服务端会话解析 `owner_id`，不接受请求体中的 user_id 作为身份依据。P00 创建本地会话，非本机部署的身份认证列为 P09 发布前条件。

P00 本机边界（P00-F01）：前端 dev/start 仅绑定 `127.0.0.1`，Uvicorn 以 `--no-proxy-headers` 启动；本地会话要求回环 socket peer、Host 属于配置的 API/前端端口，Origin 若存在必须是前端同源。Cookie 使用 `SameSite=Strict`，仅限本机开发。

P01 已实现接口（细节以代码/生成类型为准）：目录查询返回 Page；库存返回派生的 available/projected/shortage/warning；报价返回后端判定的 `is_valid`；preview 返回 `lines`、`snapshot_versions` 与 `SourceRef`。数据源为 `local_seed`，scope 为 `shared_catalog`。

P02 已实现接口：`POST /api/chat/stream`（SSE，首事件 run_started，末事件 stream_end）、`GET /api/conversations`、`GET/DELETE /api/conversations/{thread_id}`、`GET /api/runs/{run_id}`、`GET /api/runs/{run_id}/events?after_seq=N`、`POST /api/runs/{run_id}/cancel`。事件 schema 为 `events-schema.v1.json`/`frontend/src/lib/events.ts`；run 按 owner 隔离，同 thread 单活跃 run，request_id 幂等；P02 执行器明确为 FakeAgent，model_mode=fake。P02-fix1 语义：删除通过 thread 条件认领与创建互斥（运行中/删除中 409，删除后 404）；已有 thread 并发同 request 返回原 run；budget 在 run_started 前注册；SSE 终态后继续排空到 last_seq。

```text
technologyagent/
  frontend/src/{app,components,hooks,lib}/
  backend/app/
    api/                 # HTTP/SSE，调用应用服务
    contracts/           # 数据、请求、响应、事件 schema
    domain/              # 补货、金额、状态转换等确定性规则
    repositories/        # MongoDB、业务读写和唯一约束
    services/            # 对话、审批、幂等和业务协调
    agent/               # 图、工具循环、阶段评审和专家
    integrations/        # 模型、MCP、ERP 适配
    sandbox/             # 容器任务与文件收集
    skills/              # 受控的采购技能包
  mcp_server/            # 共享服务和契约，不重复实现业务规则
  fixtures/             # 仅合成数据，固定版本
  tests/{unit,integration,e2e,live}/
  scripts/              # 初始化、验证、兼容性检查
  evidence/             # 分阶段证据
  docs/{specs,architecture,delivery}/ # 规格、完整文件蓝图和阶段上传记录
  AGENTS.md             # 项目开发与阶段交付规则
  start.ps1 / stop.ps1 / compose.yaml
```

前端通过同源 `/api` 转发后端；后端与 MCP 调同一套业务服务。端口从配置读取。P00–P05 不要求 Docker 执行沙箱启动。MongoDB 从 P00 起采用 Compose 单节点 replica set，初始化并验证事务；本地业务写入依赖事务，不支持直接替换成 standalone。

## 2. 数据模型

ID 使用字符串；时间保存 UTC ISO 8601，页面按 Asia/Shanghai 展示；日期筛选定义为该时区自然日，转换为 UTC 半开区间。金额使用整数分，币种固定 CNY，禁止浮点累计；数量为整数，库存和订单数量区分零与正数。

| 实体 | 必备字段及约束 |
|---|---|
| Part | id、code 唯一、name、specification、unit、category、active |
| Supplier | id、code 唯一、name、status(active/inactive)、credit_rating(可空) |
| Quote | id、part_id、supplier_id、unit_price_cents>0、min_order_qty>=1、lead_days>=0、valid_until、currency=CNY |
| Inventory | id、part_id、warehouse_id、on_hand>=0、reserved>=0、inbound>=0、safety_stock>=0、target_stock>=safety_stock、version；reserved<=on_hand；part+warehouse 唯一 |
| OrderDraft | id、owner_id、supplier_id、warehouse_id、items、total_cents、version、state(draft/pending_approval/approved/rejected/superseded)、source_refs |
| OrderItem | part_id、quantity>=1、unit_price_cents>0、quote_id、line_total_cents |
| PurchaseOrder | id、number 唯一、owner_id、draft_id 唯一、supplier_id、warehouse_id、items（含 received_qty>=0）、total_cents、status、version、created_at |
| Receipt | id、receipt_id、owner_id、provider、order_id（采购收货必填）、warehouse_id、items[{part_id,quantity>=1}]、operation_id、created_at；(owner_id,provider,receipt_id)唯一，相同receipt_id换operation_id也不能重复收货 |
| InventoryMovement | id、owner_id、provider、inventory_id、operation_id、line_index、receipt_id?、order_id?、on_hand_delta、inbound_delta、reserved_delta、created_at；(operation_id,line_index)唯一，收货流水另有(owner_id,provider,receipt_id,part_id,warehouse_id)唯一，与Receipt作用域一致 |
| Approval | id、owner_id、thread_id、run_id、action、payload_hash、draft_version、decision、state(pending/consumed/rejected/superseded)、created_at |
| Conversation / Message | thread_id、owner_id、title；message_id、role、content、created_at |
| Run / Event | run_id、thread_id、owner_id、graph_version、status、phase、last_seq；事件见第 5 节 |
| ToolCall | call_id、run_id、parent_call_id(可空)、actor、name、参数摘要、status、duration_ms、error_code、source |
| Artifact | id、owner_id、run_id、kind、mime、filename、storage_key、source_refs、created_at |
| Preference | owner_id、key、value、source=explicit_user、updated_at |

MongoDB 用独立 collection 管业务数据、展示消息、run/events、审批、操作记录、偏好；LangGraph checkpoint 使用专门 collection。审批状态不等同于采购订单履约状态，页面历史不能充当检查点。

## 3. 固定业务规则和验收数据

初始化 `fixtures/v1/`：6 个零件、3 家供应商、8 条报价、8 条库存（6 个 SKU、2 个仓库），另有 2 张历史订单（draft_id 使用两个历史草稿）。其中一张历史订单为 P001/W01 未收货10件，为案例A的 inbound=10 提供依据；另一张已完成。全部为合成数据，初始化幂等，不覆盖已经产生的订单。

固定案例 A：P001 刹车片，在 W01 的 on_hand=20、reserved=5、inbound=10、safety_stock=30、target_stock=80。可用量=15、预计可用量=25；预警条件为预计可用量 < safety_stock；基础补货量=max(0,target_stock-预计可用量)=55。

S01 的有效报价Q01单价1200分、MOQ=10、交期5天；S02有效报价Q02单价1100分、MOQ=1、交期12天。S03报价Q03单价900分但已过期；测试时间固定为2026-10-23T02:00:00Z，有效报价valid_until=2026-12-31T15:59:59Z，过期报价valid_until=2026-10-22T15:59:59Z。valid_until等于当前时刻视为过期。

MOQ 只表示最小订购量，不表示包装倍数：建议数量=max(基础补货量,MOQ)。因此两家建议均为 55，S01 总额=66000 分，S02 总额=60500 分。无交期限制且选择价格优先时选 S02；要求 7 天内到货时选 S01。价格相同依次按交期、supplier_id 排序。默认每个零件只选一家，不做拆量优化；不同供应商或仓库分成不同订单草稿。同一订单不混供应商、仓库、币种和计量单位口径。

固定案例 B：P002 在 W02 的预计可用量=safety_stock，不预警；固定案例 C：P003 存在缺口但没有有效报价，只输出缺口和缺失信息，不生成可确认订单。其余库存为非预警项。汇总对 seed 中所有记录求和，不把分页结果当全量。

报价是否有效由后端以当前时间判断；测试注入固定时钟。确认前重查报价、供应商状态、库存版本；相关内容变更则原审批失效，重新生成待确认草稿。下单不自动增加 on_hand；确认新订单按数量增加对应仓库 inbound。发货不改变 inbound；收货数量同时从 inbound 扣除、加入 on_hand、增加订单行 received_qty；取消 submitted 订单扣除尚未收货的 inbound；改单按新旧未收数量差更新 inbound。以上变化同时增加库存version，并与订单/流水在同一事务提交。外部无订单关联的手工入库只加 on_hand，不扣 inbound。取消订单不删除已有流水；inbound必须可与未关闭订单未收货数量对账。

## 4. HTTP 与工具契约

普通响应：`{ok,data,error,meta}`；error 为 null 或 `{code,message,retryable}`。meta 至少包含 `request_id,data_source,as_of,scope`。业务金额保持分，展示除以 100。分页统一 `records,total,page,page_size,pages`，page>=1，1<=page_size<=100。数据源为 local_seed/local_snapshot/remote_erp；P00 无业务数据，系统接口使用 `data_source=none`；无结果不是工具失败。P00 本地会话错误码：`UNAUTHENTICATED/401`、`LOCAL_SESSION_DISABLED/403`；`/ready` 依赖失败使用 `DEPENDENCY_UNAVAILABLE/503`。

| 接口 | 关键请求 / 返回 | 首次交付 |
|---|---|---|
| GET /health | 服务存活；不泄露配置 | P00 |
| GET /ready | DB、MCP、model、sandbox 能力状态；未启用模块为 disabled | P00 增量扩展 |
| POST /api/session/local | 仅 localhost 开发模式，建立服务端固定身份会话；请求体 owner_id 被忽略 | P00 |
| GET /api/session/me | 从 Cookie 解析可信 owner_id；无/无效 Cookie 返回 401 | P00 |
| GET /api/inventory、/warnings、/summary | 筛选、分页、汇总、数据范围 | P01 |
| GET /api/parts、/suppliers、/quotes | name/part_id 等明确筛选 | P01 |
| POST /api/replenishment/preview | part_ids、warehouse_id、max_lead_days? → 缺口、候选与推荐 | P01 |
| POST /api/chat/stream | thread_id?、message、request_id → SSE，首事件返回 thread_id/run_id | P02 |
| GET /api/conversations | 当前操作人的会话列表 | P02 |
| GET/DELETE /api/conversations/{thread_id} | 详情及删除；运行中删除返回 409 | P02 |
| GET /api/runs/{run_id} | 当前状态、可用操作、待审批数据 | P02 |
| GET /api/runs/{run_id}/events?after_seq=N | 按 seq 重放事件 | P02 |
| POST /api/runs/{run_id}/cancel | 停止调度；执行中的副作用按第 6 节对账 | P02 |
| POST /api/drafts | 业务服务校验、创建草稿，返回缺失字段或有效草稿 | P04 |
| GET /api/drafts、GET /api/drafts/{id} | 当前操作人草稿列表/详情 | P04 |
| PATCH /api/drafts/{id} | expected_version、变更字段 → 新版本；旧审批失效 | P04 |
| POST /api/order-workflows | 以请求 ID 幂等启动持久化补充/确认工作流 | P04 |
| POST /api/runs/{run_id}/resume | interrupt_id、decision(approve/reject/edit/supplement)、expected_version、payload?、idempotency_key | P04 |
| POST /api/drafts/{id}/approval；POST /api/approvals/{id}/resolve | 创建绑定版本/hash 的人工决策并记录 approve/reject | P04 |
| GET /api/orders、/api/orders/{id} | 分页/订单详情及真实状态 | P04 |
| POST /api/orders/create | 只接 draft_id/approval_id/idempotency_key，走 MutationService | P04 |
| POST /api/operations/{id}/reconcile | owner-scoped 核对操作结果，不自动执行新写入 | P04 |
| GET /api/artifacts/{artifact_id} | owner授权的下载响应 | P06 |
| GET /api/artifacts/{artifact_id}/preview | owner授权的PNG预览；文本产物以下载方式打开 | P06 |
| GET/PUT/DELETE /api/preferences/{key} | 白名单偏好及重置 | P07 |

前端 request_id 对消息请求去重；同一 thread 同时只允许一个 active run（running/waiting_input），第二个请求返回 409，不做隐式排队。等待审批期间通过 resume 继续，不能另开运行覆盖审批。

P04-fix1 补充：`GET /api/drafts` 与详情为工作流草稿附加只读 `workflow={run_id,thread_id,status,pending_interrupt}` 元数据。订单页对这类草稿必须调用所属 run 的 resume；独立草稿仍使用草稿/审批接口。启动订单工作流的幂等 hash 覆盖完整请求体，live 意图模型只在 run 成功认领后调用。

resume 在原子认领时持久保存 `resume_request`（idempotency_key、request_hash、interrupt_id、decision、expected_version、payload），再清除 pending interrupt 并继续同一 run/checkpoint。相同 key/hash 的重放返回原 run 结果；相同 key 换 payload 返回 409。无效 edit/supplement 在认领前校验，保留当前 interrupt 供修正。

业务工具名采用参考项目命名。P03 首批：inventory_page、inventory_warning、inventory_get、supplier_query、supplier_get、part_search、part_query，加本项目 quote_list、replenishment_preview。P04 增加 draft_prepare、order_create、order_get、order_page；order_create 仅接受 draft_id、approval_id、idempotency_key，并由业务服务验证，禁止模型直接提交任意金额 JSON。

P03 已实现 9 个只读 MCP 工具，工具参数不含 owner/run；模型/工具通过每 run 短期 Bearer token 绑定上下文。P03 尚无订单写工具。工具调用流按供应商稳定 index 合并并要求合法终止；assistant 正式 token 仅在数值事实校验通过后发布。历史消息用其所属 run 的 `model_mode` 元数据标注，旧消息缺失时为 unknown。

P08 补齐参考 23 项工具，名称见 P08。MCP schema 使用结构化对象，输出遵循统一响应；适配旧 ERP JSON 字符串属于适配器职责。未实现或当前数据源不支持的写操作返回 UNSUPPORTED_OPERATION，不能伪装成功。

## 5. 事件与状态

SSE 事件封装：`{schema_version:1,type,event_id,seq,thread_id,run_id,at,payload}`，SSE `id` 为 event_id；按 run_id 的 seq 从 1 递增，先持久化再发送。前端按 run_id+seq 去重。每个流均产生 `stream_end`，不等同于任务结束。

| type | payload 必备内容 |
|---|---|
| run_started | status、thread_id、run_id、model_mode(fake/live) |
| token | message_id、delta、actor |
| tool_started | call_id、name、actor、args_summary |
| tool_finished | call_id、status(success/error)、result_summary、source、error? |
| interrupt | interrupt_id、kind(approval/supplement)、draft_id?、version?、fields?、summary |
| phase | phase(planning/executing/reviewing/result)、iteration、task_type、revision_count |
| plan | task_type、request_constraints(用户仓库/物料/交期筛选，不是观测事实)、items[{id,title,status(pending/running/done/failed/skipped),evidence_refs,query_evidence,required_action}]、evidence_refs |
| review | passed、checks、revision_count、details[{check_id,kind,reason,evidence_refs}]、result、incomplete_items |
| artifact_ready | artifact_id、kind、filename；mime/source_refs为可选字段 |
| error | code、message、retryable |
| run_finished | status(completed/failed/cancelled)、summary、review_passed?、committed_facts? |
| stream_end | reason(completed/failed/cancelled/waiting_input)、last_seq |

Run.status：created → running → waiting_input → running → completed/failed/cancelled。waiting_input 持久化后关闭当前 SSE，resume 开新流继续同一个 run_id，并递增 seq。phase仅表示工作阶段，可为null；waiting_input保留executing，不视为结果。RunView同时快照task_type、plan、evidence_refs、review、revision_count、summary和committed_facts。QueryEvidence区分成功查询与实体引用；参数范围和total可证明查过，即使total为0，但不能据此支持实体数值。原始用户请求不可被candidate_answer覆盖。决定历史按run/interrupt/idempotency_key保存canonical hash与结果，旧键重放不能被后续决定覆盖。模型最多修订2次/评审3次，且共享RunBudget；确定性事实/来源/范围/审批检查失败时语义评分不得放行。订单提交后的说明评审只查询orders/operations/approvals事实，不能重放写入；终态保留已提交事实，即使说明评审失败。活跃秒数跨恢复累加，waiting_input期间暂停。stream_end后查询run状态，不能把流关闭当任务成功。

P06-fix2在计划事件中增加`request_constraints`，将用户仓库/物料/交期上限与工具观测分开。QueryEvidence补充服务端页码、页数、每页记录ID；多页范围只有页齐全且不同记录数达到total才算完整。目标补货检查覆盖目标库存正缺口；安全预警单独由`inventory_warning`查询，不互相代替。指定交期推荐必须有同一物料/仓库且带`max_lead_days`的`replenishment_preview`证据。

P04 订单工作流的 waiting_input 可取消：取消将 run 置为 cancelled、清除 pending interrupt 并释放 thread；已提交的订单事实不回滚，run 返回已提交订单结果。resume/提交窗口发生故障时，启动恢复对照持久决定、checkpoint 和 operation 记录；若 operation 已提交则返回同一订单，若尚未提交则按原决定恢复。不得创建新幂等键掩盖未知结果。

断线只代表观察连接关闭，不自动取消业务任务。刷新先查询 run，再重放缺失事件。P02 采用 REST 查询 run/events，每 2 秒检查 active run，恢复后停止轮询；无需实时重新订阅也能补全结果。完整历史以持久化消息为准，禁止重放 token 后又重复追加最终消息。

## 6. 审批、幂等与写入一致性

审批绑定 owner_id、run_id、action、draft_version、payload_hash（规范化 JSON 的 SHA256）。编辑、数据变更使旧审批 superseded；拒绝不执行；批准必须与用户看到的草稿一致。审批和字段补充在有持久化 checkpointer 的节点执行，副作用放在审批之后的独立节点。LangGraph 恢复可能重跑节点，业务幂等不可省略。

P04-fix1 的审批决定另保存 `decision_key` 和 `decision_payload_hash`；同一决定键和内容重放返回原决定，不同决定或内容冲突返回 409。workflow-owned draft/approval 的独立 PATCH/resolve 写路径拒绝绕过 run resume。一个 run 可依次确认多张供应商草稿，每张 interrupt 绑定草稿 id 与 version；拒绝/批准结果汇总后才终结 run。

所有修改业务数据(domain_write)的工具通过统一 `MutationService.execute(action,payload,approval_id,idempotency_key,owner_id)`；参数先做Pydantic与业务校验，直接调HTTP/MCP也不能绕过审批。报告产物写入和沙箱执行分别受owner/资源边界约束，不属于采购业务批准。同意只允许服务器消费审批，不向模型提供可自签的批准字段。

本地通过 operation 唯一(owner_id,action,idempotency_key)、业务文档operation_id和PurchaseOrder.draft_id唯一约束，保证重复执行最多产生一次业务效果。先原子认领operation，再在MongoDB事务内校验审批及数据版本、写业务文档、更新库存/在途量、写流水、消费审批并保存operation结果。库存收货还要在同一事务更新订单行received_qty；事务任一失败全部回滚。认领后崩溃或提交响应丢失时，reconcile先查询operation与业务operation_id：已提交返回原结果；未提交且处理租约失效才允许重新认领；状态未确认不重试。采用120秒认领租约和至多15秒的本地事务执行时间，续约/重试仍受run预算限制。不得用单文档upsert替代跨集合事务。

事务写入需在订单、库存、审批消费与 operation 成功结果落库前再次条件确认 `lease_owner`、processing 状态与租约有效期；旧租约执行者失去事务内竞争时整笔回滚，`mark_succeeded` 未匹配 operation 时不能报告成功。订单提交边界同时条件检查 run 的 `cancel_requested`，并在同一事务写入提交栅栏；取消与提交竞争由事务顺序决定。

对同一个 idempotency_key 不同 payload 返回 409；并发相同请求返回已知结果或 processing；外部请求超时后标为 outcome_unknown，按关联号查询对账，确认未提交前不自动重试。cancel 停止后续调度；已提交操作不回滚，正在执行且效果未知时显示“正在核对”，核对结束才允许重试。

订单状态：submitted → shipped → received → completed；submitted 可 cancelled，其余不允许倒退。确认下单创建 submitted；供应商审核不等于系统人工确认。入库使用唯一 receipt_id+operation_id；最后一笔完整收货才允许标记 received；普通状态更新工具不能绕过收货事实。部分收货保持 shipped 并返回已收/未收数量。库存出库不得低于 reserved，也不得产生负库存。

采购收货必须传order_id、receipt_id、warehouse_id与明细，不得超过订单未收数量；一张Receipt的同part合并为一行。手工入库显式mode=manual、无需order_id，单独审批且不能用于推进采购单收货状态。重传相同receipt_id且明细相同返回原收货结果；相同receipt_id但明细不同返回409，换idempotency_key或operation_id不能增加入库数量。

图升级采用版本路由，不原地强行加载旧检查点：P03起Run保存graph_version=v1；P07创建v2图，新的run使用v2，未结束的v1继续由保留的v1图/状态schema恢复；按run.graph_version选择图和checkpoint namespace，恢复不能更换版本。所有旧run终结且备份保留期满足后才能移除旧图，升级说明记录仍在运行的版本。会话可保留旧消息；新run不把旧版本checkpoint当新图输入。

P07委派请求的owner_id/run_id由可信服务上下文提供，模型只能提供task和受限范围；结构化`evidence_refs`跨专家传递，子任务使用父run同一预算，最多两次、不递归。专家YAML声明输入/输出schema、工具和技能白名单；运行时Registry再次校验工具调用。v2的`analysis_execute`仅分析actor可见并可调用。偏好只允许default_warehouse、preferred_supplier、max_lead_days，必须显式记住；本轮明确字段优先且不绕过报价和审批。

## 7. 有界执行与产物

默认每 run 模型最多 20 次、工具最多 30 次（含子 Agent），模型请求 60 秒、读工具 15 秒，run 活跃执行累计 180 秒；等待人工输入不计入执行时间。评审最多 2 次修订（三次检查），子 Agent 最多委派 2 次且不递归。调用上限优先于自动重试，预算耗尽给出具体未完成项，不能标成功。

产物只通过 artifact_id 下载/预览，不能让浏览器提交磁盘路径。读取验证 owner；用户文件名仅为展示。P06 默认单容器任务超时 30 秒、内存 512MiB、CPU 1、pids 64、输出总量 20MiB；执行用户非 root，根文件系统只读，仅限额tmpfs临时工作区可写，无宿主目录挂载、无Docker socket、禁网。失败时不能自动退回宿主机shell执行。ArtifactReady事件只在文件校验、原子落盘与元数据登记成功后发出。

## 8. 完成记录

每阶段 evidence 文件字段固定：status(planned/implemented/offline_verified/live_verified/browser_verified)、commit_or_files、environment、commands_and_exit_codes、expected_vs_actual、model_mode(fake/live)、data_source、browser_steps、artifacts、known_gaps。允许多个验证状态并存；未执行项写 not_run。功能截图不能代替数据断言，模型回答不能代替数据库写入核对。

每阶段额外完成工程交付任务：新增/修改模块的中文README、接口/布局变更说明、相称检查、evidence、显式路径暂存、commit、push、远程SHA核对与阶段标签推送。详细步骤以 `docs/delivery/GIT_WORKFLOW.md` 为准。检查通过但推送失败只能标记“本地完成，远程未交付”，不得勾选阶段交付或继续叠加下一阶段提交。初始蓝图提交命名为 `docs: establish greenfield architecture and staged specs`，不计作P00完成。

具体实现方法签名、配置默认值和任务级测试见`docs/implementation/INTERFACES.md`与各阶段计划；它们补充本契约，不允许改写本契约的数量、金额、审批和数据源语义。规划者只维护文档，产品实施由用户选用的其他Agent执行。
