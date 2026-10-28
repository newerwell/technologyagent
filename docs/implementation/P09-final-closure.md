# TechnologyAgent 最终补修实施手册

来源：用户 2026-10-28 明确授权实施。本版替代上一版补修计划。目标是关闭已确认缺陷、补齐原验收和 Git 交付；不重写、不开始 P10。

## 执行规则

- 在 technologyagent 原工作目录执行。远端 https://github.com/newerwell/technologyagent.git；启动复核 HEAD，不假定历史 0dd835c。
- 一次只做一张任务卡：读代码 → 添加反例 → 观察真实产品失败 → 最小修复 → 定向测试 → 证据及交接 → 显式暂存、提交、推送、核对远端 SHA。失败不跳卡、不改成完成。
- 环境、命令、权限和依赖错误不是产品反例。测试固定业务时钟及合成数据。不得降低事实、单位、来源、审批、owner、版本、幂等和预算检查。
- 不使用 git add .、git reset --hard、git clean、强推。原始库存、metadata、.env、密钥、数据库、运行日志不提交。只清理本次创建且核对绝对路径的临时目录；自动审批拒绝删除则保留并记录，不绕过。
- 不调用真实 ERP。远程仅本地 HTTP 模拟器；真实写 capability 关闭，F15/F16 保持 not_run。不重置 technologyagent_dev，写测试只用 technologyagent_test_*。
- local_seed 用于完整闭环和验收；文件 local_snapshot 用于用户库存查询。用户副本 72 条库存、72 个物料、6 个仓位，缺报价、预留、在途和目标；缺字段 null/UI 未知，不伪造采购数据。

## 任务卡 0：工作区与基线

1. git status --short、git log -5 --oneline、git diff --stat、git ls-remote origin refs/heads/main。
2. 读 AGENTS、实施手册、共享契约、最终矩阵和 Git 交付规则。
3. 交接记录分三组：必要功能（事实、库存、配置/API/MCP/UI/测试）、无关修改、本机绝不提交文件。核对库存适配和 harness/review/verified_answers 未提交依赖。
4. git check-ignore .env data/inventory_snapshot.json data/inventory_snapshot.meta.json。
5. 单元、前端、类型和库存适配定向测试；显式暂存必要文件，提交推送已有功能基线。保留无关修改。记录 SHA 和结果，不称 P09 完成。

## 任务卡 1：停用物料预览

入口 services/replenishment.py。内存 Catalog/Inventory + 固定时钟，构造停用物料、有效供应商和报价、真实缺口 55。先观察旧实现 actionable=True 失败，再修预览。

停用行必须 actionable=False、quantity=0、total_cents=0、recommended_quote_id=None、candidate_quotes=[]、missing_fields 含 part_inactive；保留真实可用量和缺口，使用 PreviewLine 正常验证。模型/UI 显示“物料已停用”。DraftService.prepare 仍拒绝 409。覆盖停用、改为启用、停用建草稿零效果、同批启用/停用分别判断。

## 任务卡 2：保留修订正文

入口 agent/graph.py。脚本模型第一次缺原因→语义失败→第二次补来源支持原因→通过，先观察正文覆盖反例。移除评审前无条件 render_verified_core_facts 覆盖非空 final_answer。

renderer 只作为本轮调用本地消息副本的辅助系统上下文，不改持久用户消息、不引入第二最终答案字段、不重复追加。硬检查先于语义评审；无正文仍模型输出错误。P003 原因来自实际工具数据，不硬编码 Q06/S03/价格/交期。编造仍拒绝，最多两次修订；返回、持久消息和 summary 一致，原请求不变。

## 任务卡 3：订单说明和提交事实

入口 services/order_workflows.py。先扩展集成测试：修订成功、两次耗尽、评审连接失败、只有单号缺数量金额。

订单事务内持久 verification_facts：物料、仓库、数量、提交单位、实际报价 ID、批准时核验交期及来源时间；仅服务器核验数据可信。说明只读持久订单、成功 operation、已消费审批、历史快照及保存的请求约束；不以当前目录替代历史。历史缺单位/交期为未知。

