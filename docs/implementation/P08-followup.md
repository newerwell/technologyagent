# P08 与前置补修 Implementation Plan

> **For agentic workers:** 用户指定的其他 Agent 按 superpowers:executing-plans 逐任务实施。当前规划者只维护审查与计划文档；本计划不表示已开始修复。

**Goal:** 让 Provider 配置、批准事实、收货、聊天业务工具和独立验收贯穿实际用户路径，并保留原订单/报告/历史恢复能力。

**Architecture:** 入口共用按模块选择的业务端口；服务负责 schema、能力与批准绑定，repository 负责本地事务；远程 intent/operation 独立持久化，不能以本地 Mongo 事务冒充外部原子性。意图、事实单位和验收器分别校验自身可信输入。

**Tech Stack:** 现有 Python/Pydantic/LangGraph/MongoDB/FastMCP/HTTPX 与 Next.js，不升级框架掩盖问题。

**Spec:** [本轮审查](../reviews/2026-10-25-P08-review.md)、[P08 Spec](../specs/P08-erp-integration.md)、[共享契约](../specs/CONTRACTS.md)。基线 c2427e0 + 已存在的未提交 P07 补修；实施前重新核对 diff，不能丢弃或混为已上传。

## 文件分工与执行顺序

Provider 路由放 integrations 并通过 bootstrap 注入，HTTP/MCP/Graph 使用同一端口；禁止分别写四套来源判定。action payload/规范化/批准快照放 contracts 与 services；本地事实事务仍在 business_mutations/inventory，远程持久动作单独建服务。Graph 只编排/等待/恢复，UI 只展示事实和提交明确决定，不计算采购金额。

先 F01/F02 解决高影响数据源与价格边界；F03 接业务闭环，F04/F05 固定收货/实体输入，F06 统一远程读取结果，F07 修前置意图与单位，F08 完成或准确保留远程交付缺口，F09 做版本与交付回归。每任务有独立测试和提交；不得一次做完后才记录。

## Global Constraints

- 保留用户既有修改、环境与数据；只 reset 专用 `technologyagent_test_*` 库。不上真实 ERP 补测试，不提交密钥/运行目录。
- 所有业务写仍需显式人工批准；同一 canonical payload、action、owner、provider、版本/事实快照贯穿批准与执行。run 关联与跨 run 复用规则先写契约，不从模型参数取身份。
- 本地写继续单 Mongo 事务提交全部事实/Receipt/Movement/批准/operation；远程超时只记未知并对账，不换关联号重发。
- 父子 run 复用预算；v1 旧批准恢复保持原授权语义。已有标签不移动，修复交付使用新提交/有条件的新标签。
- 历史 live 与当前离线结果分别记录。旧 P03 9/9、新批次 2/9、P07 报告失败均保留，不能删失败轨迹或仅改判分规则声称新 live 通过。

## Review Focus

remote/snapshot 页面仍写本地→F01；批准后变价→F02；MCP 有工具但用户走不到→F03；合法明细顺序与 hash 不一致→F04；通用提案写入坏实体→F05；末页/重复/统计类型错配→F06；动作否定与对象排除混淆/具体单位误拒→F07；进程重启丢未知状态→F08；v1 名义封存/只跑本阶段浏览器→F09。

### F01 数据源贯穿实际入口（R01）

**Files:** `backend/app/integrations/{business_provider,local_provider,erp_provider}.py`、`bootstrap.py`、`ports/` 的相关端口、`api/{catalog,inventory,drafts,mutations}.py`、`mcp_server/{server.py,tools/business.py}`、工作流及 fake registry 使用方；新增 `tests/integration/test_provider_switching.py`。

**Interfaces:** 同一 `BusinessProviderRouter` 按 suppliers/parts/inventory/orders 选择端口；`require_action(module, action, ctx)` 在任何副作用前检查能力，返回的结果携带真实 source_refs。具体端口保留原公开方法，签名变更先同步 INTERFACES/CONTRACTS。

