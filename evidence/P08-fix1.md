# P08-fix1 补修与验收

日期：2026-10-26
仓库：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`
远程：`https://github.com/newerwell/technologyagent.git`
基线：`1696396ebb288ad8501372374b9e1bdb7c430a26`（P08 review）
本轮代码验收提交：`519b048ee39b511c74b44d6120924a96ff9a06fc`（该SHA的origin/main及CI均已核对；证据/状态文档随后另行提交）

## 范围和保留项

只执行 P08 follow-up 与明确的 P07 前置补修，不开始 P09。开始时保留原工作区 P07 改动，`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md` 均未纳入 P08 提交；将 `request_intent.py` 的 P07报告请求识别及其单测作为独立提交 `3eb3203984b8110502aa9c82a2fc118178ff864b` 推送，未把其余 P07文件打包。未读取或提交 `.env`。Mongo操作仅在 `technologyagent_test_p08_verify`、`technologyagent_test_p08_browser` 及测试 fixture 的 `technologyagent_test_*` 数据库执行；没有 reset 开发库。应用已停止，Mongo容器保持运行。

原 `phase-p08` 标签对象保持 `45ff6cfe4eb4639887f53cc9ed9d91eeb670f663`，解引用提交仍是 `c2427e067a973aa91849692ed24c30006d21a883`。没有新建 P08 完成标签。

## F01–F09 与前置项结论

| 任务 | 状态 | 实施与证据 |
|---|---|---|
| F01 / R01 Provider入口 | 部分关闭 | 在REST本地投影入口增加能力检查，remote配置不再泄漏seed数据，snapshot写拒绝，混合来源写失败关闭；`tests/integration/test_provider_switching.py` 的2个反例先复现旧实现返回200，再验证修复返回明确失败。真正把映射的remote读取贯穿到这些REST页面尚未实现，保持开放。提交 `bf01217934cddbdb5714ec581b49fd3f24d2dd25`。 |
| F02 / R02 批准后变价 | 关闭 | 改单批准保存quote快照，事务内对比当前事实；先复现批准后报价从1200分改成120000分仍执行，再验证过期批准拒绝且无业务写。`tests/integration/test_business_mutations.py`：5通过。提交 `6b8beb060ec4ac82514db1d523afead95394cbe2`。 |
| F03 / R03 提案闭环 | 关闭（本地闭环） | 接通Graph `mutation_prepare` allowlist、owner-scoped HTTP提案/决定/执行、订单页共享显示，执行仅消费服务端payload并持久幂等。新增HTTP/Mongo一写和重放用例、浏览器批准与拒绝用例；补充同owner跨run执行、foreign owner NOT_FOUND、单operation/单业务记录断言。对应提交 `96a263a139cdf085b6b2a40363566de40234237f`、`5ddf9567430ec6253de1c9315e00ad598d5be531`、`519b048ee39b511c74b44d6120924a96ff9a06fc`。 |
| F04 / R04 收货规范化 | 关闭（本地） | 批准与执行共享严格canonicalizer、重复物料合并并排序。双行 `[P009,P001]` 在旧逻辑下批准hash和执行载荷顺序不一致而失败，修后乱序合法收货及重放通过；原收货事务/并发/failpoint回归包含在集成套件。提交 `69e88bd3bef4cd3d36574aa25793b8bd0efa554c`。 |
| F05 / R05 强schema | 关闭 | 按action使用strict schema，提案入口和历史持久proposal执行前重新校验。供应商name数字、错误credit_rating类型、part specification数组先复现被接受/可能污染，再验证422且无operation/坏记录；历史坏proposal在operation claim前拒绝。提交 `9256eddb39cf92ccbb2dccf8f26cded12fe56c84`。 |
| F06 / R06/R07 分页和统计 | 部分关闭 | 单页明确报告页数、校验重复ID/总量/空越界页，不能用offset推断完整；order_statistics使用专门映射保持统计形状。page2/空page3/重复ID/统计映射反例先失败后通过，`tests/unit/test_p08_erp_adapter.py` 12通过。自动抓取并合并多页及回环检测尚未接入消费链，保持开放。提交 `c31c0c8969883ca9aab103f715e39e0fe4ebb640`。 |
| F07 / V01–V04 意图和单位 | 关闭（列出的本地残留） | 按标点分句处理否定与供应商排除/正选，先处理偏好删除；P006单位“对”可用；live oracle从可信fixture读取每个实体的数量和具体单位，并核验最终正文。四类意图/单位/oracle反例先失败后通过；目标测试合计38通过。提交 `665d25bff407bd78acfd11ddcf42c1c62633830d`。未运行真实模型批次。 |
| F08 / R08 远程intent与对账 | 未关闭 | 远程写仍关闭；当前没有持久remote intent、重启后按关联号权威对账或未知结果安全重试闭环。未用HTTP模拟器声称已完成。 |
| F09 / V05版本隔离与交付 | 未关闭（部分交付） | 完成offline、完整历史browser及CI核对；P07报告门槛改动独立提交。`GraphExecutor`仍未按持久graph_version选择封存v1恢复入口，没有跨版本pending checkpoint行为对照，故版本隔离验收未完成，不加阶段完成标签。 |
| P07前置报告门槛改动 | 独立交付 | 只暂存 `request_intent.py` 和对应测试，提交 `3eb3203984b8110502aa9c82a2fc118178ff864b`，与P08代码提交分离。其余既有P07文件继续留在工作区。 |

