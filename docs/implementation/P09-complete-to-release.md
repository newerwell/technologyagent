# TechnologyAgent：P09 从当前状态到完整交付的实施计划

> **给实施 Agent：**使用 `superpowers:executing-plans` 逐卡执行。本文只是一份实施计划，复选框不表示已经完成。每卡必须经过“读代码 → 添加反例 → 确认失败原因 → 修复 → 定向回归 → 更新证据 → 显式提交 → 推送及核对”。当前卡未通过，不开始下一卡，不创建 `phase-p09`。

**Goal：**关闭当前已确认缺陷，在同一份已推送源码上通过全部本地必需场景、固定真实模型排程和全新检出的完整备份恢复，再恢复用户日常环境并交付阶段标签。

**Architecture：**保留现有 API、MCP、业务服务、版本图、事务及 Provider 边界。仅修正验收业务时钟、正文主张提取、收货断言、独立判分和评审诊断；业务真值始终来自工具及持久记录，模型只生成受核验的说明。

**Tech Stack：**Python / FastAPI / Pydantic / LangGraph / MongoDB `ta-rs` / MCP；Next.js / TypeScript / Playwright；PowerShell 7 / Docker / GitHub Actions。沿用 `uv.lock` 与 `frontend/package-lock.json`，本轮不升级依赖。

**Spec：**[共享契约](../specs/CONTRACTS.md)、[最终验收矩阵](../specs/FINAL-ACCEPTANCE.md)、[P09 规格](../specs/P09-acceptance-operations.md)、[原最终补修手册](./P09-final-closure.md)、[Git 交付规则](../delivery/GIT_WORKFLOW.md)。原文档里的历史“passed”不能覆盖后续新增验收要求。

编写日期：2026-11-09。项目绝对路径：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`。

## 1. 先看结论和当前基线

**P09 尚未完成，当前不能创建或推送 `phase-p09`。** 原 C00–C07 已有大量实际实现，不从 P00 重写；本计划接续这些成果，替代旧手册的“下一步执行顺序”，不降低原规格。

### 1.1 已核对的事实

| 项目 | 当前事实 | 接手时怎么处理 |
|---|---|---|
| 本地 HEAD / 远端 main | `8538f4c4971baefc4a2b387357b8a0fba318faab`；编写时重新 `ls-remote` 一致 | 开始时再核对，不硬退回此 SHA |
| 本地 offline | 批次 `20261109-092100`，8 个检查通过；backend 660、frontend 46 | 只证明该提交，不能替代新修复源码的门禁 |
| 云 CI | 同一 SHA 的 run `42544986861`，`p09-offline` 与 `p06-offline` 成功 | 新源码提交必须核对自己的 CI |
| 完整 browser | 同批次 16 passed，含双尺寸实际操作、下载和重启 | 保留，不冒充后续新源码通过 |
| 固定 live | 13 个外层记录，4 通过、9 失败；P03 内部 2/9 | 必须修复并产生全新完整批次 |
| 固定业务时钟 | 已在当前工作区编码并有定向结果，**尚未提交/推送** | 按 L01 审查、补证、提交；不要重新覆盖整套实现 |
| 新检出完整恢复 | 测试代码已推送；仅类型检查/收集完成，**没有实际执行完整流程** | L08 必须真跑，不能用旧单文件恢复代替 |
| 正常环境恢复 | 最终恢复未完成；不能声称用户已回到 daily live/snapshot | L09 实际恢复并验证 |
| 标签 | 本次远端查询未发现 `phase-p06` / `phase-p09` | 按各自完成条件补建，不提前建、不移动旧标签 |
| 当前运行环境 | 编写时 Docker Linux engine 管道不可连接，`127.0.0.1:8131/ready` 连接拒绝 | 是环境当前状态，不是新增业务失败；L00 检查并恢复 |
| 真实 ERP | 未联调；F15/F16 `not_run` | 写 capability 继续关闭，不影响独立记录本地版本验收 |

报告实际位置（均在被忽略的运行目录，不加入 Git）：

```text
.runtime/reports/P09-20261109-092100-offline.json
.runtime/reports/P09-20261109-092100-browser.json
.runtime/reports/P09-20261109-092100-live.json
.runtime/live/p09/attempts/20261109T013237Z-5c620c8e57/summary.json
.runtime/live/p03-readonly.json
.runtime/live/p04-order-workflow-attempts.json
.runtime/live/p05-a04-attempts.json
.runtime/private/p09-final-session.json
```

`summary.json` 的失败为 F02-F03×1、F04-order×3、F08-review×1、F11-specialists×3、F12-preferences×1。通过为 F08×2、F12×2。不得删除失败、修改失败评分或增加尝试次数挑成功。

### 1.2 必须保留的现有成果

| 成果 | 已推送提交 / 证据 | 本轮要求 |
|---|---|---|
| R8 默认与专用端口一致 | `6430901`，`evidence/P09-R8.md` | 保留两套端口支持及真实下载证据 |
| C01 Provider 总 deadline | `50fc8a7`，`evidence/P09-C01.md` | 保留超时取消、分页总预算及有限值检查 |
| C02 库存别名与必需字段 | `00fbfcc`，`evidence/P09-C02.md` | 保留 0、null、bool、未知字段边界 |
| C03 审批 payload / version | `2a8fbbf`，`evidence/P09-C03.md` | 不放宽 owner、hash、版本或批准约束 |
| C04 真 MCP 非法输入 | `ae0c57b`，`evidence/P09-C04.md` | 保留 null 拒绝与 23 项实际 wire 测试 |
| C05 验收环境与端口 | `767027a`，`evidence/P09-C05.md` | 保留完整环境还原及重启配置一致 |
| C06 隔离备份恢复实现 | `81bcb71`，后续 `aa533da` / `8538f4c`，`evidence/P09-C06.md` | L08 执行实际完整恢复，不另建简化版 |
| C07 独立 P09 CI | `4e4e219` 及后续提交，`evidence/P09-C07.md` | 保留 P06 job；核对新候选 P09 job |

短 SHA 用于定位历史；接手时用 `git show <SHA>` 确认可达，不根据短 SHA 猜测文件内容。

## 2. 全局约束与审查重点

### 2.1 所有任务共同遵守

- 只补修 P09，不开始 P10，不重写项目，不复制 ERP-AGENT 的源码或配置。
- 写测试只使用 `technologyagent_test_*`，专用 Mongo 为 `127.0.0.1:27028`、`ta-rs`。不重置 `technologyagent_dev`，不改旧 `mongo-data`。
- `local_seed` 用于完整合成采购验收；`local_snapshot` 用于用户库存查询。不得给用户快照补造报价、预留、在途或目标库存。
- 不绕过事实、单位、来源、范围、审批、owner、版本、幂等、预算、取消、权限和图版本兼容检查。
- 不修改固定 live 问题、排程、次数或成功标准来取得绿灯；测试不允许 `route.fulfill` 伪造成功业务响应或报告字节。
- 不打印模型密钥、Cookie、session token 或完整 `.env`。不将原始库存、metadata、数据库、`.runtime`、storage、下载、依赖、日志提交。
- 不使用 `git add .`、`git reset --hard`、`git clean` 或强推。无关修改、未跟踪文件和旧失败证据原样保留。
- 清理仅限本轮创建且不再需要的路径；先核对绝对路径在预期目录内，不删除命名卷或历史证据。
- 如果测试未进入测试体（Docker、权限、依赖、端口、Mongo fixture 失败），先修环境再重跑；不能作为产品 RED。
- 每卡更新交接及证据，提交推送后核对远端；推送失败保留本地提交并停止叠加交付。

### 2.2 五个必须在所属卡覆盖的易漏边界

1. **系统日期跨过报价到期日：**只固定验收业务判价时钟；session TTL、run 时限、operation lease 仍实时计时。L01。
2. **多行与表格相邻实体：**字段不能串列，P001 与 P004 不得合成一个 scope；实体标题换行仍能继承。L02。
3. **否定后又肯定或换物料：**“未收货。但已到货”不能被放行；P003 无报价不能连坐 P002 的有效推荐。L03/L04。
4. **失败答复被丢失：**每轮真实送审正文能在授权 trace 回放，未核验正文不能作为成功消息发布；旧 review 事件仍可读取。L05。
5. **恢复后身份、版本、源库与 artifact 对应：**比较全库而非少量 count，验证真实审批 ID、异 owner 404、源库不变。L08。

## 3. 文件职责及任务依赖

以下“新增”是计划目标，尚不存在；“已有”在接手时仍需核实。不要把计划中的新函数当作当前公开 API。

| 卡 | 文件 | 职责 |
|---|---|---|
| L00 | `AGENTS.md`、`docs/delivery/HANDOFF.md`、私有 `.runtime/private/` | 重建实际基线和可恢复环境，不提交私有材料 |
| L01 | `backend/app/config.py`、`bootstrap.py`、`services/{drafts,mutations,business_mutations,readiness}.py` | 只给业务判价注入验收时钟 |
| L01 | `backend/app/agent/local_tools.py`、`mcp_server/server.py` | fake 工具注册表和实际 MCP 复用同一业务时钟 |
| L01 | `.env.example`、`scripts/p09_acceptance_env.ps1`、`frontend/src/lib/p09-runtime-config.*`、两类 E2E | 显式开关、严格隔离、重启继承和恢复 |
| L02 | `backend/app/agent/fact_checks.py`、`graph.py` | 主张字段/单位/范围提取及提示词；不降低验证器强度 |
| L03 | `backend/app/services/order_workflows.py` | 订单说明的收货断言、事实覆盖与修订 |
| L04 | `scripts/live_acceptance.py` | 独立 live oracle，保持与生产核验实现独立 |
| L05 | `backend/app/contracts/events.py`、`agent/harness.py`、`services/order_workflows.py` | 严格、向后兼容的送审输入记录及两个入口发布 |
| L05 | **新增** `backend/app/agent/review_snapshot.py` | 只把已核验事实转换成可回放的白名单快照，不负责判分 |
| L05 | `scripts/export_contracts.py` 及生成的 schema/TS | 契约源与消费端同步，不手改生成文件 |
| L06 | 已有定向测试和新测试文件 | 联合回归，验证没有跨模块回退 |
| L07 | `scripts/run_acceptance.py`、既有 CI、报告 | 不必修改实现；执行新候选完整门禁 |
| L08 | `tests/acceptance/clean-restore.spec.ts`、`scripts/{backup,restore,p09_restore_facts}.*` | 全新检出真实完整恢复 |
| L09 | `FINAL-ACCEPTANCE.md`、`STATUS.md`、`HANDOFF.md`、`evidence/` | 日常环境、最终矩阵及 Git/标签交付 |

顺序固定：`L00 → L01 → L02 → L03 → L04 → L05 → L06 → L07 → L08 → L09`。测试可以复用，任务不合并成一次无法审查的大提交。

## 4. L00：重建基线，保护已有工作区和本机数据

**输出：**私有环境快照、准确文件分类、隔离 Mongo 可用证明、下一卡入口。此卡不提交产品源码。

- [ ] 在 PowerShell 7 执行并记录结果：

```powershell
Set-Location -LiteralPath 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
$PSVersionTable.PSVersion
git status --short
git rev-parse HEAD
git log -8 --oneline
git diff --stat
git ls-remote origin refs/heads/main 'refs/tags/phase-p06*' 'refs/tags/phase-p09*'
git check-ignore .env data/inventory_snapshot.json data/inventory_snapshot.meta.json .runtime
```

- [ ] 读取项目 AGENTS、蓝图、共享契约、最终矩阵、Git 规则和本文。发现 HEAD 漂移时先读新增提交，不覆盖后续工作。
- [ ] 按下表逐个查看 diff。不要把“只在工作区”写成“远端已实现”。

```text
已有但未提交的 Clock 改动：
.env.example
backend/app/agent/local_tools.py
backend/app/bootstrap.py
backend/app/config.py
backend/app/services/business_mutations.py
backend/app/services/drafts.py
backend/app/services/mutations.py
backend/app/services/readiness.py
frontend/src/lib/p09-runtime-config.cjs
frontend/src/lib/p09-runtime-config.test.ts
mcp_server/server.py
scripts/p09_acceptance_env.ps1
tests/acceptance/clean-restore.spec.ts
tests/e2e/order-flow.spec.ts

