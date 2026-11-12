# agent 执行器、Harness、评审与订单恢复图（P03–P05）

## 工具消息体积

`tool_messages.serialize_tool_result(call, result)`供主图、独立v1/v2图生成模型工具消息：保留全部业务data、error、分页、snapshot、dataset、来源及时间元数据，仅不向模型重复发送服务器派生的`meta.evidence_refs`。原ToolResult不修改，完整事实仍用于plan/review。72条合成库存的消息上限由原data字节数加固定元数据余量验证；不截断记录、不把缺字段补0。回归：`tests/unit/test_tool_message_size.py`。

语义评审请求将重复的来源列表提取为`source_ref_groups`，每条事实通过`source_ref_group`引用原列表；完整事实、值、单位、报价/供应商scope与来源都保留。该表示仅用于模型请求，原state、持久review_input和确定性检查不变。新提示词版本为`ta-v2-base-2`、`ta-semantic-review-2`；快照缺目标字段时完成分页后诚实说明未知，不承诺仅换仓库就能获得缺失报价。历史缓存探针属于旧提示词，不能冒充新版本收益。

## P09 review 输入回放

`review_snapshot.make_review_input_snapshot` 将主图/harness实际评审候选和本轮FactIndex转成严格、无raw字段的review事件快照；`harness.publish_review` 每轮调用它，保留原请求与已保存约束。数值以Decimal十进制文本精确写入，bool保持bool，非有限数值拒绝。订单流程复用`OrderWorkflowService._build_order_review_fact_index`构建原有持久订单事实，并在每个review事件保存当轮正文；事件仍由既有owner授权run/events接口读取，不新增诊断路由。旧v1 review事件可不带review_input。

P09 L07新增的`quote_id`作为可选事实键保存，用来把正式报告/回复中的报价编号和金额、交期绑定；没有报价ID的旧review快照仍兼容。报价列表和补货预览重复返回同一报价时，事实身份按报价、字段、物料、供应商与单位合并；预览中的仓库范围仍用于回答约束，另一报价编号或不匹配数值仍拒绝。P09离线pytest临时根按`P09_EVIDENCE_BATCH`生成独立目录，避免清理历史批次目录。

## 职责