## 修复前失败与定向回归

- F01：remote模式的本地REST读取返回seed数据、snapshot下单成功；修后查询/写入均按能力拒绝，原local_seed路径回归通过。
- F02：批准价格变更后，执行曾会读取新quote写入新价格；修后事务内quote快照不符则返回 `STALE_APPROVAL`，无批准业务副作用。
- F03：Graph新工具为 `UNKNOWN_TOOL`，通用proposal批准后无法从共享订单页面执行；现在proposal-only allowlist和HTTP/订单页消费闭环均有回归；同owner跨run和跨owner拒绝由新增 `test_generic_proposal_is_owner_scoped_and_can_execute_from_another_run` 覆盖。
- F04：相同合法双行收货因顺序变化无法匹配批准载荷；统一canonicalize后成功；更换receipt operation key仍受receipt唯一作用域约束。
- F05：错误结构字段类型未在通用proposal入口拒绝，旧proposal也可能先claim operation；修后入口/执行重新解析strict schema。
- F06：只看offset会误报page2、越界空page3完整，重复实体可重复计入；order statistics曾映射为空订单列表；修后按显式页数和结果类型处理。
- F07：否定可跨句误伤、排除特定供应商后意图传播不可靠，“对”被当成件数、live oracle对所有实体硬编码“件”；修后目标固定反例通过。

相关定向回归：提案HTTP/Mongo与坏历史proposal `tests/integration/test_business_workflow.py` **6 passed**；Graph role和specialist **2 passed**；收货与变更事务 **7 passed**；业务schema及工作流集合 **16 passed**；ERP adapter **12 passed**；意图、事实校验、live oracle、偏好合计 **38 passed**。各任务修复前失败输出保存在对应提交的测试迭代记录中；本证据保留其旧失败语义，不把失败轨迹归因于模型。

## 最终确定性验收

最终代码HEAD执行：

```powershell
uv run python -m scripts.verify_stage P08 --mode offline --report .runtime/reports/P08-fix1-final-offline.json
```

结果 exit 0，`ok=true`；9项全部通过。隔离DB `technologyagent_test_p08_verify`：compatibility通过、212 unit、193 integration；前端typecheck通过、10个测试文件/38 tests通过、build通过；contract check通过。报告完成时间 2026-10-26 10:01:26 +08:00。seed命令只对上述technologyagent_test数据库执行了 `--reset`。

最终代码HEAD的完整历史browser命令：

```powershell
$env:MONGODB_DATABASE='technologyagent_test_p08_browser'
$env:MODEL_MODE='fake'
npm --prefix frontend run test:e2e -- --workers=1
```

运行前只重置隔离浏览器DB并启动本地app；13/13通过，覆盖图表与报告、聊天刷新/恢复/取消/切换、订单审批、P07偏好、P08提案拒绝及批准执行。第一次历史尝试曾在残留的隔离browser DB上12/13，P04订单缺少有效报价；该次失败保留，之后只重置 `technologyagent_test_p08_browser` 并完整重跑成功。应用使用 `stop.ps1` 停止，Mongo容器未停止。

GitHub Actions push run [40256439654](https://github.com/newerwell/technologyagent/actions/runs/40256439654)：head SHA为`519b048ee39b511c74b44d6120924a96ff9a06fc`，结论`success`。代码提交推送后`git ls-remote origin refs/heads/main`与本地HEAD相同。最终证据/状态文档提交及其远端SHA在本文件末尾补记。旧`phase-p08`仍指向`c2427e067a973aa91849692ed24c30006d21a883`。

## 未运行/未验收

- 真实模型：本轮固定live批次 `not_run`；fake/offline/browser结果不作为live结果。没有读出或提交本机密钥。
- 真实ERP：`not_run`；没有指定测试端点、测试账号和写入范围，因此没有发真实ERP请求，远程写保持关闭。
- F01真正远程REST读取贯穿、F06多页自动收集、F08持久远程intent/对账、F09 v1版本隔离仍未实现/验证。P08整体完整验收未关闭；不移动旧标签、不创建新phase标签、不开始P09。

## 证据文档交付

证据与STATUS提交：`76ad60e763c7abe5d0dcf72aeb393ec675bb7b87`，已推送`origin/main`。代码和测试未在该文档提交后变化。

