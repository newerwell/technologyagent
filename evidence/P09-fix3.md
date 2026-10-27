# P09-fix3：报告范围、证据完整性与最终验收补核

日期：2026-10-27。仓库：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`。起始本地 `main`、`origin/main` 均为 `5b8d92ce68ad06e9f8d8e453aa98e518a91e610c`。工作区含先前 P07、P06/P08 和用户保留文件；本轮只提交明确验收相关文件。`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`、审查文档、截图目录和运行轨迹未打包；未读取或提交密钥。日常数据库未重置，live和restore只使用 `technologyagent_test_*` 数据库。

## N01–N04 修复与反例

修复前新增的确定性失败用例覆盖了：用物料子集伪装“全部库存”、混入请求范围外物料、不完整 `inventory_warning`/`quote_list` 页集被报告消费、相同快照在不同分页调用产生不同 `as_of`、底层快照变化，以及带逗号和“而非”表达的供应商判定。修复前报告集成测试出现 5 个预期失败，供应商oracle出现 2 个预期失败。

修复后，报告数据集必须与请求中的全量或排他物料范围一致；库存、预警和报价分页必须页码完整、实体唯一、total吻合且使用工具适配层签发的同一 `snapshot_id`。分页的 `as_of` 可以不同，最终报告保存最新观察时间；查询快照指纹变化时拒绝合并。供应商oracle保留中文逗号的句子上下文，正确识别“推荐S01，同时说明S03无效”以及“推荐S01而非S03”，仍拦截真实推荐S03的错误答案。

正式报告必须先成功生成并登记，再从授权数据集重建预期正文、打开产物回读并逐字节核对格式、范围、来源和正文，成功后才发 `report_verified`。只存在 `artifact_ready` 或调用事件不够。取消、期限和共享预算异常仍向run控制流传播。

修复后定向命令：`uv run pytest tests/integration/test_analysis_artifact_flow.py tests/integration/test_graph_upgrade.py tests/unit/test_live_acceptance.py tests/unit/test_required_report.py tests/unit/test_preference_review.py -q`，通过；随后完整离线集成见下文。

## 订单正文金额与修订契约

F08原始断言用字符串包含`660`判定金额，错误拒绝了模型以千分位写出的`66,000分`。本轮没有放宽数值条件：live验收改为调用现有订单事实校验器，要求单号、数量/业务单位、订单总额字段、金额单位和持久订单范围一致；新增反例确认金额、数量或单位错误时失败。单位解析补入物料单位“片”。三次新的F08真实尝试均通过，提交订单数、operation数、审批数分别只增加一次，库存每次保持 `on_hand=20`、`inbound=10→65`。

P04/P05已明确的订单正文契约保持最多2次纯文本修订、最多3次检查。每次修订只检查持久订单、operation和审批事实，不再次提交、不换幂等键。两次修订后仍失败时，run以失败终态保留已提交事实并明确不自动重放。本轮更新了 `docs/specs/CONTRACTS.md` 与模块README，不能以放宽数值断言来提高通过率。

## 离线、browser与本地矩阵

- 完整离线：`.runtime/reports/P09-fix3-offline.json`，exit 0，7/7；后端unit/integration 479 passed，前端38项、typecheck、build、compatibility、contract check均exit 0。
- 完整 browser：第一次 `.runtime/reports/P09-fix4-browser.json` 失败，因此前live API进程仍在运行，chat-flow收到live失败终态。该失败保留。显式停止并以fake模式/独立 `technologyagent_test_p09_browser` 重启后，`.runtime/reports/P09-fix4-browser-rerun.json` exit 0，Playwright 16/16。
- F06：全量离线通过；图升级集成测试确认v1等待审批checkpoint经v1恢复批准，重放只落一个订单，v2新run写入v2 namespace。
- F09：bar/line/pie三图实际查看；md/html/csv/json四种文件解析中文、scope、金额、source_refs；HTML实际浏览器打开并核对报告正文和来源时间。截图和解析材料保存在`.runtime/reports/P09-f09-artifacts/`与`evidence/p06-artifacts/`。
- F13：`uv run pytest --basetemp .runtime/pytest-p09-f13-mcp3 tests/integration/test_mcp_tools.py -q` exit 0，5 passed。23个只读参考工具实际调用；直接写入关闭、非法schema被拒绝，供应商/物料/订单/库存/流水集合前后不变。
- F17：完整桌面/手机browser exit 0，Playwright 16/16，覆盖1440×900、390×844、聊天刷新恢复、审批和P08提案金额卡片。
- F18/N05：从origin新检出代码SHA `a9047b3c8cc09022c84f5da521d3a58cfdbfd40d`；`uv sync --frozen`、`npm ci`均exit 0。fake模式在独立test库启动，health/ready通过。为test库加入一个ready artifact，停止应用后备份并恢复到新的`technologyagent_test_p09_restored`及独立storage目录；重启恢复服务后API下载返回67字节，SHA256 `c98f477cbb378402a1a8fa1f80c807f029f302dd72f6561634626828dc2c4c46` 与备份前一致，恢复后业务种子计数和artifact关联均核对一致。验证后应用已停止，3030/8030/9030均不再监听。

## 新真实模型批次与失败分类

固定批次：`20261027T093027Z-aa523b4add`，模式live，数据库`technologyagent_test_p09_live`，13条外层记录，10通过、3失败。所有尝试路径在`.runtime/live/p09/attempts/20261027T093027Z-aa523b4add/summary.json`索引；P03每题每次完整轨迹追加到`.runtime/live/p03-readonly.json`。历史批次未覆盖。

P03-A06三问×三次为8/9：W01缺口3/3、7天内报价3/3、P003最低价2/3。唯一失败轮所有模型调用正常结束，终态为`REVIEW_FAILED/SEMANTIC_COMPLETE`，P003的完整“无有效报价”证据未通过评审；数据库前后快照相同。这是语义/证据失败，不是传输失败。上一批P03 9/9通过也保留，不能替代本次新批次。

本轮对历史P03 0/9失败分类进行了核对：旧轨迹中7次`MODEL_TIMEOUT`、1次`MODEL_UNAVAILABLE/ConnectError`、1次`RemoteProtocolError`，逐项作为模型超时/连接/协议传输错误记录，不计作业务答案事实错误。当前固定批次中没有把传输错误改写成事实错误。

F04订单工作流为2/3。两次成功与一次失败均经过隔离种子重置；失败轮在订单和库存事务提交后因最终说明评审未通过而终止。失败轮数据库为订单数2→3、成功`order_create` operation仅增加1、审批消费仅增加1、`inbound=10→65`、`on_hand=20`。未发生第二次提交。本批未复现旧的持久决定前依赖失败；该历史依赖错误仍保留为单独失败证据，不能据本批称原错误已修复。

F08 3/3、F11专家委派3/3。F12外层固定场景为2/3；三次外层尝试各含3组偏好保存/查询，共9组内部尝试8/9通过。失败外层中的最后一组查询未完成语义/事实评审，答案未通过P001缺口事实门槛；偏好持久化与数据库快照证据保留。最终live检查命令exit 1，不满足固定真实场景通过门槛。

## N05 Git交付与阶段边界

实现与回归提交：`a9047b3c8cc09022c84f5da521d3a58cfdbfd40d`；已显式推送`origin/main`并确认远程SHA一致。新检出checkout了该SHA并执行了依赖安装、启动和恢复下载验证。GitHub Actions run `40482819592`结论success，唯一job为`p06-offline`；该CI不是P09 live验收。

F15/F16真实ERP未运行：没有指定的ERP测试环境与授权。本地最终矩阵仍因P03-A06、F04、F12真实模型场景未全通过而开放，不创建或移动`phase-p09`，不开始P10，不把本机版本称为生产上线。