- `budget.py`：`RunBudget` 检查 cancel/活跃 deadline，向模型、MCP 发现与工具调用提供剩余时限，并对调用做原子计数（DB counter）。
- `graph.py`：P03只读工具图与P05外层Harness；工具调用先收齐，计划按成功事实更新，最终正文暂存到硬校验和语义评审通过后才发 `token`。
- `state.py`：`AgentStateV1` 增量字段兼容旧状态/checkpoint；Run.status仍由RunService维护。
- `harness.py`：任务分类、结构化计划、阶段机、来源驱动计划更新、phase/plan事件发布与签名去重；最多2次修订。
- P05补修：每个运行持久原始请求；查询计划用 `QueryEvidence`（工具、call_id、参数范围、时间与total）完成，空页不伪造实体；失败步骤可以在真实重试后转为done。累计活跃预算从Run持久字段继续计算，审批等待期间暂停。
- `review.py` / `rubrics.yaml`：确定性数值/范围/来源/计划/审批订单核查，再用无工具模型调用检查语义遗漏；模型结果只能增加失败，不能覆盖硬失败。
- P09剩余工作R2：主图与语义评审统一调用`collect_model_response`；每次重试各自计入共享模型预算和trace。仅首delta前传输中断/超时允许重试一次，逻辑期限不重置；主图工具`parent_call_id`指向成功尝试。
- `evidence.py`：保留 call_id、记录引用、字段/值/单位、实体范围与 as_of；按结构化 claim 校验正式回答中的字段、数值、单位和业务结论，校验通过前正文只缓冲不发布。
- `fact_checks.py`：P06-fix2共用字段校验；金额精确到分，数量/天数要求整数，答案字段按表头和相邻分句绑定，跨实体同值在未说明范围时判为歧义。重复呈现的同一业务范围事实合并，库存预警数、目标缺口和用户交期上限保留独立字段。
- P09 L02：正式回答字段只从当前表格单元格或局部子句识别；表头决定字段、当前行标识列决定实体范围。只有明确的预警数量表达才识别为 `warning_count`；采购“要求”不再被误判成交期上限。相邻行和同一行的多物料分别绑定，只有紧邻的纯实体标题可向下一行继承范围。系统提示按物料来源单位作答，未知单位明确标未知。确定性失败跳过语义模型且正文不发布；保留原始请求、辅助事实和模型修订边界。定向结果见 `evidence/P09-L02.md`。
- P06-fix2任务范围：Harness从原始请求提取仓库、物料、交期上限和目标意图，随plan事件保留为`request_constraints`；交期筛选必须有匹配`max_lead_days`的`replenishment_preview`参数证据。目标缺口回答需有完整页集并逐项覆盖正缺口；`inventory_warning`只满足安全预警问题，不可替代目标缺口查询。
- P09 A2来源目录范围：请求解析可接收只读`source_directory`（来源实际仓位标签和物料ID），用精确最长标签匹配解析中文名、连字符和数字后缀；未知的明确仓位会以`warehouse_scope_unverified`失败关闭。GraphExecutor与v2入口使用同一可信目录，不从用户/模型参数接收目录。明确全仓清空单仓过滤，数字物料ID仅按明确编号识别，不给原ID加前缀。目录不可用时，无仓位限定的一般库存查询仍可继续；命名仓位或W编号不能被当作已验证范围。
- P06-fix2补验收：供应商推荐/最便宜问题分类为`supplier`计划；带交期上限时保存筛选参数查询证据。`verified_answers.py`只在同范围查询完整、服务返回明确推荐报价或完整报价集合确认无有效报价时，按具名字段生成库存/报价事实核心，并标注来源和观察时间。布尔报价/预警事实按类型和实体核对。证据缺失、冲突或实体不明确时不生成正文，仍由硬评审拒绝；自由正文不能覆盖渲染核心事实。
- `scripted_model.py`：fake/测试用 ScriptedModel 与明确标注的 DemoScriptedModel。
- `local_tools.py`：fake/离线测试使用同一业务 handler 的本地 registry；生产 live 走 MCP。
- P09 L01：fake registry复用bootstrap注入的Catalog与Replenishment服务，不另建系统时钟实例；验收固定业务时钟只影响报价有效性和补货判价，工具结果`as_of`仍取系统时钟。
- `fake_executor.py`：保留 P02 FakeAgent 历史实现，不再由 bootstrap 生产装配。
- `tools/analysis.py`：P06 `analysis_execute`只接收当前registry成功只读结果派生的数据集，或经同owner/run校验的已登记产物；Docker执行和产物登记失败返回工具错误，不运行宿主shell。
- P04 `checkpoints.py`/`order_nodes.py`：稳定节点 prepare/supplement/approve/submit v1，以 `(thread_id, checkpoint_ns=run_id)` 保存 Mongo 持久检查点。

## P07 版本路由、专家与技能