Clock 新测试，当前未跟踪：
tests/unit/test_acceptance_business_clock.py
tests/integration/test_fixture_business_transactions.py

交接文件另有修改：
docs/delivery/HANDOFF.md
```

其他未跟踪的 `.dsh-meow/`、旧 reviews、`frontend/AGENTS.md`、截图不是上述源码；逐个归类，不整体暂存。截图只有核对本轮 artifact/run/文件名/哈希且确属交付需要时才显式加入。

- [ ] 可把 `git diff --binary` 和两份未跟踪 Clock 测试备份到本次私有子目录。先核对 diff 不含私密文件，不依赖“创建 stash 后清空工作区”。
- [ ] 原始 C00 私有基线位于 `.runtime/private/p09-final-original-env.json` 与 `p09-final-original-local-data.json`。**先检查是否存在，不覆盖**。若缺失，记录“旧基线缺失”，从 `.env` 和进程配置读取白名单配置重建；密钥保持原文件中，不输出。
- [ ] 保存环境变量的“是否存在 + 原值”，涵盖 helper 的全部 `managedNames`，另含 `P09_CLEAN_ACCEPTANCE`、`P09_EVIDENCE_BATCH`。不得在每次切换测试模式后覆盖为新的“原环境”。独立工具进程的 `$env:` 与全局变量不能跨调用自动继承，须在同一 PowerShell 会话执行模式切换和启动，或从私有快照显式恢复。
- [ ] 只读检查 `docker info`、`docker ps`、容器 inspect 的卷/端口、`.runtime/processes.json` 与服务 readiness。Docker 未运行时可按既有授权隐藏启动 Docker Desktop，等待引擎可用后再启动专用 compose；不要先要求用户重复操作。
- [ ] 专用 compose 为 `compose.p09-acceptance.yaml`，容器必须为 `technologyagent-p09-acceptance-mongodb`，使用专用命名卷 `technologyagent-p09-acceptance-mongo`；不要执行旧卷迁移或 `down -v`。

```powershell
docker compose -f compose.p09-acceptance.yaml -p technologyagent-p09-acceptance up -d mongodb
if ($LASTEXITCODE -ne 0) { throw 'isolated Mongo startup failed' }
docker exec technologyagent-p09-acceptance-mongodb mongosh --port 27028 --quiet --eval 'JSON.stringify(db.hello())'
if ($LASTEXITCODE -ne 0) { throw 'Mongo hello failed' }
```

只在返回 `setName=ta-rs` 且 `isWritablePrimary=true` 后写测试。若刚启动尚在选主，短时重查并报告；若实际为 standalone，先核对是不是连错容器/端口，不重置用户卷。

- [ ] 对库存副本及 metadata 复算 SHA256，并与私有基线比较；检查 Git 未跟踪它们。记录当前进程来自哪个 checkout/数据库/端口，不能以工作区文件已改推断运行服务已更新。
- [ ] 更新交接为“L00 通过、下一张 L01”，提交文档路径并推送。源码仍留待 L01 定向关闭。

**通过条件：**源码、私有数据、无关文件均保留；能解释当前服务；专用副本集可用；原环境可恢复。环境不通过就先修环境，不启动全门禁。

## 5. L01：收尾固定业务时钟，提交当前已有实现

**输入：**现有 `Clock/SystemClock/FixedClock`、fixture manifest 的 `fixed_now`；本地已有未提交实现。

**输出接口：**`Settings.acceptance_business_now: AwareDatetime | None`，环境键 `P09_ACCEPTANCE_BUSINESS_NOW`；正常默认空。`DraftService`、`MutationService`、`BusinessMutationService` 保持原构造参数兼容，新增可选关键字 `business_clock`。不增加全局系统时间替换。

### 5.1 先审查，不重新机械覆盖

- [ ] 读取 `tests/unit/test_acceptance_business_clock.py` 与 `tests/integration/test_fixture_business_transactions.py`。旧 RED 已记录在 `.runtime/clock-red.log`（11 failed）及 `.runtime/clock-entry-red.log`（MCP/fake 两入口失败）；有文件才能引用，缺失则写缺失，不补造旧日志。
- [ ] 审查开关门禁：仅 `APP_MODE=local`、非空合法 `technologyagent_test_*`、专用 27028 URI、四种来源均 `local_seed`、空 snapshot 路径允许启用；naive datetime、daily/prod/remote/snapshot、错误 URI 一律拒绝加载。业务日期来自 manifest，不硬写进业务回答。
- [ ] 审查双时钟流向：

| 使用处 | 时钟 |
|---|---|
| Catalog 报价有效期、补货推荐 | business clock |
| 创建/编辑/批准/改单时的报价有效期 | business clock |
| fake Agent 的实际 `LocalToolRegistry` | 复用 bootstrap 已配置 Catalog，不重建 SystemClock Catalog |
| 独立 MCP `McpRuntime` | 同样构建 business clock 并传递所有判价服务 |
| session/token TTL、run deadline/cancel、模型预算、operation lease | SystemClock |
| created_at/updated_at、事件及流水记录时间 | SystemClock |

- [ ] 检查 readiness 只报告固定/系统业务时钟及非敏感时间，不做付费模型探测。检查 helper 保存/恢复新变量、browser/live 从 manifest 取值、offline 空值；重启子进程必须继承。正常 `.env.example` 仅空示例。

### 5.2 必须锁住的测试

- [ ] 在业务时间为 fixture 日期、操作时间为 2035 年的测试里，有效报价仍能完成 `55套/66000分 → 编辑60套/72000分 → 批准及重放 → 改单61套/73200分`。
- [ ] 上述事务的创建时间、session 到期和 lease 仍在 2035 年；不是 2026 年。创建及改单共两个成功 operation；创建审批重放只新增一张订单；最后 inbound=71、on_hand=20。
- [ ] 正常未启用开关、操作时间 2035 时，真实已过期报价仍拒绝推荐/批准，不能用验收开关绕过生产判价。
- [ ] API、实际 MCP、fake 工具入口对于同一 fixture 返回一致；两份不同进程环境分别验证，不能只测一个辅助函数。
- [ ] helper 的还原测试覆盖变量原本不存在/原本存在，旧不完整快照拒绝；浏览器配置拒绝错误日期和端口错配。

```powershell
. .\scripts\p09_acceptance_env.ps1 -Mode offline -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L01-$unitBatch" `
  tests/unit/test_acceptance_business_clock.py tests/unit/test_p09_acceptance_environment.py `
  tests/integration/test_fixture_business_transactions.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L01 directed tests failed' }
npm --prefix frontend run test -- --run src/lib/p09-runtime-config.test.ts
if ($LASTEXITCODE -ne 0) { throw 'L01 frontend tests failed' }
npm --prefix frontend run typecheck:e2e
if ($LASTEXITCODE -ne 0) { throw 'L01 E2E types failed' }
```

历史定向结果为 backend unit 421、入口组合 33、事务组合 20、frontend 配置 7 通过。它们是上一轮实际记录，不是要求人为拼出相同测试数量；接手执行须填写自己的命令、数量、退出码。