- [ ] 红测：四模块 remote_erp 且无端点，HTTP四类查询应明确不可用，不返回 seed；snapshot 下原 `/api/orders/create` 链应在业务写前拒绝。断言 orders=2、I001 inbound=10、operation 无成功业务动作。
- [ ] 修装配/入口共享路径，覆盖页面查询、预览、草稿、原订单审批提交、通用动作、fake/脚本聊天和 MCP；拒绝不能仅靠 UI 隐藏按钮。
- [ ] 测混合模块、远程503、快照写拒绝、local_seed原功能、真实元信息；不允许以远程断开/坏响应回退本地。快照如果只读相同本地数据，也须明确来源/新鲜度，不冒充已加载外部快照。
- [ ] 运行新测试及 `test_provider_contract.py`、`test_mcp_tools.py` 中相关用例；模块README/映射契约同步，显式提交并推送该任务。

### F02 改单的可展示事实与旧批准失效（R02）

**Files:** `contracts/mutations.py`、必要的 `contracts/domain.py`、`services/{approvals,business_mutations}.py`、提案/审批页面；扩展 `tests/integration/test_business_mutations.py`。

**Interfaces:** `prepare_order_amendment(order_id, items, expected_version, ctx)` 生成服务端变更草稿，含旧/新明细、具体单位、单价/行额/总额、quote snapshots 和相关版本。批准绑定这些事实而非只有 quote_id。

- [ ] 红测固定 O001/P001/Q01 数量10，批准时1200分；批准后Quote改120000分，执行必须拒绝并要求重新确认，不能写1200000分订单；批准/原订单/inbound保持一致。
- [ ] 用与原下单一致的事实重查原则覆盖报价金额/交期/有效期、供应商状态、订单版本和相关库存。准备阶段展示金额，事务内比较绑定事实；变化后废弃原批准并展示新版。
- [ ] 测无变化改单成功、变价/过期/停用/并发旧版本拒绝、相同幂等键重放、取消与改单inbound对账；不得在执行时静默用当前金额替换批准金额。
- [ ] 跑针对集成和原订单批准回归；更新中文README/契约，提交并推送。

### F03 让通用业务请求走完提案、决定和执行（R03）

**Files:** `agent/{graph,graph_versions,request_intent}.py`、`specialists/{policy.py,analyst.yaml,order.yaml}`、`contracts` 的通用等待/恢复状态、`services` 编排入口、`api/mutations.py`、`frontend/src/app/orders/page.tsx`、`mcp_server/tools/specs.py`；新增 `tests/integration/test_business_workflow.py` 与 `tests/e2e/p08-business-flow.spec.ts`。

**Interfaces:** 明确只读业务工具能力与 `mutation_prepare` 的提案能力；持久保存 proposal_id/approval_id/action/version/run，用户决定后由受控服务消费保存的 canonical payload。页面独立提案可提供 `execute(approval_id,idempotency_key)`，请求不接受替代业务payload；聊天提案必须续接其拥有的run。具体URL/事件先同步契约。

- [ ] 红测实际 GraphExecutor + 可用 ALL_TOOL_SPECS：order_statistics、part_by_supplier、mutation_prepare 不应 UNKNOWN_TOOL；被禁止角色仍不可调用写/自批工具。
- [ ] 实现本地用户请求→可信提案→持久等待→页面批准/拒绝→服务端执行→结果事实；不同 owner 不可读取/批准/执行，明确同 owner 跨 run 执行规则。
- [ ] 新增真实HTTP/Mongo+浏览器批准用例：供应商从N→N+1、一次operation、审批consumed，刷新/重启后不重复；拒绝业务0写；执行报错显示失败/未知，不显示“已完成”。
- [ ] 不删除原只读边界：analyst不可直接供应商/库存写，order不可自己批准；审批列表与业务工具执行使用同一动作类型。
- [ ] 跑新闭环和原P04/P07恢复测试，记录结果，提交并推送。

### F04 收货使用同一规范化与作用域（R04）

**Files:** 新增或扩展 `contracts` 的收货payload/规范化，`services/{approvals,inventory}.py`、`repositories/{movements,operations,indexes}.py`；扩展 `tests/integration/test_inventory_receipts.py`。

**Interfaces:** `canonicalize_receipt(payload) -> ReceiptPayload` 只定义一次，准备展示、hash、批准和执行全部调用；provider来自可信路由，Receipt和operation对其作用域保持一致，不能任意模型字符串切换数据源。

