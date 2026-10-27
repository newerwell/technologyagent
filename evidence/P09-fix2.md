# P09-fix2：正式报告核验与验收修正

日期：2026-10-27
基线：本地 `main`，开始时 HEAD 与 `origin/main` 为 `1cdb79cbcc48d324f4703c4cf4a3c866fad57fdf`。工作区含更早的 P07/P09 未提交内容；本证据仅记录本次报告/终态修正与验收，不把无关工作区差异算作本次交付。

## 修复内容

- R01：报告兜底按本轮 owner/run、查询参数、范围、同一快照和页码收集库存页；仅在 1..N 页完整、记录数与总数一致且无重复实体时生成完整数据集。两页 W01（P001、P002）回归检查正式正文、来源与完整性；缺页、冲突快照和重复记录不能生成“完整”报告。
- R02：保留明确要求的 `html`/`csv`/`json`/`md` 格式；只有未指定时才采用 Markdown。HTML 回归核对登记产物类型和正文。
- R03：普通 `artifact_ready` 不再满足报告前置条件。正式报告必须关联本轮实际成功的报告工具调用、请求格式、授权数据集/范围/来源，并重新读取产物字节，核对内容和 SHA-256；篡改正文的回归拒绝验证事件。
- R04：取消、期限和共享预算控制异常从报告生成与验证路径继续传播；新增注册表/Graph 回归覆盖三类异常。
- R05：供应商推荐、否定及转折按具体供应商和动作片段判定。保留正确的“S01 而非 S03”，并拦截“S03 报价无效但仍建议采购”。
- 已提交订单的正文复核最多修订 2 次、总计最多检查 3 次；每轮依据已持久化订单事实重建文字。批准、订单、operation、幂等键不重放。集成回归覆盖修订成功和修订耗尽，两种结果均断言只有一个 `order_create` operation。

契约更新见 [CONTRACTS.md](../docs/specs/CONTRACTS.md) 和 agent/tool/service 模块 README。正式报告新增 `report_verified` 事件，仅在文件字节、来源、范围、格式均核验后产生。

## 确定性失败与修复后检查

修复前定向反例实际失败：只用最后一页遗漏 P001；缺页仍被接受；明确 HTML 被降级成 Markdown；已有无关 JSON 产物跳过报告调用；报告控制异常被吞；供应商否定关系误判或误放。修改后：

```text
uv run pytest --basetemp .runtime/pytest-p09-r01-body tests/integration/test_analysis_artifact_flow.py tests/unit/test_required_report.py tests/unit/test_live_acceptance.py tests/integration/test_order_review_loop.py -q
43 passed

uv run pytest --basetemp .runtime/pytest-p09-fixture tests/unit/test_event_contracts.py tests/unit/test_p07_specialists_skills.py -q
20 passed
```

完整离线复跑 `.runtime/reports/P09-fix2-offline-rerun.json`：exit 0，7/7；unit/integration 468 passed，前端 typecheck、38 项测试、build 与 contract check 全通过。首次离线记录 `.runtime/reports/P09-fix2-offline.json` 的 2 个夹具失败保留；更新事件 fixture 与组合委派测试后复跑通过。

完整浏览器复跑 `.runtime/reports/P09-fix2-browser.json`：exit 0，seed 与完整 E2E 通过，Playwright 16/16；覆盖桌面 1440×900、手机 390×844、订单审批、历史恢复、P08 提案金额和本轮相关界面。

## 新固定 live 批次

首次因验收命令进程未继承服务环境变量，启动器返回 `not_run`（`.runtime/reports/P09-fix2-live.json`）；未发起模型请求。随后显式给验收进程设置 `MODEL_MODE=live`、`RUN_LIVE_MODEL=1` 与 `technologyagent_test_p09_live` 后运行完整固定批次：

- 批次：`20261027T080230Z-c7c0fe00bb`，模型配置名 `deepseek-flash`，外层 13 次均执行并保存；总门禁 pytest exit 1，11/13 外层通过。
- P03-A06：固定 3 个问题各 3 次，内层 0/9 通过。缺口、7 天推荐、无有效报价三个问题均未通过完整终态/事实/来源门槛。部分 run 记录 `MODEL_UNAVAILABLE`/`RemoteProtocolError`，也有运行终态与完整分页/事实证据失败；证据不能断定根因只来自网络或只来自模型服务。九轮业务数据库前后快照相同：订单 2、P001/W01 inbound 10、on_hand 20。
- F04：3 次中 2 次通过，1 次在持久决策前返回 `DEPENDENCY_UNAVAILABLE`。两个成功轮各自新增一张 P001 55 套、单价 12.00 元、总额 660.00 元订单；订单 operation 各 +1；I001/W01 inbound 均 10→65、on_hand 均保持 20。失败轮未进入持久提交阶段。
- F08：3/3 通过。修订仅改答案文字，最多 2 次修订/3 次检查；数量、金额和订单号保持已提交事实。
- F11：3/3 通过。
- F12：3/3 通过，含记忆和后续查询事件、DB 偏好前后记录。完整轨迹在对应 `F12-F12-preferences-attempt-N.json`。

外层摘要与 13 个唯一尝试索引：`.runtime/live/p09/attempts/20261027T080230Z-c7c0fe00bb/summary.json`。P03 九条记录在 `.runtime/live/p03-readonly.json`，通过 `acceptance_batch=20261027T080234Z` 唯一筛出；完整事件与每轮数据库快照保留。F04 数据在 `.runtime/live/p04-order-workflow-attempts.json`。这些 `.runtime` 原始证据不纳入 Git。

此前 P09 轨迹中的 F04 一轮及 F08 三轮曾在订单已提交后评审失败；旧记录未修改。当前提交后修订/失败集成回归确认同一 run 仅有一个 `order_create` operation；本批次 F04 两个成功轮各只新增一单和一个 operation。

## 最终矩阵与边界

R01–R05 的确定性缺陷已关闭；offline 与 browser 门禁通过。live 门槛仍未关闭：F02/F03 为 0/9，F04 为 2/3。不能用 F12 的 3/3 替代 P03-A06。P09 仍未完成，不创建/移动 `phase-p09`。

其他本地必需矩阵项 F06、F09、F13、F17、F18 仍为 partial/not_run（逐项见 [FINAL-ACCEPTANCE.md](../docs/specs/FINAL-ACCEPTANCE.md)）；因此本次不宣称本地最终验收关闭。F15/F16 真实 ERP 仍独立 `not_run`。CI 配置范围、远程/V1 隔离、所有正式报告格式的人工打开、23 工具事实汇总和新目录启动/恢复验收均未被本轮结果替代。