- [ ] 新增 `evidence/P09-L01.md`，更新相应中文模块 README 与交接。显式暂存本卡上述源码、两份新测试、README 和证据，按第 14 节推送。没有完成本卡提交前，不把它当作干净检出已有功能。

**通过条件：**四入口及业务事务共享固定判价时间，操作时间正常；配置隔离有效；源码已推送。不能据此关闭整个 P09。

## 6. L02：修复正文的字段、表格和实体范围提取

**修改：**`backend/app/agent/fact_checks.py` 的 `_field_from_text`、`_context_for_number`、必要的表格解析辅助逻辑；`backend/app/agent/graph.py` 的 `SYSTEM_PROMPT`。保留 `BusinessClaim`、`FactIndex`、`extract_business_claims`、`validate_answer` 对外签名及硬核验语义。

**新增测试：**`tests/unit/test_fact_claim_context.py`。已有回归：`test_fact_checks.py`、`test_verified_answers.py`、`test_deterministic_review.py`。

### 6.1 先加入这些最小反例

使用 `tests/unit/test_fact_checks.py::_quote_evidence` 的构造方式，建立 P001/W01 shortage=55、unit=套、对应候选 quantity=55；P004/W01 shortage=10、unit=条；P001/S01 lead_days=5；P002/W02/S02 unit_price_cents=1100；请求 max_lead_days=7 的可信事实。quantity 和 shortage 是两个独立字段，不能互相替代。不要给每句话分别造“正好匹配”的假事实。

| 计划新增测试名 | 正文 / 断言 |
|---|---|
| `test_warning_label_does_not_change_shortage_field` | `预警：P001/W01缺口55套。` → shortage、55、套、P001/W01；通过 |
| `test_table_column_beats_warning_in_other_cell` | 表头 `零件\|仓库\|预警\|缺口`，行 `P001\|W01\|有预警\|55套` → 55 是 shortage，不是 warning_count |
| `test_purchase_quantity_is_not_delivery_limit` | `P001/W01要求采购数量55套。` → 已有采购数量字段对应业务事实，不是 max_lead_days |
| `test_deadline_and_quote_lead_are_separate_lines` | `P001要求7天内到货\nP001/S01交期5天。` → 7 为请求上限、5 为报价交期 |
| `test_adjacent_part_lines_keep_separate_scope` | `P001/W01缺口55套\nP004/W01缺口10条。` → 各自 scope，均通过 |
| `test_explicit_entity_heading_can_scope_next_line` | `P002/W02/S02：\n单价11元` → 保留已支持的标题继承 |
| `test_wrong_table_cell_value_and_unit_still_fail` | 55 改 56、套改件、P001改P004，各自失败 |
| `test_ambiguous_entity_scope_does_not_guess` | 无法唯一定位物料/仓库/供应商时仍拒绝，不选第一条事实 |

- [ ] 先运行新文件，确认旧实现出现目标误判。特别记录：旧代码把任意“预警”强制解析为 warning_count、把任意“要求”强制解析为 max_lead_days；scope 会跨换行合并。

### 6.2 固定实现规则

- [ ] 将“字段上下文”和“实体继承上下文”分开。数值字段只从当前单元格或当前行局部子句识别；不能因为允许标题继承就把上一行的业务字段也继承。
- [ ] 表格先定位当前数值所在列，使用该列的明确字段表头；从本行标识列取得实体 scope。不得把其他单元格的“预警”压过“缺口”表头。跨越新表、空行或非表格正文时清除旧表头。
- [ ] 普通文本字段上下文不跨换行或句号、分号。逗号/顿号仅在现有受控继承规则内使用，不能把后续另一物料并入前一主张。
- [ ] `warning_count` 仅用于明确的预警数量表达，例如“预警共2条”；“预警：缺口55套”中的 55 仍是 shortage。“要求”单独出现不代表交期约束；只有与时间单位和上限含义绑定时才识别 max_lead_days。
- [ ] 实体标题继承只允许紧邻的、无业务数值且实体明确的标题，例如 `P002/W02/S02：`。下一行显式给出新物料/仓库时替换对应 scope；遇空行、新标题或强句界清除，不收集整段所有 ID。
- [ ] 同一行 `P001/W01缺口55套，P004/W01缺口10条` 也必须各自绑定。一个字段短语有两个可竞争实体时保持歧义失败，不能任意绑定最近事实。
- [ ] 若发现 Markdown 列表序号被误当业务数值，用行首列表语法定位排除序号；不能忽略没有单位的真实业务数字。
- [ ] 检查请求上限事实从 request_constraints 到确定性评审、最终核验是否使用同一可信上下文。若缺失，先加具体失败测试再修接线；不得把用户的“7天”改成供应商的实际“7天”。
- [ ] 修改 SYSTEM_PROMPT 中写死的 `缺口X件/在手X件`：要求使用该物料来源中的业务单位；未知单位明确未知，不能统一改成“件”。fixture 当前真实单位为 P001套、P002个、P003个、P004条、P005条、P006对。
- [ ] 保留 `render_verified_core_facts` 的辅助上下文用途，不替换非空 `final_answer`，不修改持久用户请求；每轮消息只创建本地副本，模型修订结果继续参与下一轮核验。

### 6.3 回归与通过条件

```powershell
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L02-$unitBatch" `
  tests/unit/test_fact_claim_context.py tests/unit/test_fact_checks.py `
  tests/unit/test_verified_answers.py tests/unit/test_deterministic_review.py `
  tests/integration/test_harness.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L02 tests failed' }
```

- [ ] 增加并保留错误字段、单位互换、scope 互换、旧快照被新快照取代、缺来源、NaN/Infinity/bool 数值、歧义的拒绝测试。
- [ ] 千分位和精确货币仍正确：`66000分`、`66,000分`、`660.00元` 等价；`660元` 只有在确实对应 66000 分时通过。不得改用 substring 判金额。
- [ ] 核对确定性检查失败时语义评审不调用；最多两次修订；最终返回、持久消息、终态 summary 一致；修订补充的来源支持内容没有丢失。
- [ ] 写 `evidence/P09-L02.md`，更新 Agent 模块 README，显式提交本卡路径并推送。

**通过条件：**正确表述不被上述字段/范围错误拒绝，错误金额/单位/来源/范围仍全部拦截。只改提示词、扩大容错或把硬核验改为警告不算修复。

## 7. L03：收货断言按语义子句判断，订单提交不重放

**修改：**`backend/app/services/order_workflows.py::_order_answer_fact_check`，必要时在同文件添加私有 `_has_unverified_receipt_claim(answer: str) -> bool`。生产订单数量/金额/单位/历史报价事实仍来自现有持久 verification_facts，不从当前 Catalog 补历史值。

**测试：**扩展 `tests/unit/test_order_review_bounds.py` 与 `tests/integration/test_order_review_loop.py`。

### 7.1 先复现两个方向的错误

为同一张 status=created、尚无收货事实的订单，先准备含单号、每项数量及单位、总额、已保存交期要求和报价交期的完整正文。下列句子加在完整正文后测试，避免因为缺数量/金额导致错误归因。

| 新测试 | 附加文本 | 预期 |
|---|---|---|
| `test_negative_receipt_implication_is_allowed` | `交期不代表已经到货。` | 通过 |
| 同上参数化 | `交期不表示已经到货。`、`报价交期不意味着已经收货。` | 通过；当前“不表示”会被误拒 |
| `test_asserted_receipt_without_saved_receipt_fails` | `已经到货。`、`订单已完成收货。` | 失败 |
| `test_negation_does_not_cross_sentence_or_turn` | `尚未收货。已到货。` | 失败；当前错误放行 |
| 同上参数化 | `尚未收货，但已到货。`、`未确认。已入库。` | 失败；当前错误放行 |
| `test_delivery_promise_is_not_actual_receipt` | `用户要求7天内到货；批准时报价交期5天；尚未实际收货。` | 通过，仍有必要交期覆盖 |
| `test_receipt_scope_is_per_order` | 两张订单，仅一张有收货事实，分别断言已到货 | 未收货那张不能被另一张的事实授权 |

- [ ] 新测试先在旧代码运行并记录实际失败。当前根因是只检查命中前 8 字符中是否含“未/没有”等，不是所有订单提交失败的统一根因。

### 7.2 实现规则

- [ ] 分割强句界（句号、分号、换行）和转折界（但、但是、然而、不过）。收货断言的否定必须在同一命题内直接修饰该断言。
- [ ] “不表示/不意味着/不代表已经到货”是对推论的否定；“尚未收货，但已到货”的后半句是肯定；前一句“未确认”不否定后一句“已入库”。不能以整段出现过否定就豁免。
- [ ] 一个子句包含多个收货断言时逐个判断。任一无依据肯定断言存在则失败；如果无法确定否定范围，保持拒绝并给明确原因，不扩大肯定许可。
- [ ] 多订单说明先用单号/实体明确归属；缺归属的肯定断言不能借任意一张 received/completed 订单通过。没有历史收货依据时不从“已下单”“已发货”或报价交期推导收货。
- [ ] 保留必要说明覆盖：只写单号仍不通过；必须覆盖每项数量和已知单位、每单总额、已保存的用户交期上限及批准时报价交期。历史单位/交期未保存则保持未知，不重新查当前值补造。
- [ ] fake 模式继续从持久订单事实生成说明；live 修订只改正文，不调用工具、不重新批准、不重新提交。不把固定订单事实模板冒充 live 模型输出。

### 7.3 集成事实与提交

- [ ] 集成用例包括：第一次缺说明、修订成功；两次修订耗尽；模型连接失败。每种分支均只有一张新增订单、一个成功 `order_create` operation，审批已消费，inbound 正确、on_hand 不因下单改变。
- [ ] 失败终态明确为“订单已提交，说明评审未通过”，并保留单号；不能诱导用户再下单。重放同一决定返回同订单。

```powershell
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L03-$unitBatch" `
  tests/unit/test_order_review_bounds.py tests/integration/test_order_review_loop.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L03 tests failed' }
