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