- `graph_versions.py`：旧run按持久 `graph_version` 继续走v1；新run固定v2。父run合并owner偏好与本轮约束后，按分析、订单查询、订单准备及否定范围路由；工具参数和评审使用同一有效范围。组合最多两次委派并传结构化分析证据，仍共用父run模型/工具/时限预算。
- `deepagent_adapter.py`：检查锁定的DeepAgents版本及工厂能力。锁定版默认带有项目禁止的内置工具，且不兼容当前ModelPort/事件/中断边界，因此本阶段选择具名LangGraph子图，不开启DeepAgents默认工具。
- `specialists/`：YAML列出目标、工具白名单、输入/输出JSON Schema及不递归/不自批规则；`RoleToolRegistry`在工具发现与调用时双重校验。
- `skill_loader.py`：只从仓库固定 `skills/` 根目录加载任务所需技能，返回版本、正文与示例SHA-256；run保存hash清单供追溯。
- `request_intent.py`：确定性区分明确记忆命令、本轮覆盖、分析、只读订单查询、订单准备和否定；纯订单不会制造空分析任务，查询不创建草稿。
- 组合请求明确要求报告文件时，analyst提示必须使用当前run只读查询数据调用 `artifact_report`；`artifact_ready`仅表示文件登记，父路由要求同run持久 `report_verified`（正文、格式、范围、来源核验通过）后才允许继续订单准备。只有文本摘要或任意普通产物时以 `REPORT_ARTIFACT_REQUIRED` 失败。
- `versions/v1.py` / `versions/v2.py`：通过独立的 `v1_impl.py`、`v2_impl.py` 与版本化订单图构建器分流执行；GraphExecutor和OrderWorkflowService按持久`graph_version`选择builder。v1保持旧状态schema、订单节点名、thread key和`checkpoint_ns=run_id`；新v2订单图用独立thread namespace。安全业务服务仍共享当前实现，避免旧版本复制写入逻辑。
- P09 R4/A3回归：固定旧待审批checkpoint fixture字节hash；测试专用v2包装图新增`v2_probe`状态字段、节点及经过的START→probe→原v2图→状态核验边，并经真实chat执行入口验证节点事件/字段读回。保持该v2 builder替换时旧v1审批恢复和重复恢复，核对只产生一张订单/一个成功operation、库存事实正确、旧v1 checkpoint原始文档内容不变；新v2订单图使用独立checkpoint thread key。证据见`evidence/P09-A3.md`。真实`ta-rs`是此Mongo验证前提。
- P07-fix1补验收：明确报告请求要求analyst调用`artifact_report`，并由父run核对同run持久`artifact_ready`；缺失时`REPORT_ARTIFACT_REQUIRED`阻断后续订单准备。P07最新offline为199 unit/181 integration/38 frontend；fake browser 12/12，下载API字节5/5。新P03 live 3×3为2/9；P07 live因模型未生成报告文件而失败，严格验收未关闭。
- P09-fix1回归：显式报告请求在analyst语义/确定性评审通过后核对同run `artifact_ready`；若模型漏调`artifact_report`，服务端仅从本run成功查询的授权dataset补生成Markdown并登记，未见登记事件即失败，因此父路由不会先启动订单准备。P09实时记录摘要直接索引含唯一attempt后缀的`evidence_path`。
- P09偏好保存是无模型的确定性命令：写入后同owner读回匹配才发出`PREFERENCE_PERSISTED`通过评审并完成run；后续查询的计划约束、查询参数与最终`NUMERIC_MATCH`/`REQUEST_CONSTRAINTS`评审共同证明默认仓库范围及缺口事实。供应商oracle按同一报价/供应商局部语句判断，不因相邻的有效推荐和无效排除产生误报。
- P09-fix3：正式报告数据集必须与用户完整筛选/排他范围精确匹配；库存页、库存预警和报价分页只有覆盖完整且同一来源快照的页集可发布。正文按服务端事实重建、实际打开回读；范围不匹配不得产生`report_verified`。
- P09-fix3事实回归：订单正文支持“片”等业务单位，并将带千分位的分值与持久订单总额按字段、单位、单号范围精确核对；不能用`包含某个数字`替代金额校验。
- 使用例：`route_executor(executor, request, sink, budget)`。`analysis_execute`只在v2 analyst actor可用；订单专家仍通过订单工作流和人工审批写入。

详细白名单、schema格式、错误和兼容限制见[专家模块说明](specialists/README.md)及[技能说明](../../../skills/README.md)。

验证：`uv run pytest tests/unit/test_p07_specialists_skills.py tests/integration/test_graph_upgrade.py tests/integration/test_specialists.py -q`。

## 调用

```python
executor = GraphExecutor(model, registry_factory, model_mode="live")
outcome = await executor.execute(ExecutorInput(...), sink, budget)
```

## 边界