```

- [ ] 写 `evidence/P09-L03.md`、更新服务 README 和交接，显式提交推送。

**通过条件：**否定解释能通过；跨句/转折的无依据肯定收货被拦截；说明失败不造成重复业务写入。

## 8. L04：修复独立 live oracle 的否定、将来动作与实体绑定

**修改：**`scripts/live_acceptance.py::_invalid_quote_conclusion_issues`。不导入生产 `fact_checks`、收货判定器或语义模型作为独立判分的替代。

**测试：**`tests/unit/test_live_acceptance.py`、`test_final_acceptance_oracle.py`；可新增 `tests/unit/test_live_oracle_quote_scope.py` 集中存放本卡用例。

### 8.1 可信输入与必须新增的用例

从真实成功 tool event 的请求参数和返回记录构造：P003/S03 唯一报价因供应商停用且过期失效；另有 P002/S03 有效报价的独立测试场景。后者是合成 oracle 夹具，不修改实际 fixture 供应商状态来迎合结论。

| 文本 | 预期 |
|---|---|
| `P003没有有效报价；S03单价7元但停用且过期，不可用于采购建议。` | 无推荐违规 |
| `P003没有有效报价。建议先获取P003有效报价后再比价。` | 无推荐违规，不把未来补资料当当前有效报价 |
| `P003没有有效报价。P002推荐S03。` | P002 推荐单独对 P002/S03 核验，不连坐 P003 |
| `P003/S03报价已失效，但仍建议采购。` | 违规 |
| `P003无有效报价。仍推荐S03作为P003的供应商。` | 违规 |
| `P003暂无有效报价。推荐先向供应商询价。` | 不是当前有效采购推荐 |
| `P003暂无有效报价。S03可用于采购。` | 违规，省略物料时继承紧邻明确的 P003 |
| `P003暂无有效报价。P002推荐S03。P003也可按S03报价下单。` | 最后一项违规 |

- [ ] 至少前 3 个正确句在旧 oracle 中形成真实 RED；明确错误推荐原来已拒绝的结果也记录，不能伪称所有用例旧版都失败。
- [ ] 加入本批 P003 的真实完整回答作为 regression fixture，保持原字句，预期本项 oracle 通过。保留原失败批次作为修复前证据，不修改其 JSON。

### 8.2 实现规则

- [ ] 按子句提取“当前推荐/报价有效”的肯定断言。区分否定、条件、未来补取资料与当前建议，不以出现“建议/有效报价/采购”任一关键词就认定肯定。
- [ ] 给每条肯定断言绑定 `(part_id, supplier_id)`。同子句明确 ID 优先；省略时只继承最近且无歧义的实体上下文；出现新物料就切换，不能整段累积。
- [ ] 只用相应物料/供应商的成功工具返回判断有效性；无证据或歧义时给出独立问题，不能猜报价为有效。
- [ ] 断言出现转折时重新判断后半句；“无有效报价，但推荐购买”仍拒绝。“不可用于采购建议”不能被拆成肯定推荐。
- [ ] 保留 `validate_live_run` 对终态、真实模型/工具轨迹、只读无写入、分页完整性、来源和 DB 对照的其他约束。

```powershell
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L04-$unitBatch" `
  tests/unit/test_live_oracle_quote_scope.py tests/unit/test_live_acceptance.py `
  tests/unit/test_final_acceptance_oracle.py tests/integration/test_p09_live_gate.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L04 tests failed' }
```

- [ ] 写 `evidence/P09-L04.md`，显式提交推送。不要在此卡为证明修复单独加跑随机 live；先完成 L05/L06，再按 L07 固定排程运行。

**通过条件：**正确的否定/补资料/其他物料推荐不误判；真正失效报价推荐仍失败；oracle 与生产判断器保持独立。

## 9. L05：持久保存每轮真实送审输入，使失败可以定位

**为什么必需：**本批多个只读和订单 run 只保留错误检查，没有最终失败候选正文；不能从 `ORDER_FACTS_MATCH` 猜测模型究竟写了什么。readonly 图没有可供追溯正文的持久 checkpoint，必须在既有授权事件链中保存实际送审输入。

当前 `ReviewPayload` 使用 `extra="forbid"`。直接给 `sink.emit("review", ...)` 加字段会触发校验错误，必须先改契约，再改发布者。

### 9.1 契约与接口：先定义，再接入

- [ ] 在 `docs/specs/CONTRACTS.md` 记录：现有 v1 `review` payload 新增可选 `review_input`，旧事件不含该字段仍合法；候选正文不是已通过的 assistant message。Envelope 版本不变，不能以此改旧节点名、namespace 或 checkpoint 结构。
- [ ] 在 `backend/app/contracts/events.py` 新增严格 DTO（以下是本计划指定的新接口）：

```text
ReviewFactSnapshot(_Strict)
  key: dict[str, str | None]       # 仅 FactKey 的 8 个已定义字段；逐项白名单生成
  value: str | bool               # 精确数值用十进制字符串，不丢失分/元精度
  unit: str
  call_id: str
  as_of: str | None = None

ReviewInputSnapshot(_Strict)
  input_version: Literal[1] = 1
  candidate_answer: str           # 本轮实际送给核验的文本，允许空以诊断无输出
  original_request: str           # 原始用户请求，不是追加修订提示
  request_constraints: dict[str, Any] = {}
  facts: list[ReviewFactSnapshot] = []
  source_refs: list[SourceRef] = []

ReviewPayload 新增：
  review_input: ReviewInputSnapshot | None = None
```

这里 `{}` / `[]` 表示 DTO 的 `Field(default_factory=...)`，不要使用共享可变默认值。`key` 必须用 validator 拒绝白名单外键，精确的八个 key 为 `entity_type/entity_id/field/part_id/warehouse_id/supplier_id/order_id/metric`；测试断言完整键集合。不得接收模型提供的任意可信事实。`request_constraints` 来自已保存结构化约束的 JSON 副本，不拷贝请求头、模型 messages 或配置。

- [ ] 新增 `backend/app/agent/review_snapshot.py`，公开一个内部函数：

```python
def make_review_input_snapshot(
    *, candidate_answer: str, original_request: str,
    request_constraints: dict[str, Any], fact_index: FactIndex,
    source_refs: list[SourceRef],
) -> ReviewInputSnapshot:
    ...
```

它只做类型化、白名单和精确值序列化，不判断是否通过、不查新数据、不调用模型或工具。snapshot 中不得放 `BusinessFact.raw`。对非有限数值拒绝转换；bool 保持 bool，不能转成 0/1。

### 9.2 接入两个真实发布位置

- [ ] 主图/harness：在 `publish_review` 的每轮 review 事件中，保存这轮 `state.final_answer`、原始用户请求、原约束及**本轮核验所用** fact index。若确定性检查就失败，仍保存；不能只在 semantic 成功后保存。
- [ ] 订单流：在 `OrderWorkflowService` 正文评审循环的每次 `append_event("review")` 处保存当轮 candidate。订单 facts 使用当前评审已经读取的持久订单、成功 operation、已消费审批和 verification_facts，复用现有建事实入口；不重新查询当前报价替代历史快照。
- [ ] 有两次修订则应有 revision_count=0/1/2 的 3 轮真实输入，各自对应自己的 checks；不能统一引用最后一个 candidate。`review_input` 不进入 `final_answer` 竞争，也不发布 token/成功正文。
- [ ] 将无副作用的事实构建函数提取成共享内部入口时，仅机械提取，先保持现有事实集合一致；不要复制另一套订单核验逻辑。新增公共内部函数需要模块 README 写清调用者。
- [ ] 使用已有 run owner 授权读取 review 输入；保留他人 run/trace 404。不得为了诊断添加无鉴权调试路由或允许客户端传 owner。
- [ ] 候选文本遵守现有模型输出和事件资源预算，完整保留核验实际输入；不能静默截断后声称是完整正文。若现有预算无法容纳，先用边界测试明确错误终态，再按既有存储机制设计有 owner 的内容引用，不随意加无限字段。

### 9.3 生成契约与测试

- [ ] `scripts/export_contracts.py` 注册新 DTO，使 `$ref` 和 TypeScript 名称可导出。由脚本生成，不手写下面两个产物：

```text
backend/app/contracts/events-schema.v1.json
frontend/src/lib/events.ts
```

```powershell
uv run python -m scripts.export_contracts
if ($LASTEXITCODE -ne 0) { throw 'contract export failed' }
```

脚本也管理 domain 产物；若无 domain 契约变更，核对其 diff 应为空。生成器若支持 check 模式，按实际帮助使用，不编造 CLI 开关。

- [ ] 扩展 `tests/unit/test_event_contracts.py`：旧 review JSON 不含新字段可解析；新字段结构/版本非法、未知 extra、未知 fact key 被拒绝；序列化精度正确。
- [ ] 新增 `tests/unit/test_review_input_snapshot.py`：FactKey 八键白名单、bool/Decimal/单位/来源、未知不补 0、拒绝非有限数值、无 raw/secret/messages。
- [ ] 扩展 `tests/integration/test_harness.py`、`test_order_review_loop.py`：第一候选失败、第二候选修订后的文本分别保存且可回放；终态 failed 时仍可取真实送审输入；原用户请求各轮不变；跨 owner 无法读取。
- [ ] 核对已有模型观测链：每次真实尝试只计数一次、成功 call_id 关联工具、usage 缺失仍未知；不增加内部隐形重试。若 trace redactor 把数值 `prompt_tokens/completion_tokens` 因含 token 字符串而遮掉，先新增确切用例，再仅对白名单数值 usage 放行；API key/session token 仍脱敏。不要为修诊断顺带重写模型层。