- [ ] 红测合法双行：隔离夹具增加P009/单位套/S01有效Q09与W01库存，通过正式草稿批准路径创建P001+P009同供应商/仓库/单位订单；批准收货 `[P009:1,P001:1]` 后应成功；重排后同receipt重放不重复入库。不要向正式seed添加P009。
- [ ] 规定重复part行合并或拒绝；无论选哪种，批准内容与执行完全一致。测整数/布尔/空行/超收、warehouse、order状态、scope重复。
- [ ] 明确 owner/provider/receipt 与幂等键关系；不同provider相同key不能误返回另一来源的结果。补作用域测试，不向公共输入随意开放provider。
- [ ] 重跑65/65/45/10/10、20/20/40/75/75固定事务、failpoints、并发重放；更新README/契约，提交推送。

### F05 action-specific 强类型输入（R05）

**Files:** `contracts/mutations.py` 或按模块拆分的payload文件、`services/{approvals,business_mutations}.py`、`api/mutations.py`、MCP schema生成处；扩展业务集成和schema一致性测试。

**Interfaces:** action→Pydantic payload 注册表；HTTP/MCP/prepare/事务执行共用解析，`extra=forbid`、非空字符串、严格数量/版本；规范JSON用于展示/hash，不能仅验证具体MCP外壳。

- [ ] 红测HTTP通用提案的 `name=123`、`credit_rating={...}`，必须在提案准备或执行前422拒绝；供应商数不变、无坏记录、无成功operation，目录读取仍200。
- [ ] 对 part_create 的 specification/category、供应商字段、状态、库存数量/版本、改单/收货嵌套字段补非法类型/未知字段断言；旧持久坏提案执行也拒绝，不能依赖新入口修好。
- [ ] 正常23工具名称/schema与业务服务保持一致，未批准任何写仍拒绝；运行对应unit/integration，更新README，提交推送。

### F06 远程读取的分页与结果类型（R06/R07）

**Files:** `integrations/erp/mappings.py`、`mcp_server/tools/business.py`、`contracts/common.py` 必要的范围类型、`agent/harness.py` 使用方；扩展 `tests/unit/test_p08_erp_adapter.py`，新增 `tests/integration/test_erp_read_results.py`。

**Interfaces:** 单页结果包含契约pages或明确不可知状态；完整性来自已验证页集合，而非offset到末页。单实体/分页/统计分别使用各自映射，`map_order_statistics` 保留 total/total_cents/by_status/scope信息。

- [ ] 红测duplicate[A,A]/total2、只读page2/total21、越界空page3；都不能声称已收集全量。单页1/1合法响应进入实际Graph评审应能通过。
- [ ] 用HTTP模拟器测试完整多页、重复/回环页、total=0但非空、总量缺失/矛盾；保留成功页和缺失范围，禁止默认补可信total=0或pages=1。
- [ ] 远程 order_statistics 输入 total30/12345分/submitted30，输出必须仍有这些值；订单item mapping与统计mapping互不混用。对允许的remote read_actions逐项契约测试。
- [ ] 跑实际MCP与Graph消费链，更新erp-mapping和来源/范围说明，提交推送。

### F07 前置意图、偏好与具体单位/独立oracle（V01–V04）

**Files:** `agent/{request_intent,fact_checks}.py`、`graph_versions.py`、`scripts/live_acceptance.py`；扩展 `tests/unit/{test_request_intent,test_fact_checks,test_live_acceptance}.py` 与 `tests/integration/test_chat_preferences.py`。

- [ ] 红测四类原文：“不准备订单”“不生成订单，只分析”“不用S01，本轮只用S02准备P001订单”“删除我的偏好”。断言动作否定时备单0次，排除S01仍使用S02准备，删除后同owner存储为空。
- [ ] 按分句/动作对象确定否定与供应商选择，不靠扩大跨句正则；有效约束传播到最终持久draft，而非只看parser字典。
- [ ] 红测真实目录P006/W01 available40对，正确句通过、40件/40套拒绝；其他已有具体单位错误测试保持。
- [ ] 独立oracle对正确55套/36个/10条接受，错误件数/单位、实体交换、遗漏、反向结论、截断/不全证据仍拒绝。期望来自可信fixture，不能从被测答案反推。
- [ ] 可先对旧脱敏轨迹重新评分作诊断，但保留原分数和理由；需要新真实3×3时只运行固定批次，不挑选成功样本。live未运行保持not_run，模型业务仍失败保持failed。
- [ ] 跑针对回归、更新README/证据，提交推送。

### F08 持久远程intent与结果未知对账（R08）