- 只读图只有 model/tools 两个节点；P04订单图维持原稳定节点名与Mongo checkpoint协议。P05不新增模型可调用的写工具。
- 模型工具参数按供应商 index 收齐后才 JSON/schema 校验；只有 `stop`/`tool_calls` 属正常结束，提前 EOF、`length`、`content_filter` 和错误结束均失败，部分正文/参数不会作为成功结果执行或发布。
- 结构化数值校验覆盖明确的数值/单位/字段/实体与工具事实，也检查缺货事实和最终库存结论是否矛盾；不声称替代 P05 全面的自然语言语义评审。
- P09 L07 复现补充：数字主张的局部上下文在中文括号处切分，避免“缺口36个（可用4个）”把缺口绑定为可用量；库存记录聚合数与在手量分开识别；“最晚交期”映射为请求上限。报价实体支持Q编号scope，报价起订数量只有在同报价、同物料的`part_unit`证据匹配时才接受业务单位；报价本身未按仓位建模时允许在同物料/供应商范围下携带仓库请求上下文。缺少或冲突的单位、物料、供应商仍拒绝。主提示要求不输出没有对应工具聚合字段支持的总数。
- P09 L07 新一轮 live 保持事实门禁严格：仅明确否定“订单已提交/已批准”的文案不会触发只读订单写入误报；表格单元格按最近的字段标点与括号上下文绑定事实，括号内业务单位可用于数量核验；供应商拒绝提示不会把无效供应商身份传播到后续独立的条件/说明段。2026-11-09 固定 live 仍发现 P03 数字/范围/答案覆盖失败和一次工具循环 `KeyError`，以及 P07 专家流程的语义评审失败；详见 `evidence/P09-L07-process-cleanup.md`，不得以这些工具级修复宣称 live 门槛通过。
- 语义评审只接收筛选后的工具事实与白名单订单/operation/approval字段；日期时间数字不按库存数值校验。订单单号与数据库ID分别传递，避免把引用ID误判为对外单号。
- 模型 60s、读工具 15s、活跃 180s、模型 20 次、工具 30 次；失败调用也计数。
- 断线只关观察 SSE；ChatService 的任务继续写持久事件。
- waiting_input 持久化 interrupt，resume 校验 owner、同 run、interrupt_id 与草稿版本；编辑会 supersede 审批并回到确认节点。
- 图节点恢复可能重跑；订单写入只由 MutationService 在事务内执行，业务幂等不可省略。
- phase规划/执行/评审/结果与Run.status分开；等待审批保留executing + waiting_input。失败run即使phase=result，UI仍显示失败。
- P09通用`mutation_prepare`成功后Graph将proposal interruption写回LangGraph状态并停止本轮后续工具/模型调用；`RunService.wait_for_input`将owner run转为持久waiting_input。恢复时服务端只从审批记录读取规范payload，并由OrderWorkflowService走Provider与MutationService门禁。
- P05每个候选回答最多评审3次、最多修订2次；模型调用计入同一RunBudget。硬事实失败会触发有限修订；不能发布未通过正文。
- 订单图完成后只用operation/order/approval集合查询已提交结果，再输出评审；评审和恢复代码不调用`submit_order_v1`或MutationService。
- 订单说明评审先做确定性订单/审批事实核对，硬失败不请求语义评审。通过后最多3次检查、2次纯正文修订；每次从持久订单、operation与审批重读单号、数量/单位、单价/行额和总额。修订不调用业务写工具、不更换幂等键；两次后仍失败则终态保留已提交事实，明确不重放订单提交。
- P09正式报告验收保留请求中的md/html/csv/json格式（未指定才默认md），库存分页仅合并同owner/run、同范围、同数据源与同`as_of`的完整页集。生成后重新打开文件并逐字节比对服务端根据授权数据集重建的正文，再记录`report_verified`；普通产物事件不能放行订单准备。报告调用中的取消、deadline和共享预算异常继续传播到run控制流。
- fake模式使用明确的ScriptedModel离线评审响应；不能作为真实语义或模型验收。