```powershell
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L05-$unitBatch" `
  tests/unit/test_review_input_snapshot.py tests/unit/test_event_contracts.py `
  tests/unit/test_model_observation.py tests/integration/test_harness.py `
  tests/integration/test_order_review_loop.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L05 tests failed' }
npm --prefix frontend run typecheck
if ($LASTEXITCODE -ne 0) { throw 'frontend contract types failed' }
npm --prefix frontend run typecheck:e2e
if ($LASTEXITCODE -ne 0) { throw 'E2E contract types failed' }
```

- [ ] 检查 live 子 pytest 的失败输出保存链。本批 F04 子记录输出较短，但 own trace 已证明审批后正文核验失败；尚不能断言是编码或捕获程序错误。若不能保留完整 traceback，先用固定失败子进程证明丢失点，再修 stdout/stderr 保存，不改变测试成败。
- [ ] 写 `evidence/P09-L05.md`，提交 DTO、生成器及产物、发布入口、新模块 README、测试与交接。仅当测试覆盖上述兼容和授权边界才推送。

**通过条件：**今后每个失败都能看见实际核验文本、对应事实与检查；失败正文不冒充成功输出；旧事件/旧 v1 恢复可继续使用；无额外授权入口或密钥泄露。

## 10. L06：联合定向回归，确认原任务要求没有倒退

本卡主要是验证和归档，不为获得“更多改动”重写已关闭功能。若失败，则退回所属 L 卡修复，新增回归并提交；不能带着失败开始最终 live。

- [ ] 在同一提交上联合运行 L01–L05 的全部新增测试和直接受影响旧测试，检查“单卡通过、组合失败”的配置污染。
- [ ] 运行现有实际 MCP 矩阵：`tests/integration/test_p08_tool_matrix_r7.py`。继续区分 **15 读 + 8 写 = 23 工具**；非法参数必须实际发到 MCP，不以本地 schema 检查替代。
- [ ] 对照 `evidence/P09-R7.md` / C04，逐工具核对正常输入、非法输入、实际结果和 DB 前后事实。写工具必须有未批准拒绝、批准成功、同 key 重放、错误 owner/旧版本拒绝；已有完整证据可引用，缺行才补，不笼统称“所有集合完全不变”。
- [ ] 复核原任务 1 的停用物料：preview 不可执行、quantity/total=0、quote=None、候选空、missing_fields含 part_inactive，但真实缺口仍保留；草稿继续 409。启用/停用混合批次各自判断。
- [ ] 复核原任务 2/3/4：修订不被固定答案覆盖；订单历史事实不被当前 Catalog 替换；四个模型入口共用观测预算。只允许首 delta 前指定传输错误最多额外一次；协议错误/401/429/5xx/截断/取消不因此重试，usage 缺失不补 0。
- [ ] 复核原任务 5：实际 MCP 两页 seed 快照能合并；内容漂移/缺页/重复实体拒绝完整报告；全仓不被默认 W01 限制；真实中文仓位和原物料 ID 正确匹配；snapshot 拒绝报价时 metadata 仍来自 snapshot。
- [ ] 复核原任务 6：v1 独立状态/节点/builder 由两个真实执行位置选择；旧 fixture 不改；v2 变化不会影响 v1；namespace/重复恢复单订单边界保留。
- [ ] 复核原任务 7：本地 HTTP 模拟器的真实分页映射、100页/10000条上限、缺必需字段拒绝；远程 operations 持久认领/dispatch 后只 lookup；404 仍未知；并发及重建客户端不再 POST。真实 ERP 写仍关闭，不调用真实 ERP。

下面是编写时已存在的直接回归入口，先核对文件仍存在，再执行。新证据列出每条命令及覆盖要求；测试名字相近不代表覆盖成立，必须读断言。若发现原要求实际没有实现，新增“L06-缺口编号”任务：具体文件、RED、修复、GREEN、推送后才继续，不能仅文档勾选。

```powershell
$unitBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
uv run python -m pytest --basetemp ".runtime/pytest-L06-unit-$unitBatch" `
  tests/unit/test_replenishment_service.py tests/unit/test_model_observation.py `
  tests/unit/test_graph_version_isolation.py tests/unit/test_mcp_inventory_snapshot_fail_closed.py `
  tests/unit/test_required_report.py tests/unit/test_provider_queries.py `
  tests/unit/test_p08_erp_adapter.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L06 unit boundaries failed' }
uv run python -m pytest --basetemp ".runtime/pytest-L06-integration-$unitBatch" `
  tests/integration/test_p08_tool_matrix_r7.py tests/integration/test_checkpoint_resume.py `
  tests/integration/test_inventory_snapshot_routes.py tests/integration/test_provider_queries_r5.py `
  tests/integration/test_remote_operations_r6.py -q -rs
if ($LASTEXITCODE -ne 0) { throw 'L06 integration boundaries failed' }
```

本命令在 L01 的 offline/27028/seed 环境内执行；snapshot routes 的快照由测试自己的合成临时文件提供，不能切到用户库存文件。如果引用文件因后续提交改名，用 `rg` 找到实际替代并记录，不直接删掉该覆盖要求。

- [ ] 确认前端 unit、应用 typecheck、E2E typecheck 通过；不运行时长大的全门禁来替代缺失定向证据。
- [ ] 写 `evidence/P09-L06.md`，逐行对应原任务 1–7 与 23 工具矩阵；更新 HANDOFF 为“修复已推送，等待新候选全门禁”。

**通过条件：**所有已确认产品缺口关闭，旧安全/数据边界没有回退；没有仅在工作区的交付必需源码。此时仍不能创建 `phase-p09`。

## 11. L07：冻结新源码，依次完成 offline、CI、browser、固定 live

**前提：**L01–L06 都通过且相关源码已推送；Docker/专用 Mongo 可用；没有未提交的交付必需代码。此前失败的 8538f4c candidate 不再作为最终候选。

### 11.1 冻结及运行准备

- [ ] 逐个检查 `git status --short`，区分无关未跟踪内容与交付源码。记录新候选完整 SHA；核对 `origin/main`。任何测试、配置、脚本、锁文件、生成契约、产品源码改变都需要新候选，不允许边跑边改。
- [ ] 新建 `.runtime/private/P09-L07-<batch>.json`，记录 `source_sha`、HEAD、开始时间、4 个数据库/来源参数、3 端口、时钟、各报告路径和每步退出码。字段初始为 `not_run`，不得初始化为 passed。不记录模型 key。
- [ ] 同一个 PowerShell 7 会话中执行下列命令。若中断/换进程，先从私有记录重新加载批次与环境；不要默默产生新批次覆盖旧记录。

```powershell
Set-Location -LiteralPath 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$gateBatch = Get-Date -Format 'yyyyMMdd-HHmmss'
$candidateSha = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'cannot resolve candidate' }
New-Item -ItemType Directory -Path '.runtime/reports' -Force | Out-Null

# 停应用，不停止或重建任何 Mongo 数据卷。
.\stop.ps1
if ($LASTEXITCODE -ne 0) { throw 'stop failed; inspect process registry' }
. .\scripts\p09_acceptance_env.ps1 -Mode offline -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:P06_REQUIRED = '1'
$env:UV_CACHE_DIR = Join-Path $PWD '.runtime/uv-cache'
$env:STORAGE_ROOT = Join-Path $PWD ".runtime/L07-$gateBatch-offline-storage"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
docker build -t technologyagent-sandbox:0.1.0 -f backend/app/sandbox/Dockerfile backend/app/sandbox
if ($LASTEXITCODE -ne 0) { throw 'sandbox build failed' }
```

`P06_REQUIRED=1` 必须保留，防止 Docker 不可用时 sandbox 测试被跳过却称通过。缓存可用，但不能复制 `.venv` / node_modules 冒充干净安装。

### 11.2 offline

```powershell
uv run python -m scripts.run_acceptance --scope local --mode offline `
  --report ".runtime/reports/P09-$gateBatch-offline.json"
$offlineExit = $LASTEXITCODE
if ($offlineExit -ne 0) { throw "offline failed: $offlineExit" }
```

- [ ] 打开报告，检查 `ok=true`、`not_run=false`；逐项核对 `checks` 的 status、exit_code、required、输出和 skip 原因。现有 manifest 为 8 个检查，含 E2E typecheck；如数量变化，给出实际源码 diff 依据，不能删检查凑通过。
- [ ] 检查 unit/integration 的实际通过/跳过数量，Docker 相关必需用例不能 skip。长时 pytest 缓冲输出可能数分钟不动，通过进程/日志确认状态，不重复并发启动整套验收。
- [ ] 保存实际命令/退出码/完整日志，报告绑定 `$candidateSha`。运行后核对源码 diff 没被构建或生成器意外改变。

### 11.3 核对精确 SHA 的云 CI

- [ ] 查询新候选的 push run，而不是聊天里旧 run 的当前状态。要求 `head_sha == $candidateSha`，`p09-offline` 及既有 `p06-offline` 均 success。
- [ ] 保存 run ID、job ID、链接、report artifact 的 8 检查结果和无必要跳过证明。CI 只用 fake/seed/隔离库，无用户数据或 live 凭证。
- [ ] 失败先定位并按所属卡修复；源码变更产生新候选。`p06-offline success` 不能代替 `p09-offline success`，job 仍 running 不能视为通过。

可用 GitHub connector 查询；CLI/API 为后备。按精确 SHA 过滤 push run；某些工具只列 PR runs，空结果不代表没有 push CI。

### 11.4 browser

```powershell
.\stop.ps1
if ($LASTEXITCODE -ne 0) { throw 'stop before browser failed' }
. .\scripts\p09_acceptance_env.ps1 -Mode browser -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:P06_REQUIRED = '1'
$env:STORAGE_ROOT = Join-Path $PWD ".runtime/L07-$gateBatch-browser-storage"
$env:P09_EVIDENCE_BATCH = "L07-$gateBatch"
.\start.ps1
if ($LASTEXITCODE -ne 0) { throw 'browser services failed' }
uv run python -m scripts.run_acceptance --scope local --mode browser `
  --report ".runtime/reports/P09-$gateBatch-browser.json"
$browserExit = $LASTEXITCODE
if ($browserExit -ne 0) { throw "browser failed: $browserExit" }
```