初始正文包含用户单号、逐项数量及已知单位、各单总额、用户交期要求是否有保存依据；区分要求七天、报价五天和实际到货。ORDER_FACTS_MATCH 同时校验必要覆盖；66000分/66,000分/660.00元精确等价。错误金额/数量/单位拒绝，只有单号进入修订。最多两次纯文字修订，无工具/重批/重提交。成功/耗尽/连接失败都只有一单和一个成功 operation；失败明确“订单已提交，说明评审未通过”。

## 任务卡 4：统一模型调用和有限重试

入口 services/model_observation.py。ObservedModelResponse(deltas, successful_call_id, usage)；collect_model_response(model,messages,tools,ctx,budget,emit,purpose)。四入口：主 model_node、semantic_review（包括 emit=None）、_live_draft_request、_revise_order_answer。移除各自重复计数/事件；emit=None 仍检查预算。

每次实际尝试：取消/期限检查→charge_model 一次→started 一次→请求→finished 一次。工具 parent 为成功尝试 ID。最多额外一次，仅任意 ModelDelta（token/tool_call/usage）出现前的传输中断或超时可重试；RemoteProtocolError 属传输中断。MODEL_PROTOCOL_ERROR、401、429、5xx、截断、取消、预算耗尽不自动重试，不能只看 retryable。

逻辑调用总期限首次计算，最多60秒并受 run 剩余时间限制；第二次不重置，无 delta 等待也检查取消/期限。失败/成功各自 trace；usage 缺失未知。测试：失败后成功请求/预算2；连续失败仅2；任意delta后断流1；取消/预算不足不启动；工具只处理完整成功结果一次；失败片段不拼入正文。

## 任务卡 5：实际报告入口和范围

5A：MCP 注册→_business_call→dispatch_business→InventoryService。local_seed inventory_page/warning 成功后使用现有完整筛选分页快照计算，证明页属于完整集合；漂移/无法证明直接明确失败。文件快照保留真实副本身份、采集时间和未知完整性。实际 MCP 层测完整两页（观察时间可不同）、变化、缺页、重复实体不得完整报告。

5B：请求约束增 all_warehouses:bool=False；所有/全部仓库/跨仓汇总不套默认W01；真实来源目录识别“A区-1号库”等仓位及物料原ID，不加P前缀。选择和报告核验用同一结构范围。全仓拒单仓筛选，明确单仓/单物料须精确一致。快照全部仅已保存集合，不宣称实时ERP全量。测全仓+W01失败/完整通过、保存W01后全仓不继承、中文仓位错/对、单物料额外实体失败。

5C：快照拒报价/目标补货仍保持拒绝，错误meta为快照来源和采集时间，不误标local_seed；其他模块来源保持真实。

## 任务卡 6：v1/v2隔离

不改旧checkpoint fixture。机械提取当前安全修复后的v1 state、图节点/builder、订单节点/builder/workflow_config为独立文件；不恢复旧漏洞。versions/v1.py导出独立实现，不共享别名；v2独立构建入口。GraphExecutor和OrderWorkflowService._graph真实路由选择版本。旧字段默认、节点名、thread key、namespace、中断恢复ABI不变；安全业务服务共用当前实现。

测旧checkpoint批准/重复恢复仅一单、真实改变v2节点/状态/编排仍不影响v1、新v2 namespace、互不覆盖；函数自相等不能证明隔离。

## 任务卡 7：远程读取及持久对账（仅本地HTTP模拟器）

7A：保留ErpClient协议，不猜真实ERP。API/MCP接同一Provider查询服务，不允许Mongo假冒ERP。领域DTO验证必需字段，缺字段明确错、不填0。分页校验页码/ID/count/total，最多100页/10000条并受预算；异常/重复/触顶返回分页不完整。