## 验证

`uv run pytest tests/unit/test_evidence.py tests/integration/test_agent_tools.py tests/integration/test_agent_stream.py -q`
`uv run pytest tests/integration/test_checkpoint_resume.py tests/integration/test_order_idempotency.py -q`
`uv run pytest tests/integration/test_harness.py tests/unit/test_phase_transitions.py tests/unit/test_plan_updates.py tests/unit/test_deterministic_review.py tests/unit/test_semantic_review.py -q`

P06-fix2补验收还验证了 `tests/unit/test_fact_checks.py`、`tests/unit/test_live_acceptance.py` 与 `tests/integration/test_readonly_scope_answers.py`。2026-10-25完整Windows P06 offline为9/9 checks（157 unit、160 integration、38 frontend）；fake browser为2/2 checks、Playwright 9/9；显式live批次 `20261025T050032Z` 的P03三题各3次共9/9，详情及每次DB快照见[证据](../../../evidence/P06-fix2.md)。这不等同于正式后端浏览器下载或所有报告格式的人工打开验收。
# P08 前置意图与独立事实验收补修

P08 前置修复按标点分句限制订单否定范围，供应商排除不会否决后续正向备单；“删除我的偏好”先于通用偏好查看解析。事实核验接受目录具体单位“对”并继续拒绝单位错配。P03 live oracle 对P001/P003/P004使用可信fixture单位套/个/条，且逐项核对工具事实与最终回答；静态回放通过不代表真实模型live已通过。

# P09-F02 跨来源事实身份

库存与补货预览的来源记录ID仅作为追溯信息；事实匹配按字段、物料、仓库、供应商/订单、指标和单位形成业务身份。同一业务事实由多个工具一致观察时合并为一个可引用事实；同一业务身份出现不同最新值仍报告冲突，不同物料/仓库/供应商、字段或单位继续保持独立并拒绝含糊主张。

# P09-F07 聊天业务提案

订单专家提示明确：`mutation_prepare`仅创建待批提案；成功后运行立即持久为`waiting_input`，聊天和订单页共用同一审批/恢复路径。拒绝或批准均以原run、owner、版本和请求幂等键核验，业务写入只读取服务端保存的规范payload。独立Graph测试未注入`RunService`时，评审事件仍发送到事件sink，避免测试/嵌入执行器因可选持久层缺失而中断。

# P09 最终补修：模型修订正文

`GraphExecutor`评审前不再用`render_verified_core_facts`覆盖模型的非空最终正文。每次模型调用只在本地消息副本的系统上下文中附加来源核验的辅助事实；不修改持久消息，也不新增竞争的答案字段。确定性事实/范围/来源检查仍先于语义评审，语义修订通过后才发布；空正文仍按原模型输出错误处理。验证：`uv run pytest tests/unit/test_graph_answer_preservation.py tests/unit/test_verified_answers.py tests/unit/test_deterministic_review.py tests/unit/test_fact_checks.py -q`。

# P09 R3：报告范围使用结构化约束

请求约束现在显式包含`all_warehouses`、`all_inventory`、仓库ID/真实仓位名及物料ID。显式全仓在当前轮覆盖保存的默认仓库，不删除持久偏好；工具参数会移除单仓筛选。原始数字物料号仅按用户明确提供的物料编号读取，绝不补造`P`前缀。

报告数据集选择和正式正文验收共用同一结构化范围。全仓/全库存报告只能从无相应筛选的完整`inventory_page`页集生成；显式仓位/物料要求来源记录集合与请求集合精确一致。报告生成后仍需从artifact存储重开并按服务端事实重建正文逐字节核验，才记录`report_verified`。定向反例与报告文件回读见[evidence/P09-fix4](../../../evidence/P09-fix4.md)。

# P09 A4：正式回答发布门禁与供应商事实范围