- [ ] 启动后、重置前检查服务/验收进程同为 `technologyagent_test_p09_browser`、27028、fake、四 local_seed、空 snapshot、业务时间=manifest。端口是 8131/3131/9131，baseURL 为 3131、LIVE_API_URL 为 8131。若检查不匹配，停止，不能 reset。
- [ ] Playwright `--workers=1`；现有 suite 已固定单 worker，检查实际执行命令，不假定并行安全。完整 browser 之外，桌面 1440×900 和手机 390×844 都必须完成下表；不能只有截图。

| 步骤 | 必须核对 |
|---|---|
| 库存与报告 | 真实查询、三种报告生成及实际下载；字节、哈希、内容、source_refs、artifact/run 对应 |
| 草稿与编辑 | 初始55套/66000分，编辑60套/72000分、版本递增；尚未新增订单 |
| 刷新与重启 | 同 run/draft/version 待审批状态仍在；端口、库、storage 不漂移 |
| 批准与重放 | 每场新增1单、1成功 order_create operation；重复批准同订单 |
| 库存 | inbound10→70，on_hand=20；不把下单记为已经入库 |

- [ ] 每张截图记录实际文件名/SHA256，绑定本轮 run/artifact；不能混用旧 `.runtime` 文件和新截图。已有三图/HTML 确认、R8 六份 MD/CSV/JSON 实开记录保留，不要求用户重复确认。若生成内容/格式改动导致旧打开证据不适用，才补对应新实开；解析成功不能冒充人工打开。

### 11.5 固定 live（只有前面全部通过才执行）

```powershell
.\stop.ps1
if ($LASTEXITCODE -ne 0) { throw 'stop before live failed' }
. .\scripts\p09_acceptance_env.ps1 -Mode live -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:P06_REQUIRED = '1'
$env:STORAGE_ROOT = Join-Path $PWD ".runtime/L07-$gateBatch-live-storage"
.\start.ps1
if ($LASTEXITCODE -ne 0) { throw 'live services failed' }
uv run python -m scripts.run_acceptance --scope local --mode live `
  --report ".runtime/reports/P09-$gateBatch-live.json"
