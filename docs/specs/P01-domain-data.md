# P01：本地业务数据与确定性补货

状态：已实施并推送 main；本地规则/API/UI 与 Chrome 浏览器验收通过，GitHub Actions P01 成功；等待 phase-p01 标签核对。依赖：P00。目标：即使不接模型，也能通过页面/API 完成数据查询与正确补货计算。

## 任务

- [x] **P01-T01 定义实体与固定数据。** 在 `contracts/domain.py` 定义 Part、Supplier、Quote、Inventory、历史草稿与订单；`fixtures/v1/` 和 `scripts/seed.py` 初始化 CONTRACTS 案例。生成种子汇总 manifest；校验外键、金额、版本和唯一索引。
- [x] **P01-T02 查询仓储层。** `repositories/catalog.py`、`inventory.py` 实现筛选、分页、详情和汇总，total 按全部匹配记录计算；无记录返回空列表，非法分页返回 422。
- [x] **P01-T03 补货规则。** `domain/replenishment.py` 提供 `preview_replenishment(part_ids,warehouse_id,max_lead_days,now)`；严格使用共享公式；先过滤失效报价、停用供应商与交期，再排序；不由模型计算金额。
- [x] **P01-T04 HTTP 查询与预览。** 实现共享契约 P01 接口；每个结果附 source/as_of/scope，预览返回库存缺口、候选报价、推荐和缺失信息。无法下单的项明确 actionable=false。
- [x] **P01-T05 数据浏览页面。** `frontend/src/app/data/page.tsx` 展示库存、供应商、报价和补货预览；筛选改变重置页码；处理加载、空结果、失败。该页后续作为排查 Agent 回答的业务依据。
- [x] **P01-T06 规则测试与数据证据。** `tests/unit/test_replenishment.py` 覆盖固定案例、负数、MOQ、无报价、过期报价、等于阈值；`tests/integration/test_catalog.py` 核对筛选和总量；记录 P01 evidence。

## 验收

| ID | 输入/操作 | 通过条件 |
|---|---|---|
| P01-A01 | 运行 seed 两次 | 6 零件/3 供应商/8 报价/8 库存/2 历史订单，数量不翻倍 |
| P01-A02 | P001 W01，价格优先 | 可用15、预计25、缺口55；推荐 S02，55件，60500分 |
| P01-A03 | 同上，max_lead_days=7 | 推荐 S01，55件，66000分 |
| P01-A04 | P002 等于阈值；P003 无有效报价 | 前者不预警；后者报告缺口，不生成有效订单候选 |
| P01-A05 | 8条库存，每页3条，遍历分页 | 3页，总数8，无重复遗漏；汇总与manifest一致 |
| P01-A06 | 浏览器按名称/仓库筛选 | 表格与 API 同范围，展示合成数据及时间标记 |

验收结果（2026-10-23，本机 Windows 10）：A01–A06 全部通过；命令、退出码、固定数值和浏览器截图见 [evidence/P01.md](../../evidence/P01.md)。

## 本阶段结束后

得到可独立验证的业务基础。没有 AI 对话和写入订单；后续 MCP、Agent 与报表必须复用这些规则，不能各写一套公式。

## 阶段 Git 交付

- [x] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [x] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [x] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p01` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [x] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
