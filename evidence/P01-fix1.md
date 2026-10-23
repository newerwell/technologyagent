# P01-fix1 补修证据

status: implemented / offline_verified / browser_verified / ci_verified
stage: P01-fix1
delivery_state: pushed_main（858916d；CI run 39980552764 success）；phase-p01-fix1 指向最终记录提交
base: phase-p01 232826336d29c19decf808c757cd0658536a8d02
environment: Windows 10.0.19045；venv Python 3.13.14（uv 0.11.27）；Node 24.11.0；npm 11.6.1；Next.js 16.4.2；MongoDB mongo:8.0 replica set `ta-rs`（127.0.0.1:27027）
model_mode: fake（无 MODEL_API_KEY；本补修不调用模型）
data_source: local_seed（fixtures/v1）
scope: shared_catalog

## 修复范围

### P01-F01 默认 seed 保留已有状态

- `services/seeding.py` 默认由 `replace_one` 改为固定 `_id` + `$setOnInsert` + upsert：只补缺失的合成记录，不覆盖已有记录、业务修改或 version。
- `SeedSummary` 明确输出 `fixture_counts`（种子输入数量）与 `database_counts`（执行后实际 DB 数量），不再用单一 `counts` 混淆。
- 显式 `--reset` 仍只允许 `technologyagent_test_*`；默认 seed 不删除数据。

### P01-F02 在途对账与固定预警集合

- 修正 fixture：
  - I004：on_hand 10→15，inbound 5→0，保留 safety 15/target 30 → projected 15=safety，不预警。
  - I006：on_hand 8→12，其余不变 → projected 10=safety 10，不预警。
  - I007：on_hand 0→5，inbound 2→0，其余不变 → projected 5=safety 5，不预警。
- `validate_bundle` 新增 `validate_inventory_reconciliation`：按未关闭订单（非 completed/cancelled）的 `quantity - received_qty` 汇总每个 part/warehouse 的 inbound，逐项等于库存 inbound；未收量为负、未收订单行无库存、inbound 不等都在写库前拒绝。
- 精确预警集合只有 I001、I005；O001 未收 10 件仍是 P001/W01 的唯一 inbound 依据；O002 已完成不产生 inbound。未新增第三张历史订单，P001 仍为 15/25/55、60500/66000。
- manifest/hash 重新生成；仓库/全量汇总与预警数量来自实际规则，不手写固定值。

### 旧基线显式迁移

- 新增 `services/baseline_repair.py` 与 `scripts/repair_p01_baseline.py`：
  - 默认 dry-run，打印 before/after 备份与变更列表；只有 `--apply` 才写。
  - 仅处理 I004/I006/I007，要求完整旧字段、schema_version=1、version=1 完全匹配。
  - 在真实 Mongo 事务中更新，version 递增到 2；发现库存被修改、version 变化或存在相关新增订单时拒绝覆盖并报告冲突。
  - 不在 API 启动时自动执行，不提供 reset 开发库。
- 当前开发库 `technologyagent_dev` 只读检查：P01 业务 collection 均为 0 条，I004/I006/I007 不存在，因此未执行修正、未 reset、未写入开发库。

### P01-F03 预览绑定参数与数据代次

- `ReplenishmentPreview` 增加 request generation：每次物料/仓库/最大交期/目录代次变化先失效旧请求并清 preview/meta/error/loading；旧请求的成功、失败、finally 只有 requestId 仍匹配时才可写状态。
- 增加 `catalogGeneration`，目录刷新/失败/筛选实际变化时统一失效；DataPage 分离目录请求与库存分页请求，翻页只重取库存，不清空 parts/选择。
- 当前物料被筛掉时先清旧预览再选首个有效物料，避免 P001 选择配 P003 结果。

### P01-F04 会话失败后可刷新恢复

- DataPage 分离 `sessionStatus`（loading/ready/error）与 catalog/inventory loading；刷新时若会话未就绪，先 `ensureLocalSession`，成功再加载，失败保持按钮可用。
- 共用 in-flight session promise，避免重复点击并发创建会话；数据 401 只进入用户可刷新的 error 状态，不自动无限重试；403 不触发认证循环。
- 初次网络失败后刷新成功；页面无需整页重载。

## 先失败后修复的测试证据

### 后端（修复前）

`uv run pytest tests/integration/test_seed.py -q`：4 failed，3 passed。

- I001 inbound 被 seed 重置为 10（期望 65/version2）。
- P001 name 被重置为 fixture 值，业务修改丢失。
- fixture inbound 与未关闭订单不一致（I004=5、I007=2 无订单依据）。
- 预警集合多出 I006、I007。

### 前端组件（修复前）

`npm --prefix frontend run test -- --run src/components/data/ReplenishmentPreview.test.tsx`：4 failed，均为需求复现：

- W01 旧请求成功后仍显示 ¥605.00。
- 旧 rejected/finally 清掉新请求 loading。
- 改最大交期后仍保留旧金额。
- P003 预览在目录移除 P003 后仍保留 ¥0.00。

`DataPage.test.tsx` 新增 2 个失败：翻页后 parts 请求从 1 变 2；首次会话失败后刷新没有第二次 `/api/session/me`。

修复后同一批测试全部通过，且新增目录代次、完成/取消订单、inbound 对账拒绝等断言。

## 实际执行

