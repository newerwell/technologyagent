# P09 最终补修证据

status: in_progress
stage: P09
environment: Windows / uv 项目环境 / npm 前端锁文件；本机 Mongo replica set 与 Docker daemon 当前不可用
model_mode: 未运行 live
data_source: 新测试仅用固定时钟与内存合成数据；本机 local_snapshot 未作为采购夹具

## 任务卡 0：必要功能基线

- commit：`b3a0d899d3695f45cba489c8869bd6d0c2576c1c`；推送后 `origin/main` 相同。
- 纳入库存快照适配及API/MCP/本地工具/UI接入、事实与约束处理、配置、对应测试和文档；未纳入 `.env`、原始库存、metadata、运行数据。
- 保留未提交审查文档、截图、`.dsh-meow/`、`frontend/AGENTS.md`。
- `tests/unit/test_inventory_snapshot.py`：3 passed；`tests/unit`：263 passed；前端10个文件/39项 passed；typecheck passed。
- `tests/integration/test_inventory_snapshot_routes.py` 曾因默认Mongo副本集名称与standalone不符失败；用directConnection后连接拒绝，Docker daemon不可用。此项为环境阻断，不记为产品通过。

## 任务卡 1：停用物料预览

反例 RED：`uv run python -m pytest --basetemp .runtime/pytest-task1-red tests/unit/test_replenishment_service.py -q -rs`，2 failed。旧实现将 `active=False` 的P001仍返回 `actionable=True`、quantity=55、total_cents=66000、Q-P001。前端RED也观察到原页面只显示 `part_inactive` 英文标记，未显示用户可读原因。

实现：`ReplenishmentService.preview`对停用物料保留真实 available=15、projected=25、shortage=55、warning=true，并使用 `PreviewLine.model_validate`重建不可采购结果；候选报价/推荐/数量/总额清零并添加`part_inactive`。MCP工具描述和数据页解释“物料已停用”；`DraftService.prepare`既有409拒绝保持不变。

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest --basetemp .runtime/pytest-task1-green2 tests/unit/test_replenishment_service.py tests/unit/test_replenishment.py -q -rs` | 14 passed，exit 0；含停用/启用混合预览及草稿409且预览不运行 |
| `npm --prefix frontend test -- --run src/components/data/ReplenishmentPreview.test.tsx` | 6 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task1-full-unit tests/unit -q -rs` | 266 passed，exit 0 |
| `npm --prefix frontend run typecheck` | exit 0 |

任务卡1提交：`881ac46de956aff29e428f6d050cfa47d49f308e`；推送后`origin/main`相同。完整P09 offline/browser/live及Mongo集成尚未重跑；不创建`phase-p09`，不表示P09完成。

## 任务卡 2：保留模型修订正文

反例 RED：`uv run python -m pytest --basetemp .runtime/pytest-task2-red tests/unit/test_graph_answer_preservation.py -q -rs`，1 failed。首轮正文缺少报价失效原因，语义评审要求补充；旧执行器在每轮评审前以核验核心文本替换模型回答，导致第二轮模型修订仍被覆盖并最终失败。

实现：核验核心事实只附加到每次模型调用的系统消息副本；`state.messages`、原始请求和模型最终正文保持独立。确定性审查仍先执行，语义审查通过后才发布正文，未引入第二个最终回答字段。

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest --basetemp .runtime/pytest-task2-green tests/unit/test_graph_answer_preservation.py -q -rs` | 1 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task2-unit tests/unit/test_graph_answer_preservation.py tests/unit/test_verified_answers.py tests/unit/test_deterministic_review.py tests/unit/test_fact_checks.py -q -rs` | 28 passed，exit 0 |

任务卡2源码提交：`16c4c3afae25815477a3fabfcdd90a7028038355`；push后远端SHA相同。P09完整offline/browser/live门禁及真实模型批次均未在本卡执行。

## 任务卡 3：提交事实快照与订单说明覆盖

### 反例与修复

- RED：订单说明只含 `PO-1`、没有数量或总额时，旧 `_order_answer_fact_check` 会通过。新增反例要求单号存在时仍必须覆盖每条已知数量和订单总额。
- RED：订单仓储此前不接受 `verification_facts`（`TypeError: unexpected keyword argument`）；新仓储测试确认该事实要随订单插入保存。
- RED：语义评审此前会丢弃订单的提交事实快照；回归扩展后因 `verification_facts` 不在白名单而 `KeyError`。
- RED：正确的“报价交期不代表已经到货”措辞被词面规则误判为实际到货；新增否定上下文测试复现。
- 修复：批准事务从同一事务读取的启用物料、有效报价和 run 的已保存订单意图构造订单事实快照，并与订单、inbound、审批消费、operation结果原子提交。保存数量/单位/仓库、quote/supplier、报价交期和观察时间、最大交期约束；没有单位时不从当前目录补写。
- 修复：结算只读取成功 operation、持久订单、已消费审批和提交快照；不再查询当前目录补单位。普通订单接口剥离内部快照；语义评审只收到快照白名单字段。
- 修复：正文硬门槛要求单号、每项数量、订单总额；有保存的用户交期时要求覆盖用户约束和批准报价交期，并拦截没有收货事实支撑的肯定收货陈述。明确否定的“不代表已经到货”可通过。两次纯正文修订仍不会调用订单写服务。

### 实际检查

| 检查 | 结果 |
|---|---|
| `uv run python -m pytest tests/unit/test_order_review_bounds.py tests/unit/test_semantic_review.py tests/unit/test_order_verification_persistence.py -q -rs` | 13 passed，exit 0 |
| `uv run python -m pytest --basetemp .runtime/pytest-task3-unit tests/unit -q -rs` | 270 passed，exit 0 |
| `uv run python -m pytest tests/integration/test_order_review_loop.py -q -rs` | 3 errors，exit 1；测试夹具连到 `127.0.0.1:27027` 的 Mongo standalone，但要求副本集 `ta-rs`。未执行集成体，故不记为通过；Docker daemon仍不可用。 |
| `uv run ruff check`（本任务触及文件） | exit 1，报告26项，含多个原有导入/异常处理/格式问题；本任务未把既有 lint 问题当作验收通过。 |
| 真实模型/live、P09 offline/browser | 本卡未运行；Mongo副本集不可用，且完整批次不属于本任务的定向门禁。 |

新增 Mongo 集成断言保留 55 套、66000分、最大交期7天、批准报价交期5天及报价/供应商ID，并要求只写一张订单、一个成功operation，inbound 10→65、on_hand保持20。由于 Mongo 服务环境阻断，本轮这些事务事实没有被实际执行核验，状态为待补验。

提交：`d7a4907714b0dde01cf9ddc0afaeab37604f6c75`，已推送；`git ls-remote origin refs/heads/main`核对为同一SHA。交付记录提交`bfe03f4e0d7f5ae2994ac3144e4668a90a243e9f`远端一致；GitHub Actions run [40676320946](https://github.com/newerwell/technologyagent/actions/runs/40676320946) 的`p06-offline`在本次检查时仍`in_progress`，不是P09专属门禁。本任务不创建或移动 `phase-p09`。