**Files:** 新增 `services/remote_mutations.py`、所需contracts/repository；扩展 `erp/client.py`、`erp_provider.py`、`services/reconciliation.py`、MCP分发和bootstrap；新增 `tests/integration/test_erp_outcome_unknown.py`。

**Interfaces:** remote handler在HTTP前持久化owner/provider/action/canonical hash/approval/version/correlation/operation状态；`reconcile(operation_id,ctx)`选择对应provider并按同关联号lookup，核对实体、明细和金额。

- [ ] 红测模拟器已接单但响应丢失→重建服务/客户端→同操作重试：POST总共1次；lookup找到同单后持久succeeded，批准只消费一次。不同owner/action/hash与伪approval拒绝。
- [ ] 实现超时/断线/不可解析响应的未知状态策略；lookup不支持/普通404保留未知，不能只查本地库无订单就宣布retryable。权威未提交证明须在能力契约中明确。
- [ ] 服务向read重试传递动态剩余预算，取消或超时后不发后续尝试；写不自动retry。远程调用与本地事务分开记录，不能持有Mongo事务等待HTTP来冒充原子性。
- [ ] 默认写能力继续关闭，模拟器通过并具备明确测试环境/账号/范围后才单独实测与开放；未具备真实环境不会阻止本地持久闭环测试。
- [ ] 如本轮明确不实现此任务，T05保持未完成，交付表写“仅客户端预留”，不能把无真实环境作为已实现替代。记录准确状态并提交推送。

### F09 版本隔离、全阶段验收和交付（V05及交付）

**Files:** `agent/versions/v1.py`、`agent/graph.py`、`services/order_workflows.py`、必要的v2 builder；阶段/恢复测试、`scripts/verify_stage.py`、CI、README、STATUS、P08 evidence/spec。

- [ ] 先写行为对照：改变v2编排/共享入口后，持久v1 fixture依然使用指定v1 builder/schema/config恢复原pending approval；不是比较同一函数对象。升级前后的旧事实/决定/namespace一致。
- [ ] 真正按持久graph_version选择封存入口，稳定domain/service仍可共享；避免复制整套业务，也不能只增加未被使用的常量。
- [ ] 核对并交付当前已有未提交P07修复，明确其原作者范围；先看git diff，不能打包.env.example、.dsh-meow、frontend/AGENTS.md等无关文件。本轮P08修复与原变更分别可审查提交。
- [ ] fake、RUN_LIVE_MODEL=0，跑P08 offline和完整历史browser套件（包含P04订单、P07偏好/报告及P08批准成功与拒绝）；不能只grep本阶段1条后称全项目回归通过。报告记录精确计数/退出码/数据源和数据库。
- [ ] CI检查当前阶段manifest或明确说明它仅运行P06目录回归；不能把job success说成P08独立compatibility/browser/live通过。
- [ ] 必需验收满足后显式暂存、commit、push、核对远端；原phase-p08不动。严格未验项仍开放，不创建伪完成标签，不开始P09。

## 发给实施 Agent 的提示词

```text
你是TechnologyAgent实施Agent，只做P08与前置补修，不开始P09。
仓库：C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent
远端：https://github.com/newerwell/technologyagent.git

先核对pwd、git status/log/diff、origin/main与标签。当前有P07报告门槛等既有未提交修改，保留并区分其工作区/远端状态，不reset、不覆盖、不把无关文件打包。
读AGENTS.md、PROJECT_LAYOUT、EXTENSION_GUIDE、CONTRACTS、实施手册/INTERFACES、STATUS、docs/reviews/2026-10-25-P08-review.md、docs/implementation/P08-followup.md和P08证据。

按F01→F09逐任务：先失败复现，再最小修复/针对回归、中文模块README、证据及独立提交推送。先处理Provider配置未贯穿与批准后变价，再接通通用业务请求→提案→决定→执行，修乱序收货/弱schema/远程分页统计及前置意图单位。远程持久intent/对账与v1隔离未实现时保持开放，不以模拟器或常量声明冒充完成。

只用technologyagent_test_*独立库测试，不reset开发库、不请求未指定真实ERP、不开放未验证远程写。保留旧标签、失败轨迹、全部既有边界。live需记录固定批次与数据库前后事实；未运行、运行失败、确定性通过分开写。
最后跑完整offline及历史browser、核对Git远端，给出关闭/未关闭清单和commit；停止，不开始P09。
```