7B：复用operations。远程一次认领不得过期重领；内部action含稳定provider范围，沿用owner/action/key索引。存原action/provider/payload hash/审批/关联号/dispatch/外部结果及ID。同键异payload冲突。只有新认领胜者原子dispatch持久确认后可POST一次；已有operation不再POST。dispatch后超时/取消/损坏/解析/崩溃/保存失败均待对账，不以内存集合保证幂等。

7C：ReconciliationService先分远程；远程processing/unknown即使lease过期只lookup，不因无本地订单可重试；普通404/超时/无法验证关联保持未知。本地原事务安全恢复不变。

测持续HTTP模拟器+独立Mongo：并发POST≤1、丢响应后重建服务lookup同单仍POST1、dispatch后崩溃不重发、损坏JSON/保存失败unknown、lookup404unknown、owner/provider隔离、异payload冲突。真实写能力仍关，F15/F16 not_run。

## 任务卡 8：23工具证据

按P08原表全部23工具（并非23只读）逐行：工具、正常/非法输入、实际MCP结果、写前/后数据库事实、测试名。读验证值和范围；写测未批准、批准成功、重放、错误owner/过期版本。非法参数发到实际MCP，不只schema本地验证。复用已有供应商/物料/改单/取消/收货/流水测试，核具体记录数量，不能少量断言冒称全集合相同。无正常写证据不标通过。

## 任务卡 9：双尺寸和干净检出

1440×900和390×844各完整：查询→真实报告→下载（字节/hash/内容/来源）→草稿→编辑数量金额→刷新待审→重启测试后端恢复→批准→重复批准仅一单。workers=1；不得route.fulfill假成功业务/下载，允许断网延迟故障注入。

保留三图+HTML既有确认；补MD/CSV/JSON实际打开、每图明确文件/hash，不混旧runtime文件；无打开能力not_run，解析不算打开。全新检出已推代码，锁文件安装、不复制venv/node_modules/build，fake+合成库完整报告下载订单恢复；旧基础启动/单文件恢复不能替代闭环。

## 任务卡 10：最终门禁与环境恢复

PowerShell7。所有pytest `uv run python -m pytest --basetemp .runtime/pytest-<任务>-<批次> <实际路径> -q -rs`，记命令/数量/退出码/原因。

offline：MODEL_MODE=fake、RUN_LIVE_MODEL=0、MONGODB_DATABASE=technologyagent_test_p09_verify，inventory/parts/suppliers/orders均local_seed，INVENTORY_SNAPSHOT_PATH空。`uv run python -m scripts.run_acceptance --scope local --mode offline --report .runtime/reports/P09-<batch>-offline.json`；查所有子检查。

browser：stop，同环境切technologyagent_test_p09_browser，start，确认服务及验收均local_seed，run_acceptance --mode browser。live仅此前确定性/offline/browser通过后：stop，MODEL_MODE=live、RUN_LIVE_MODEL=1、DB=technologyagent_test_p09_live，start，--mode live。固定13外层、P03内部9次、F12内部9组，不加次挑成功；保留全部失败，修后全新批次。

最后恢复technologyagent_dev、原live配置、库存/物料local_snapshot、data/inventory_snapshot.json及其他原来源；重启页面/MCP确认72、未知仍未知。不重置日常库。

## 任务卡 11：CI/Git/最终交接

CI增P09offline（fake合成隔离库，无私有库存/凭证），不替代browser/live/人工打开。

每卡：git diff --check/status；git add --明确路径；diff --cached --stat/--check/--name-only，排除私有数据；commit；push origin main；rev-parse HEAD和ls-remote核同SHA，失败不称上传。P06自身全关才补phase-p06，P09全部本地必需门槛才phase-p09；不覆盖标签，annotated核^{commit}解引用。

最终报告每卡填：具体修改、已关闭/部分关闭/未运行、修前反例、定向命令/数量/退出码、各全门禁、订单operation库存流水事实、证据文件/批次、本远SHA/标签、限制。

完成须缺陷全关、F01–F14/F17–F18满足、固定live通过、干净检出闭环、交付与验收源码一致、远端及标签核对。任一不满足保留未完成，不开始P10；F15/F16可独立not_run，不能称真实ERP联调完成。
