# P07-fix1 实施与验收记录

日期：2026-10-25。范围：P07及本轮复核所列前置事实缺口；不开始P08。起点 `88e012dadf358148db45241080251b65a876b75a`，远程 `origin/main` 起点相同。旧 `phase-p07` 解引用为 `727269a1f39eed8a4227041e36f656cabaa7c76e`，旧标签未移动。

## 修复对应关系

| 审查项 | 实施与确定性回归 |
|---|---|
| R01 聊天记忆 | 新增确定性请求意图识别；显式“记住/查看/删除”经共享偏好服务持久化，分析和订单入口读取同owner偏好。HTTP Mongo集成覆盖保存和跨新会话应用。 |
| R02 本轮覆盖 | 本轮显式仓库/供应商/交期覆盖长期偏好；明确清除与否定意图不重新套回默认。订单最终草稿和工具参数使用同一有效约束，偏好不因本轮覆盖改写。 |
| R03 空分析/多物料 | 纯订单准备直接进入订单工作流，不创建空分析委派；直接物料ID由目录校验；多物料输入不静默缩减。 |
| R04 否定/订单查询 | 确定性意图区分不下单、订单状态查询和准备；查询走只读订单工具，不创建草稿/审批。 |
| R05 v2订单读取 | 扩展v2只读能力和双向工具权限校验；写操作仍只能通过订单审批及MutationService。 |
| R06 取消 | router保留取消/限额/时限控制异常；取消不再降级为普通专家失败，复用父run共享预算。 |
| R07 技能 | 启动校验specialist/skill清单；按任务特征合并最小技能集，普通报告加载报告技能；保存skill hash。 |
| R08 版本 | 固定v1 schema、builder、订单节点和checkpoint namespace ABI；持久版本路由继续使用旧实现恢复旧审批。 |
| V01 范围 | 冒号、换行和分句中的事实绑定保留实体范围；多实体/多供应商同值要求明确范围，不能借其他行事实。 |
| V02 快照 | 先按实体/字段确定最新观察快照，再比较数值；同时间冲突拒绝，旧快照不能为当前答案兜底。 |
| V03 多仓 | 计划更新保留既有成功页；renderer按每个 `(warehouse, part)` 范围要求完整证据，不用单一全局最新组漏仓。 |
| V04 单位 | `InventoryView`与报价视图携带目录业务单位；聊天事实及CSV报告保留具体单位；缺单位产物被拒绝。 |
| V05 oracle | 独立live答案oracle检查完整正文，正确结论后追加反向结论或无效供应商推荐仍失败。 |
| P03残留 | 结构化数值/范围/单位硬检查与正文发布门槛继续由确定性review执行；候选正文校验通过前不发布token。截断/反向结论与字段范围反例保留在unit/integration/live oracle测试。 |

## 失败优先与本轮结果

- 修复前保留了对话偏好未保存、路由/订单意图错误、单位与跨实体事实借用、同时间快照歧义、多仓遗漏、oracle相反结论及正文发布问题的确定性失败探针；本轮没有删除/放宽这些拒绝断言。
- 全量第一次offline报告 `.runtime/reports/P07-fix1-offline-final.json` 保留，显示4个unit和多个集成测试使用旧`件`单位、旧报告列数/错误金额，未通过。对具体失败逐个修正成功夹具为种子目录真实单位/金额，错误数量/错误金额反例仍保留；随后全量离线通过。
- 最终命令：`uv run python -m scripts.verify_stage P07 --mode offline --report .runtime/reports/P07-fix1-offline-final2.json`；exit 0、9/9 checks、191 unit、169 integration、38 frontend；compatibility、前端typecheck/build和contract check通过；总时长387.80秒。使用专用验证DB `technologyagent_test_p07_verify`。
- browser首次运行 `.runtime/reports/P07-fix1-browser-final.json` 因本机3030/8030服务未启动失败（连接拒绝），保留该失败报告。按项目`start.ps1`以临时`MODEL_MODE=fake`、专用`technologyagent_test_p07_browser`启动后，重跑`uv run python -m scripts.verify_stage P07 --mode browser --report .runtime/reports/P07-fix1-browser-final2.json`；exit 0、2/2 checks、Playwright Chromium 11/11。偏好保存/恢复/新会话应用、审批页面和历史E2E在此批次运行。
- 报告下载与授权API/事实/范围回读：`uv run pytest tests/integration/test_artifacts.py tests/integration/test_analysis_artifact_flow.py -q --basetemp=.runtime/p07-download`，5 passed。E2E artifact卡片是浏览器展示/链接检查，不替代实际字节；用户已确认HTML显示正常，本轮未重复请求人工检查。其他报告格式人工打开状态沿用P06原证据，未在本轮逐个打开。
- live门禁分别运行`uv run python -m scripts.verify_stage P03 --mode live --report .runtime/reports/P03-fix1-live-final.json`、`uv run python -m scripts.verify_stage P07 --mode live --report .runtime/reports/P07-fix1-live-final.json`；两项均为exit 2 / `not_run`，显式live启用及隔离live配置门槛未满足，零模型请求。P03固定3问题各3次本轮未运行；P07真实委派/审批中断live未运行，未批准或创建订单。历史P06-fix2的P03 9/9不替代本轮新批次。
- GitHub CI与push SHA将在本轮提交后补录。旧phase标签只核对，不移动；live与P03 3×3门槛未关闭，所以不创建`phase-p07-fix1`或其他完成标签。

## 边界

保留9项只读工具与原目录/协议边界；分析专家不可写/自批，owner/run来自可信父上下文，委派共享父预算且不递归。未批准/提交订单，未reset开发库。`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`为既有改动，本轮不纳入提交。没有开始P08。