$liveExit = $LASTEXITCODE
if ($liveExit -ne 0) { throw "live failed; preserve this batch: $liveExit" }
```

- [ ] ready 的 `configured` 仅表示配置存在，不是模型实测成功；真实调用证据来自本批 model_started/finished、tools、review、终态及独立 oracle。
- [ ] 排程沿用 `tests/live/test_final_scenarios.py`：1 个 F02-F03 外层 + F04/F08/F11/F12 各3 = **13 外层记录**；P03 内部 3问题×3 =9；F12 内部每轮3组、共9组。记录所有失败/成功、usage 未知情况与真实 DB 结果。
- [ ] 必须是 13/13，以及内部各必需断言通过。不能把“外层 pytest 执行过1个用例”当作13场通过；不能靠改 pytest 输出解析把 failed 变 passed。
- [ ] 如失败，先查看 L05 的本轮 review_input、hard/semantic 检查、真实工具数据、原请求约束和订单事实，确定是模型错误、生产误判、oracle误判或环境故障。没有足够证据先补诊断，不反复改提示词碰运气。
- [ ] 先验证订单是否已经提交。已提交的说明失败不重下单；保留旧批次及 operation 关联。在所属卡修复并定向验证后，形成新 SHA、重新全门禁、新批次，不能把不同批次成功样例拼成13/13。

### 11.6 本卡关闭

- [ ] 三份报告均 `ok=true/not_run=false`，每个 required check passed/exit0，live summary及内部记录无失败；CI 精确匹配源码；运行全程产品源码未变。
- [ ] 私有 session 标记为 `all_gates_passed_pending_clean_restore`，填写实际 SHA/时间/库/端口/业务时钟/报告，而不是沿用 `.runtime/private/p09-final-candidate.json` 的旧 8538f4c。
- [ ] 写 `evidence/P09-L07.md`，正文区分前次失败批次与本批结果；不要提交 `.runtime`。只读摘要可提交，未经脱敏的送审文本不默认公开。

**通过条件：**新候选的本地 offline、精确 SHA 云 CI、完整 browser、固定 live 都实际通过。仍需 L08/L09，不能在此创建 P09 标签。

## 12. L08：从已推送候选全新检出，完成真实完整备份恢复

**输入：**L07 已通过的候选 SHA，`frontend/playwright.clean.config.ts`、`tests/acceptance/clean-restore.spec.ts`、`scripts/p09_restore_facts.py`，27028 专用 Mongo。

**输出：**新安装、新源码目录、真实全库+storage backup/restore、恢复后批准/重放/下载/授权的完整证据。旧“新目录能启动”“单文件恢复67字节”仅历史证据，不能关闭本卡。

### 12.1 创建全新检出与安装

- [ ] 再读 L07 三份报告及 CI head_sha；任何一项不通过不能运行本卡。检查 `$candidateSha` 仍是已验收源码，必须先 push 后 clone。
- [ ] 停止原项目管理的服务；在新检出中运行其自身 start/stop，不按端口批量杀进程。下面命令继续在同一 PowerShell 会话执行：

```powershell
$originalRoot = 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
Set-Location -LiteralPath $originalRoot
.\stop.ps1
if ($LASTEXITCODE -ne 0) { throw 'original services did not stop' }
$cleanStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$cleanRoot = Join-Path $originalRoot ".runtime/p09-clean-$($candidateSha.Substring(0,7))-$cleanStamp"
if (Test-Path -LiteralPath $cleanRoot) { throw 'choose a new checkout directory' }
git clone https://github.com/newerwell/technologyagent.git $cleanRoot
if ($LASTEXITCODE -ne 0) { throw 'clean clone failed' }
Set-Location -LiteralPath $cleanRoot
git checkout --detach $candidateSha
if ($LASTEXITCODE -ne 0) { throw 'candidate checkout failed' }
if ((git rev-parse HEAD).Trim() -ne $candidateSha) { throw 'wrong clean source' }
foreach ($relative in @('.venv','frontend/node_modules','frontend/.next','.env','data/inventory_snapshot.json')) {
    if (Test-Path -LiteralPath (Join-Path $cleanRoot $relative)) { throw "unexpected copied content: $relative" }
}
uv sync --frozen --group dev
if ($LASTEXITCODE -ne 0) { throw 'clean Python installation failed' }
npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw 'clean frontend installation failed' }
```

不要复制外层 `.env` 或密钥。本流程 fake，无需真实模型。允许复用包下载缓存；不能复制原安装目录、构建或用户库存。

### 12.2 配置及真实执行

```powershell
. .\scripts\p09_acceptance_env.ps1 -Mode browser -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:P09_CLEAN_ACCEPTANCE = '1'
$env:MONGODB_DATABASE = 'technologyagent_test_p09_clean_' + $cleanStamp
$env:STORAGE_ROOT = Join-Path $cleanRoot '.runtime/clean-source-storage'
$env:P09_EVIDENCE_BATCH = 'L08-' + $cleanStamp
$env:P06_REQUIRED = '1'
.\start.ps1
if ($LASTEXITCODE -ne 0) { throw 'clean startup failed' }
npm --prefix frontend run typecheck:e2e
if ($LASTEXITCODE -ne 0) { throw 'clean E2E typecheck failed' }
npm --prefix frontend run test:e2e -- --config playwright.clean.config.ts --workers=1
$cleanExit = $LASTEXITCODE
if ($cleanExit -ne 0) { throw "full clean restore failed: $cleanExit" }
```

此配置当前只有 1 个完整用例，`retries=0`。`--list` 或 typecheck 成功不算执行。Chrome 通道实际可用才执行；缺浏览器先安装受支持浏览器，不把测试改成 skip。

现有 E2E 会在 source checkout 内：reset **新的 clean 测试库** → 生成并下载报告 → 编辑草稿 → stop → backup → restore 到新的 restored 库及 storage → startup restored → 批准/重放。不要另行提前 seed restored 库或在 restore 后 init/reset 以补齐数据。

### 12.3 逐条核对现有用例的事实断言

- [ ] 源库为 `technologyagent_test_p09_clean_<stamp>`；目标库为 `technologyagent_test_p09_restored_<同stamp>`，与源不同且从未使用；两处 storage 和 backup 目录不存在。不得重用失败尝试的目标路径。
- [ ] `backup.ps1` 与 `restore.ps1` 显式传：`-MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028 -MaintenanceConfirmed`。不靠默认值（默认为旧27027容器）。只有真正停写且进程注册为空才能使用 MaintenanceConfirmed。
- [ ] 备份含全部集合、checkpoint 原始 BSON、session、审批、草稿版本、operations、artifact 元数据与全部 ready 文件；manifest 每项文件 SHA256。路径穿越、reparse point、多余或缺失文件继续拒绝。
- [ ] restore 只映射 manifest 的原 test namespace 到新 test namespace；预览/白名单和空目标保护保留；不恢复原库名覆盖源库。
- [ ] 在启动目标服务前，以 `p09_restore_facts` 比较**每个集合全部文档的规范 BSON hash/count**、checkpoint 字节、artifact字节/owner/run/source_refs，要求 source==target。此时再读源库/文件仍相等。
- [ ] 待审批恢复核对同 owner、run、draft、version=2。真实 approval ID 从备份前按 owner/run/draft/version 唯一匹配，形如 `apr_*`；`int_*` interrupt ID **不是审批 ID**，不得拿它查询 approvals。
- [ ] 新目标恢复后页面仍为 60套/72000分待审批，批准及重放只新增一张订单、一个成功 order_create operation。审批 consumed、order.operation_id、operation.order_id、draft/version 形成同一唯一关联。
- [ ] 目标最终订单为 2 seed + 1 新单；成功 operation 为1；P001/W01 inbound=70、on_hand=20。源库业务仍为2单、0成功operation，不受目标批准影响。
- [ ] 恢复后重新下载原 artifact：实际字节 SHA256 与备份前一致、metadata/source_refs 一致；订单页和历史可访问。不能只测文件能解析。
- [ ] 对不同可信 owner 的同 artifact 请求返回404；测试身份注入仅在严格 guarded testDB 的受信任脚本，Cookie留浏览器，不加公共 owner 后门、不把 session token 传 CLI。
- [ ] `.runtime/reports/clean-restore/` 的实际 facts JSON、日志及 screenshots 记录 source/target/checkpoints/审批/订单/operation/文件哈希，批次和文件名对应；公开证据只摘必要合成事实。

若用例失败：保存源码 SHA、退出码、trace、事实和路径。环境故障排除后用新目标重跑；产品/验收代码缺陷必须回原 checkout 修复、提交、形成新候选，再完成受影响定向及完整门禁。不能只改 clean clone 取得通过就宣称远端相同。

- [ ] 从新检出生成 `evidence/P09-L08.md` 的脱敏摘要，回原项目显式加入；检查原项目交付不依赖未跟踪源码。保留完整私有恢复材料至最终复核结束。

**通过条件：**新检出锁安装和真实完整恢复闭环都完成，源数据不变，目标业务正确、下载和 owner 边界正确。到这里仍要恢复日常环境并核对交付。

## 13. L09：恢复用户环境，关闭矩阵，提交并核对标签

### 13.1 恢复原环境，不重置日常库

- [ ] 在 clean checkout 调用它自身的 `stop.ps1`。回原项目；确认服务管理注册为空，不能让目标 restored 服务继续占用测试端口。
- [ ] 读取 L00 私有原环境快照并恢复“存在性+原值”。现有 C00 JSON 的顶层为 `variables`，每项是 `{exists, value}`；helper 的会话快照用 `{present, value}`，两者不能混用。先核实结构再执行。

```powershell
Set-Location -LiteralPath 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
$originalEnv = Get-Content -LiteralPath '.runtime/private/p09-final-original-env.json' -Raw | ConvertFrom-Json
if (-not $originalEnv.variables) { throw 'missing original variable snapshot' }
foreach ($property in $originalEnv.variables.PSObject.Properties) {
    $saved = $property.Value
    if ($null -eq $saved.exists) { throw "invalid original entry: $($property.Name)" }
    $restoredValue = if ($saved.exists) { [string]$saved.value } else { $null }
    [Environment]::SetEnvironmentVariable($property.Name, $restoredValue, 'Process')
}
```

此代码不打印值；若后续 L00 另存了更新结构，使用其对应恢复逻辑，不把测试进程的环境当原环境。禁止整份 `.env` 回显。

- [ ] 新增测试开关 `P09_ACCEPTANCE_BUSINESS_NOW`、`P09_CLEAN_ACCEPTANCE` 若原本不存在则删除；`P09_EVIDENCE_BATCH`、编码/缓存等本轮变量按 L00 记录恢复。不能盲删原来已有的变量。
- [ ] helper 的旧 global snapshot可能来自测试模式；清除失效会话快照，不能在恢复完原值后又用它覆盖。核对最终有效配置来自 env+`.env` 的合并结果。
- [ ] 默认预期为 `technologyagent_dev`、原 live 模型配置、库存和物料 `local_snapshot`、路径 `data/inventory_snapshot.json`；supplier/order 及 URI/port/storage 恢复原值。原来3端口为空时应由项目默认8030/3030/9030，不沿用8131组。
- [ ] 先只读检查日常 Mongo 是否可用、是否为启动脚本支持的副本集。原27027曾是 standalone，**不能假定现在已经变成 ta-rs**。若不兼容，保留现有卷和数据库，写清非破坏性的迁移方案及备份目标；不得为恢复页面清空或原地重建旧数据。
- [ ] 实际启动原项目，确认进程来自原路径、正确端口/库/来源。若上述日常环境无法安全启动，明确留为 L09 未完成；测试全过也不能宣称已恢复。只有确需改变用户持久数据且未获授权的操作才提出具体审批，不反复问普通启停许可。

**仅当日常27027确认为 standalone 时，执行下面的条件补卡 L09-RS，而不是让最终交付永久停在“需要副本集”：**

1. 停应用和 MCP，保留原容器/卷；只读记录原 Mongo 版本、数据库名、集合清单/计数/规范 BSON hash、storage 文件清单及 hash。读取源库不能触发 seed/reset。
2. 先检查源实例已有 `technologyagent_dev` 和其他数据库。迁移仅涵盖明确选定的日常库及其引用文件；不能遗漏 checkpoint/session/approvals/operations，也不能顺手迁移其他项目数据库。
3. 实现独立的 `scripts/migrate_daily_mongo.ps1` 和对应 `docs/operations/DAILY-MONGO-MIGRATION.md`；不放宽现有仅接受 test 库的 backup/restore guard。脚本固定允许源库 `technologyagent_dev`，源只读，目标必须是全新空实例；dry-run 默认，不提供 drop/reset 源库选项。
4. 目标方案固定为新的 `compose.daily-rs.yaml`：单独项目/容器 `technologyagent-daily-rs-mongodb`、新命名卷 `technologyagent-daily-rs-mongo`、回环端口27029、ta-rs，镜像沿用已锁定的 Mongo 主版本。启动前核查端口和卷不存在/未使用；不得把旧 mongo-data 挂给新实例，不能复用测试27028实例作为日常库。
5. 为源库执行一次维护期 `mongodump`，保存到新的私有目录并记录archive SHA；一致性依赖源应用确已停写，standalone 不假装有 oplog 事务快照。恢复前核对归档只有选定库的namespace、完整清单和hash；目标集合数必须为0，再恢复到新实例的同名dev库。
6. 新实例启动 PRIMARY 后，先比较全部集合/hash、checkpoint bytes、artifact元数据及文件；比较前不启动应用。验证源数据/文件不变。失败保留目标供诊断，配置不切换，不删除源实例或卷。
7. 在合成临时源/目标数据库先测试脚本：非空目标、错误库名、错误端口/namespace、坏hash、漏文件、源仍运行写进程均应拒绝；正常迁移前后全量指纹一致。guard可接受专用合成测试库进行演练，但显式拒绝任意库输入，演练不能冒充真实dev迁移完成。
8. 准备具体迁移报告，列清原数据完全保留、目标/备份位置、仅本机 URI 将切到 `mongodb://127.0.0.1:27029/?replicaSet=ta-rs&directConnection=true`。若现有授权不足以切换日常持久配置，先完成上述可审查结果，再只就这一项切换询问用户。获准后仅更新本机配置，重启验证snapshot/API/MCP，不提交.env。回滚是停新应用、恢复旧配置及原实例，绝不把新库反向覆盖旧库。

此补卡是条件方案，编写时没有证明27027当前仍为standalone，也没有新建迁移脚本/容器。原实例已兼容时整卡不执行。执行后要单独报告“日常库迁移至新副本集”，不能称 URI 与迁移前完全相同。

### 13.2 用户快照验收

- [ ] 重新计算两个文件 SHA256，与 L00/C00 比较；原始文件未变且未入 Git。

```text
inventory_snapshot.json:
dd2e208d2144fabed9372f20d8df57dbf530a239a20811e0c308b2df3b093248
inventory_snapshot.meta.json:
fe6467f7d533cb50eed810188b7bcdb1fe28321f9a850c7db19a37d4b84f1ea5
```

这些是历史基线摘要；若用户随后更新了快照，以 L00 保存并解释过的新基线为准，不能强行恢复成旧文件。

- [ ] 实际页面和有 owner 会话的 API 查询，`GET /api/inventory?page=1&page_size=50` 及第2页；再通过**实际运行 MCP** 调用 inventory_page 的同两页。使用既有 MCP client/session/grant 方式，不增加无鉴权探针。每端72条、无重复、72物料、6仓位，副本身份/采集时间一致。
- [ ] 预留、在途、目标库存及完整报价缺失保持 null/未知；不能显示为0或给出可采购推荐。全部只表示已保存快照集合，不能宣称整个实时 ERP；采集时间和完整性未知信息保留。
- [ ] ready 模型为原 live 配置的 configured；不用为启动验证发额外付费请求。MCP与页面真实来源均 local_snapshot，而非残留 seed。
- [ ] 不执行 dev seed/reset，不给用户快照注入合成供应商报价，不把测试订单搬进日常库。

### 13.3 更新最终矩阵及证据