| 检查 | 结果 |
|---|---|
| seed 单元/集成 | `test_seed.py` **9 passed**；两轮 seed 计数一致；I001 65/version2、O001 shipped/version2、合法 P001/W01 55 件新订单与草稿保留；缺 I008 只补该条 |
| 对账 | 独立断言 actual inbound == 未关闭订单剩余量；I001=10，I004/I006/I007=0；完成/取消不产生 inbound；故意改 inbound 被 `validate_bundle` 拒绝 |
| 旧基线迁移 | 4 passed：dry-run 不写、apply 事务更新 3 条并 version=2、修改库存冲突拒绝、相关新增订单拒绝、当前 fixture no-op |
| 后端集成 | `uv run pytest tests/integration -q`：**59 passed**（含 P00 回归与 P01 新断言） |
| 单元测试 | `uv run pytest tests/unit -q`：**25 passed** |
| 前端测试 | 3 files、**12 passed**：StatusPanel 2、DataPage 5、ReplenishmentPreview 5 |
| P01 阶段验证 | `uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-fix1-offline.json`：exit 0，**9/9 checks**，165.45s |
| 契约检查 | `uv run python -m scripts.export_contracts --check`：exit 0 |
| 前端 typecheck/build | exit 0；静态路由含 `/`、`/data`、`_not-found`、`/icon.svg` |
| 真实浏览器 | Chrome headless：首次会话请求 abort→错误→刷新恢复；受控延迟旧 preview 不回填；见下 |
| GitHub Actions | push `858916d` 后远程 run [39980552764](https://github.com/newerwell/technologyagent/actions/runs/39980552764) | success；checkout/setup/install/init/verify/upload 全部步骤 success |

verify_stage 明细：

```text
db_init            exit 0  passed    1168.66 ms
compatibility      exit 0  passed   17638.73 ms
seed               exit 0  passed    2442.32 ms
unit_tests         exit 0  passed    3071.29 ms  (25 passed)
integration_tests  exit 0  passed  117861.29 ms  (59 passed)
frontend_typecheck exit 0  passed    5273.95 ms
frontend_tests     exit 0  passed    7217.06 ms  (12 passed)
frontend_build     exit 0  passed    9959.25 ms
contract_check     exit 0  passed     812.36 ms
```

## 固定数据与汇总

```text
P001/W01: 20/5/10/30/80 -> available 15, projected 25, shortage 55
price priority: Q02 1100, MOQ 1, 12 days -> 55 * 1100 = 60500
max_lead_days=7: Q01 1200, MOQ 10, 5 days -> 55 * 1200 = 66000
W01 summary: records 5, on_hand 107, reserved 8, inbound 10, available 99,
             projected 109, safety 80, target 180, shortage 101, warning 2
W02 summary: records 3, on_hand 70, reserved 5, inbound 0, available 65,
             projected 65, safety 40, target 80, shortage 20, warning 0
total: records 8, on_hand 177, reserved 13, inbound 10, available 164,
       projected 174, safety 120, target 260, shortage 121, warning 2
warning set: I001 (55), I005 (36) only
fixture hash: sha256:d2df3a511837d5f6b6e386d2437d0149a169dbe3175ae838f03806524cf90ffa
```

## 浏览器证据

脚本：Chrome headless 打开 `/data`，拦截首次 `/api/session/me` 使其失败，再点刷新；对首次 preview 请求延迟 1.5s 后切仓库。

- 首次会话失败：页面显示真实网络错误，刷新按钮可用；点击后会话恢复（`/api/session/me` 共 3 次：abort、401、创建后读取），业务数据加载。
- 修正后 W01 预警：“当前预警 2 条”，只有 W01/P001 缺口 55、W01/P003 缺口 36；无 P004 预警。
- W01 汇总：107/99/109/101/2。
- 旧 preview 延迟：W01 请求 pending→切 W02→旧响应返回；页面没有金额/旧结果（stale total count=0）。
- 价格优先：¥605.00；改最大交期清空旧金额；7 天重算 ¥660.00。
- P003 预览 ¥0.00/无可确认推荐；翻到库存第 2 页后选择仍为 P003，结果仍为 P003 的 ¥0.00（一致）；改为 P001 立即清空旧结果。
- 数据源 local_seed 可见；页面无横向溢出；Cookie HttpOnly/SameSite=Strict。
- Console 仅首次故意 abort 的 `net::ERR_FAILED` 和创建会话前的预期 401，无 pageerror。

截图：[evidence/P01-fix1-data.png](../evidence/P01-fix1-data.png)

组件探针（Vitest/jsdom，10 个 DataPage/Preview 用例）覆盖旧成功/旧失败/finally、参数变化、目录代次、P003 筛选变化、翻页不清 parts、首次会话失败刷新；真实 Chrome 证据覆盖受控网络失败与延迟。两者不互相冒充。

## 未运行与限制

- 真实模型、AI 对话、订单写 API、MCP 产品服务、专家/技能、沙箱、ERP 未实现/未运行；P01-fix1 不改变这些边界。
- Playwright E2E 未启用；浏览器脚本为手工验收，不进入 CI。
- 开发库未执行 baseline repair：业务 collection 为空，无需修正；没有对开发库 reset 或写入。
- live/browser verify_stage 模式仍无检查，返回 not_run。GitHub Actions 已对 858916d 实际执行并通过（run 39980552764）。
- 旧 `evidence/P01.md` 的 warning 4/总缺口 128 是修复前历史记录，已由本文件取代；原记录不删除。