通过确定性/语义评审后，`GraphExecutor`还会在发布正文前执行旧P03结构化claim校验；无效数字、单位、布尔状态或实体范围不会先以token对外发送。补货预览的数量/总额事实继承服务实际选中的报价与供应商身份，便于正文按报价、物料、仓位和供应商核验。`总额`只匹配`total_cents`，`行金额`只匹配`line_total_cents`；两个字段相等也不能互相代替。

# P09 R8：演示模型与正式报告的 browser 流程

`DemoScriptedModel`为固定 P09 浏览器场景按完整页大小读取 local_seed，使报告工具结果能覆盖其正式声明的全部 W01 库存行；这仅是 fake 演示夹具，不代表真实模型验收。P09 双尺寸 E2E 从 artifact 授权下载接口读取实际字节，校验登记大小、范围和来源，再验证订单55套/660元经编辑为60套/720元后重启恢复、审批与幂等重放。具体人工打开记录和 hash 见`evidence/P09-R8.md`。

## DeepSeek 输入缓存提示布局

新启动的`graph_version=v2`使用`prompt_layout.build_v2_initial_messages`：首条system保留基础规则，第二条system（存在角色规则或技能时）保持角色/技能前缀，本轮可信结构化约束另置于后部system，用户请求随后发送。`prompt_template_id`标记主图角色与报告规则变体；技能的版本和内容hash仍由既有`skill_manifest`单独记录。核验事实仅加入本次模型调用的消息副本，作为用户请求前的可信system消息，不改持久消息。

缺少`prompt_template_id`的既有v2状态继续沿旧路径将核验事实加到首条system；v1初始提示和`versions/v1_impl.py`未迁移。语义评审按rubric类型报告`ta-semantic-review-1:<task_type>`；订单意图提取和订单说明修订分别报告`ta-order-intent-extract-1`与`ta-order-answer-revision-1`。这些标识用于后续trace分组，不表示供应商缓存收益已验证。

# P09 N01–N04：合法语言格式与已核验覆盖

论断提取（`fact_checks.py`）先识别表格列角色（实体/报价、字段、值、单位）：纵表从本行字段单元格取字段、从单位列取业务单位；实体列只有在纯 ID 单元格时才整体绑定 P/W/S/Q。普通文本支持同一句内的受控逗号继承（`P001，数量55，单位套`）：只有紧邻实体且其间没有新业务数字时才继承，句号、转折、新块清除；Markdown 粗体/反引号按展示符号处理。字段取离数字最近的标签，避免同行"单价…/总额…"互相覆盖；无法唯一绑定时仍返回可修订错误。

同一报价的 `min_order_qty` 在比较前按可信 `part_unit` 规范单位（仅同一 quote/part/supplier），规范副本保留原 `call_id`/`as_of`；part_unit 冲突时不选边。选择链改为先归一再取最新快照，再比较数值；不同报价、不同供应商、不同物料、同时间不同值仍拒绝。

`evidence.affirmative_order_submission_claims` 按命题返回肯定下单文本，否定不跨句、不跨转折；`validate_business_claims` 与 `review.deterministic_review` 共用它，持久订单的"订单已提交"仍由成功 operation 与已消费审批授权。集合标题（如下/下列/以下）不再被当作"所有零件都有缺口"，含"所有/全部"的断言与全部事实核对。

推荐覆盖（`review._supplier_recommendation_issues`）只使用本轮匹配约束的 preview 中服务端实际选中的 `recommended_quote_id`，通过同一快照的 quote 标识或 quote_list 行解析 part/supplier；`lead_days` 主张必须数值等于该报价已核验交期，并用 Qxx、part+supplier 或该 part 唯一交期报价绑定。请求 `max_lead_days` 不能冒充供应商交期。验证：`uv run pytest tests/unit/test_fact_claim_context.py tests/unit/test_fact_checks.py tests/unit/test_order_review_bounds.py tests/unit/test_verified_answers.py tests/unit/test_fact_identity_reconciliation.py tests/unit/test_evidence.py tests/unit/test_deterministic_review.py tests/unit/test_supplier_recommendation_coverage.py -q`。