- [ ] `docs/specs/FINAL-ACCEPTANCE.md` 每个 F01–F14、F17–F18 分别写实际状态、对应候选 SHA、批次、证据。旧矩阵顶部和 F18 旧行不再作为当前通过依据；保留历史证据链接并追加“被完整恢复要求取代”的说明。
- [ ] F02/F03/F04/F08/F11/F12 同时引用本轮固定 live；F13写清15读+8写；F17实际双尺寸；F18引用L08完整恢复。F15/F16保留 `not_run`，禁止标真实ERP联调通过。
- [ ] 更新 `evidence/P09.md`、必要 P06 汇总、`docs/delivery/STATUS.md`、`HANDOFF.md`、实施入口；列出最后源码 SHA、全部结果和任何剩余项。未完成项不能改写成完成。
- [ ] 每个链接实际存在；每个截图有对应文件及SHA；报告中的订单/op/inventory事实与本轮数据一致。历史截图不冒充本批截图。

### 13.4 最后 Git/CI 与标签

- [ ] 对交付文件做 diff 检查并显式提交推送，参照第14节。核对远端 main；如果最后仅追加文档/合成证据，验证候选为最终 HEAD 祖先，二者 diff **只有文档/证据**。代码、契约、测试、配置、脚本或锁文件任何变动都要新候选，不能用“补证据”掩盖代码变动。
- [ ] 如果最终 main 的新 CI 尚未完成，等待并核对其结果；源码候选 CI 与最终文档提交 CI 分别列出。失败或仍 running 不能写最终交付通过。
- [ ] P06 自身所有要求已有实际证据且无开放项时，才为缺失的 `phase-p06` 创建 annotated tag，指向真正包含通过实现及相应证据的提交；不凭“P09里跑过部分sandbox”猜 P06完成。
- [ ] 本文全部完成、矩阵本地必需项及 fixed live通过、L08/L09通过后，才创建 `phase-p09`，指向最终交付提交。已有标签只核对，不移动或覆盖。

```powershell
# 只有上面的全部条件已核对才执行；$deliverySha 为实际最终交付提交。
$deliverySha = (git rev-parse HEAD).Trim()
git tag -a phase-p09 $deliverySha -m 'P09 local acceptance completed; real ERP F15/F16 not run'
if ($LASTEXITCODE -ne 0) { throw 'tag creation failed; inspect existing tags' }
git push origin refs/tags/phase-p09
if ($LASTEXITCODE -ne 0) { throw 'tag push failed; do not claim delivery' }
git ls-remote origin refs/heads/main refs/tags/phase-p09 'refs/tags/phase-p09^{}'
if ($LASTEXITCODE -ne 0) { throw 'remote verification failed' }
```

核对解引用 `phase-p09^{}` 的 commit SHA 等于 `$deliverySha`；tag 对象自身 SHA 不应拿来和 commit 比较。phase-p06 用相同规则单独处理，不复制 P09 SHA 当作其天然通过依据。

**最终通过条件：**原需求全部本地必需能力及验收满足；交付源码=受验收源码（或仅文档后续）；原环境恢复且用户快照可用；main/CI/标签核对成功。真实 ERP 状态继续独立说明；不自动开始 P10。

## 14. 每卡统一提交、失败处理和报告格式

### 14.1 显式提交模板

`<本卡文件>` 不是可直接执行的字面量。实施者必须先写出确切路径列表，逐个核对后执行；不要用目录通配把其他卡文件一起放入。

```powershell
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff check failed' }
git status --short
# 示例仅适用于L02；其他卡替换为自己的明确文件列表。
git add -- backend/app/agent/fact_checks.py backend/app/agent/graph.py `
  tests/unit/test_fact_claim_context.py evidence/P09-L02.md
if ($LASTEXITCODE -ne 0) { throw 'stage failed' }
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'staged diff check failed' }
# 人工核对暂存内容，无密钥/原始库存/运行目录；README和交接如有变更也逐个显式加入。
git commit -m 'fix(p09): preserve claim field and entity context'
if ($LASTEXITCODE -ne 0) { throw 'commit failed' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'push failed; retain commit' }
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

暂存区若已含用户/其他卡文件，先查看并记录，不擅自把它们提交。只取消自己本次误暂存的内容，不破坏已有暂存意图；必要时用明确路径的独立提交方式。

### 14.2 什么时候必须停止本卡

| 情况 | 处理 |
|---|---|
| RED 原因是权限/环境/命令错误 | 修环境后重跑，不改生产逻辑迎合 |
| 新测试通过但原错误无法复现 | 不宣称修复，先核对实际版本/输入和失败 trace |
| API成功但 MCP/fake入口不同 | 补真实入口接线与回归，不只改辅助函数 |
| 订单说明失败但已提交 | 查同一订单/operation，纯正文修订，不重下单 |
| 远程 dispatch 后结果未知 | 只 lookup；404仍未知，不重发POST |
| live失败 | 保存全部记录，确定原因、定向修复、新源码及新全批次 |
| 全量测试后又改代码/测试/脚本 | 撤销候选通过状态，重新冻结并跑相应完整门禁 |
| push或CI或tag核对失败 | 保留提交与证据，写准确未完成状态 |
| 日常Mongo不兼容且有持久数据 | 保留数据和卷，提出有备份的新实例迁移方案，不 reset |

### 14.3 每卡证据模板

```markdown
# P09-Lxx：任务名称

日期/实施者：
状态：已关闭 / 部分关闭 / 未运行
源码基线SHA：
本卡修改文件及目的：

## 修复前反例
命令、原输入、实际失败断言、日志位置；区分产品/环境。

## 实现
实际调用链、规则、未改变的授权/事务/事实边界。

## 定向结果
| 命令 | passed/failed/skipped | 退出码 | 报告 |
|---|---|---|---|

## 数据事实
明确库/批次，写前/写后的订单、operation、approval、库存/流水及唯一关联。
只读任务注明未产生写入的核对范围，不夸大为全库完全相同。

## 后续全量门禁
offline / browser / fixed live / CI / clean restore各自实际状态。
尚未运行写not_run，不写“预计通过”。

## 交付与限制
已核对的上一提交/远端SHA、CI run、证据文件、剩余项及下一卡。
提交本身不试图包含自己的SHA；当前提交SHA由后续交接与远端核对提供。
```

最终报告增加：L00–L09逐项结果、F01–F18逐项状态、完整门禁批次、clean源/目标、环境恢复、交付SHA/main/annotated tags、真实ERP未验证限制。禁止只写一句“全部测试通过”。

## 15. 给下一位实施 Agent 的可复制指令

```text
项目：C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent
远端：https://github.com/newerwell/technologyagent.git

我授权你按 docs/implementation/P09-complete-to-release.md 从 L00 开始，
顺序实施剩余补修、定向测试、每卡显式提交推送、最终门禁与恢复交付。
这是继续完成P09，不是重写，不开始P10。

先读AGENTS.md、共享契约、最终矩阵、Git规则和本手册，再核对实际HEAD/status/远端。
编写手册时HEAD/origin/main为8538f4c4971baefc4a2b387357b8a0fba318faab，
当前工作区有尚未提交的固定业务时钟实现及两份新测试，必须审查保留，不能覆盖或混入无关文件。
固定live旧批次20261109T013237Z-5c620c8e57为4/13通过，必须保留，不能当成通过。
当前Docker和服务是否运行要实际检查，不能只凭聊天历史。

每卡：读取→反例→确认产品失败→最小修复→定向回归→证据/README/交接→明确路径commit/push。
没有通过本卡不要跳到下一卡，不先写“已完成”。新失败要定位，不加尝试次数碰运气。
所有写测试用专用27028 ta-rs、technologyagent_test_*与合成数据；不碰日常dev数据/旧mongo-data。
不提交.env、原始库存/metadata、运行日志/库/下载/依赖；不调用真实ERP，远程写caps保持关闭。
不放宽事实/单位/来源/范围/审批/owner/版本/幂等/预算/取消检查。
不要使用git add .、reset --hard、clean、强推或覆盖标签。

最终必须在同一已推送源码上完成offline、精确SHA CI、完整双尺寸browser、固定13外层live，
再全新clone锁安装并跑真实完整备份恢复及恢复后批准/下载/隔离，最后恢复用户live/snapshot环境。
只有全部本地必需场景与交付核对完成，才能创建phase-p09；F15/F16真实ERP继续单独not_run。
每卡报告真实结果、证据和下一步；中断时更新HANDOFF，使下一位不需猜测。
```

## 16. 本计划自检与执行状态

本文为规划交付，本轮没有按本计划执行新的产品修改或验收。L00–L09 的复选框全部保持待执行；前述历史结果仅为定位依据。

| 原要求 | 本计划落点 |
|---|---|
| 原任务0工作区与基线 | L00、L01、每卡Git模板 |
| 原任务1停用物料 | L06复核并引用原定向证据，缺失则补卡 |
| 原任务2模型修订保留 | L02、L05及harness回归 |
| 原任务3订单说明与历史事实 | L03、L05、订单事务事实 |
| 原任务4统一调用/预算/有限重试 | L01双时钟、L05模型观测、L06原边界回归 |
| 原任务5报告快照/结构化范围 | L06、L07报告下载、L09用户快照 |
| 原任务6版本隔离 | L06及L08原checkpoint恢复 |
| 原任务7远程读取/持久屏障/对账 | L06本地HTTP模拟回归，真实ERP仍未验证 |
| 原任务8全部23工具证据 | L06、L09矩阵归档 |
| 原任务9双尺寸/实开/干净检出 | L07、L08 |
| 原任务10正确环境全门禁及恢复 | L07–L09 |
| 原任务11CI/Git/标签/最终交接 | L07、L09、第14节提交模板 |

自检要求：任务用到的计划新增文件清楚标注；函数签名及使用方一致；所有判分修复同时有正确句通过和错误句拒绝；没有把旧CI/旧报告/收集成功替代最终验收；不存在“先打标签再补证据”的步骤。
