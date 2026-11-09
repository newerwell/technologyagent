# TechnologyAgent 最终完成实施手册

日期：2026-11-08。当前核对源码为`7f63ce497cc851e3985b802a521cb1e819726bdd`。

规格依据：[共享契约](../specs/CONTRACTS.md)、[最终场景](../specs/FINAL-ACCEPTANCE.md)、[7f63复审](../reviews/2026-11-08-P09-7f63-review.md)。本文C00–C11是实施任务编号，F01–F18是原验收场景编号，二者不要混用。

> 给实施Agent：本文件是剩余工作的唯一执行入口，替代旧计划的执行次序和过时状态；原共享契约与最终验收标准不降低。采用executing-plans顺序执行C00–C11；每卡读取实际代码、写反例、确认真实失败、最小修复、定向回归、证据和交接、显式commit/push。当前卡没有通过，不跳下一卡，不把状态改成完成。用户要完整交付，不是仅修改若干文件或得到一份绿报告。

## 0. 最终目标、当前事实与执行规则

### 最终要交付什么

独立项目完成：库存查询→核验补货→比价→报告下载→采购草稿→数量/金额编辑→人工审批→幂等下单→刷新/重启恢复→订单历史及必要审计。对应F01–F14、F17–F18和固定live通过，干净检出具备相同能力，源码/证据/远端/阶段标签一致。

真实ERP F15/F16可以独立保持not_run；本地模拟器不能冒充真实ERP验收。真实ERP写capability继续关闭。不得因此省略已要求的远程协议、持久dispatch和只读对账本地实现。

### 哪些保留，不从头重做

- R0隔离Mongo、R1停用件、A1模型错误分类/硬期限、A2来源目录、A3版本演化、A4兼容runner均已有实现。
- R5远程查询、R6持久写屏障、R7正常业务工具矩阵、R8双尺寸真实流程已有主体和定向证据。
- 7f63复审实际356 unit、20项R5/R6/既有MCP集成通过；六份R8下载文件字节与hash匹配。当前head的GitHub run42475723919成功，但job只有P06。
- 仍需补R5期限/别名、R6审批完整性、R7非法参数wire、R8配置传递，以及全部最终门禁。

### 工作区和数据边界

工作目录：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`。远端：`https://github.com/newerwell/technologyagent.git`。

- 必须先重新查HEAD/status/main/tag，不能把上面SHA当永久事实。
- 一次只做一张卡；不同时修改多个业务子系统。卡内独立只读审查可以并行，实现按顺序。
- 测试只写technologyagent_test_*；不reset technologyagent_dev、不复用或重置原mongo-data、不改用户JSON/metadata/.env。
- 测试Mongo只用127.0.0.1:27028、ta-rs、technologyagent-p09-acceptance-mongodb、命名卷technologyagent-p09-acceptance-mongo。
- C05实施裁定：采用R8已验证的专用8131/3131/9131，代替旧规划8031/3031/9031；没有改动项目日常默认端口。
- 原本27027/technologyagent-mongodb属于日常环境。本地验收和备份恢复不能悄悄访问它。
- local_seed用于完整采购验收；local_snapshot只读用户副本72条/72物料/6仓位。缺报价/预留/在途/目标保持null/未知，不补造。
- 固定业务时钟和合成数据；不得将日期、价格、供应商、真实库存硬编码到生产回答。
- 不用git add .、reset --hard、clean、强推、改旧标签；不删除用户/其他Agent改动。运行目录、依赖、密钥、原始库存和下载文件不提交。
- 环境错误、命令错误、依赖缺失不是产品反例；先解决环境再测。没有执行测试体不能记passed。
- 不跳过断言、不减少live排程、不只保存成功。工具/审批/owner/版本/金额/单位/来源/预算检查不得放松。

### 复审重点与负责卡

| 容易漏掉的条件 | 必须在哪张卡验证 |
|---|---|
| 最后一页或单实体响应迟到，不能因无下一页就成功 | C01迟到/取消/总deadline反例 |
| 已存提案与请求一致，但保存的批准hash或版本不一致 | C03真实入口拒绝且POST/operation/消费均零 |
| 父服务正确，重启子进程却换库、URL、存储或来源 | C05两套端口、clean库和真实重启配置 |
| 备份脚本误用27027、恢复到错误namespace或文件关联不符 | C06脚本guard、C09真实恢复前后全量核对 |
| 绿报告来自旧源码、替身或只恢复一个文件 | C07冻结candidate、C08真实门禁、C09新clone全恢复、C11核SHA |

### 证据与命令纪律

每卡记录：源代码SHA、实际命令、测试数量、退出码、首次产品失败、修后结果、DB/文件事实和限制。使用独立批次和basetemp，旧报告不覆盖。

```powershell
$PSVersionTable.PSVersion
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location -LiteralPath 'C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent'
$batch = Get-Date -Format 'yyyyMMdd-HHmmss'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.runtime/uv-cache'
```

每个native命令后立即保存并判断退出码；不能让Get-Content或下一条成功掩盖失败：

```powershell
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "检查失败，exit=$exitCode；停止本卡并查看对应报告。" }
```

优先`uv run python -m pytest -p no:cacheprovider --basetemp .runtime/pytest-Cxx-<batch> ... -q -rs`。若uv仅因缓存ACL无法运行，先使用上述仓库内UV_CACHE_DIR；仍失败时可用仓库`.venv/Scripts/python.exe`执行同一模块，真实记录命令，不改测试来适配权限。

上面的native失败即停止设置适用于GREEN/交付/门禁；观察RED时显式捕获预期非零、确认错误来自目标产品断言，再修复。不能用“预期RED”吞掉实际GREEN或门禁失败。

PowerShell全局变量仅在同一进程有效。如果工具每次新建PowerShell，不能假称上一工具调用的环境快照仍存在；每次测试/启动显式加载所需模式，正常配置另按C00保存与C10核对。

## C00：建立可恢复基线与稳定验收环境

**目的：**确认检查的是同一份代码，后续不会切错Mongo/库/源码。只处理环境和规格交付，不改业务逻辑。

1. 执行git status --short、git log -5 --oneline、git diff --stat、git ls-remote origin refs/heads/main及phase-p06/phase-p09。
2. 读取AGENTS、CONTRACTS、FINAL-ACCEPTANCE、本文件及7f63复审。当前已存在的HANDOFF/STATUS/旧计划文档修改是审查结果，不重置丢弃。
3. 在`.runtime/private/`保存本轮会覆盖的环境变量原值和“是否存在”；不输出、不提交。包含compose、两Mongo URI、数据库、四来源、snapshot路径、MODEL_MODE/RUN_LIVE_MODEL、三应用端口、LIVE_API_URL、P09_BROWSER_BASE_URL、STORAGE_ROOT、UV_CACHE_DIR、P06_REQUIRED。不复制MODEL_API_KEY；原.env保持不变。URI如有认证也只能留此私有恢复材料。
4. 另存非敏感原Settings摘要、原始库存/副本/metadata的本机hash与72条结构计数，作为恢复核对；hash材料留忽略目录，不把原始JSON/metadata带入Git。
5. 只读检查Docker及27028 hello。检查实际容器挂载，不是只看容器名字；数据库必须setName=ta-rs、isWritablePrimary=true。
6. 若Docker正常且实例存在，直接使用；不要重建。若专用容器未启动，只启动指定compose/project。端口被不明standalone占用时先查归属，不能在该节点rs.initiate/reset/drop，也不能切27027逃避。
7. 确认原.env/JSON/metadata仍忽略且未跟踪。将本文件、最新7f63复审、相关计划/交接显式纳入一次文档基线提交，保证干净clone也有规格；不加入其他未审查旧文档/截图。

```powershell
git status --short
git log -5 --oneline
git ls-remote origin refs/heads/main 'refs/tags/phase-p06*' 'refs/tags/phase-p09*'
git check-ignore .env data/inventory_snapshot.json data/inventory_snapshot.meta.json
git ls-files .env data/inventory_snapshot.json data/inventory_snapshot.meta.json
docker info --format '{{.ServerVersion}}'
docker ps --filter name=technologyagent --format '{{.Names}} {{.Status}} {{.Ports}}'
docker inspect technologyagent-p09-acceptance-mongodb --format '{{json .Mounts}}'
docker exec technologyagent-p09-acceptance-mongodb mongosh --port 27028 --quiet --eval 'const h=db.hello(); print(JSON.stringify({setName:h.setName,isWritablePrimary:h.isWritablePrimary}))'
# 只有需要启动已确认的专用实例时执行
docker compose -f compose.p09-acceptance.yaml -p technologyagent-p09-acceptance up -d mongodb
```

**完成条件：**规格已交付、恢复资料留本机、真实PRIMARY可访问、专用卷正确，未碰原mongo-data。Docker命令失败但Mongo可读时应分别记录；容器沙箱和备份需要Docker时仍不能宣称环境已全好。

## C01：R5读取总期限覆盖最后页和单实体

**修改：**`backend/app/integrations/provider_queries.py`。测试：现有test_provider_queries.py与test_provider_queries_r5.py。

### 先加反例并观察失败

- test_remote_last_page_cannot_succeed_after_deadline：max_query_seconds=0.01、remaining_budget=0.01，provider在0.04秒后返回合法单页；旧代码成功，必须拒绝。
- test_remote_get_uses_total_deadline：同样预算及延迟，合法Supplier.get不得迟到成功。
- test_remote_get_uses_service_timeout_without_explicit_budget：不传remaining_budget，仍受max_query_seconds控制。
- test_remote_all_records_shares_one_deadline：分页/all_records总期限从第一次请求前计算，不能每页刷新；第二页没有剩余时间时不得发起。
- test_remote_timeout_cancels_and_closes_read：取消/超时后等待任务和HTTP响应释放，不留下背景读取。

### 固定实现要求

1. page/get/all_records一次逻辑读取开始时计算`deadline = monotonic() + min(max_query_seconds, remaining_budget)`；remaining_budget缺失则用max_query_seconds。非有限值、非正值在发请求前拒绝，不能无限等待。
2. 抽内部“剩余时间检查/有限等待”帮助函数，三入口共用；对provider.query的等待使用剩余期限，不只把数值作为参数传给provider。
3. 请求前、返回后、DTO转换及集合聚合完成后核期限；没有下一页也必须检查，晚到结果不返回成功。
4. 超时沿用503 DEPENDENCY_UNAVAILABLE和真实retryable语义；不要改成缺字段错误。页码/total/重复ID/100页10000条触顶拒绝等原校验不变。
5. 测试用可控时钟验证期限计算，用短异步延迟或本地慢响应验证真实等待取消；不依赖当天业务日期，不请求ERP。

```powershell
. .\scripts\p09_acceptance_env.ps1 -Mode offline
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C01-$batch" tests/unit/test_provider_queries.py tests/integration/test_provider_queries_r5.py -q -rs
```

**完成条件：**迟到page/get/all_records均拒绝，预算未耗尽的合法单页/多页正常，deadline不刷新，资源释放已断言。更新integrations README及C01证据，提交`fix(p09): enforce complete remote read deadlines`并推送核SHA。

## C02：R5库存别名与缺字段检查统一

**修改：**`backend/app/integrations/erp/mappings.py`，必要时调整provider_queries原始类型检查；不改既有Inventory DTO放宽必需字段。

1. 在映射/查询测试中参数化三种库存数量名称：on_hand、quantity、stock_qty；库存ID两种：id、inventory_id。输入均为同一完整合成事实。
2. 固定例子：I01/P01/W01，on_hand=8、reserved=2、inbound=1、safety_stock=4、target_stock=10、version=2。应得到available=6、projected=7、shortage=3、warning=false；ID保持I01。
3. 先看inventory_id+quantity旧实现以missing id,on_hand失败，再修复。
4. 同一字段的映射、缺失判断、原始类型检查使用同一别名定义；优先级沿用规范字段在先、已有别名次之。不要用`or`误把0当缺失，不做模糊字段猜测。
5. 缺所有数量别名、缺ID、null、bool冒充整数、负数、不合法版本仍拒绝；on_hand=0合法。不要补0或虚构单位/目标库存。
6. 真实本地HTTP模拟器分别经REST和MCP返回上述合法别名数据，结果一致；删除必需字段则两入口失败且无Mongo回退。

```powershell
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C02-$batch" tests/unit/test_provider_queries.py tests/unit/test_p08_erp_adapter.py tests/integration/test_provider_queries_r5.py tests/integration/test_provider_contract.py -q -rs
```

**完成条件：**声明支持的每个别名通过、缺字段/类型反例仍拒绝、API/MCP一致。更新erp-mapping.md和证据，提交`fix(p09): align inventory aliases and required fields`并推送。

## C03：R6批准载荷hash和版本完整性

**修改：**`backend/app/services/remote_operations.py`；如提取公共规范hash函数，同步ApprovalService调用，不能改变既有hash算法。测试扩展test_remote_operations_r6.py。

### 必须分清两种hash

- 审批hash：ApprovalService.request_mutation对`parse_mutation_payload(action,payload)`结果，用UTF-8、ensure_ascii=False、sort_keys=True、separators=(',',':')规范JSON做SHA256。
- operation hash：当前还包含approval_id/action/payload，用于同键重放。保持此用途，不能拿它替代审批hash。

### 反例与修改

1. 经服务器建立ORIGINAL供应商提案并批准；在隔离测试内修改proposal_payload为CHANGED、保留原payload_hash，执行CHANGED。当前可POST成功，修后必须409 STALE_APPROVAL。
2. 错误hash拒绝时：HTTP模拟器POST=0、没有新operation、审批仍未消费、业务集合无变更。不能只测私有比较函数；真实事务入口也测。
3. 校验owner/action/approve/pending后，规范化已存提案与请求，比较二者，再重算已存规范提案hash并与保存hash比较；空/缺hash也拒绝。上述步骤先于operation持久化和POST。
4. 对当前generic提案规则，version/draft_version均须为正整数（不接受bool）且一致；不一致/缺失为STALE_APPROVAL。公共决策入口的expected_version检查保留；不能仅记录当前版本就算验证。
5. 创建operation时保存经核验的approved_payload_hash、approval_version、proposal_version；审批消费CAS绑定经核验hash、两个版本、owner/action/decision/status与ID。
6. 以上审批校验针对新认领/新dispatch。已成功operation的合法同键重放继续返回原持久结果，不要求已消费审批重新变pending；同键异payload仍冲突，既有远程operation不能重新认领或POST。
7. 继续跑并发、子进程崩溃、丢响应、坏JSON、结果保存失败、lookup404及owner/provider隔离。测试POST总数在持续模拟器侧计，不在单个client内存计。

```powershell
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C03-$batch" tests/integration/test_remote_operations_r6.py tests/integration/test_business_mutations.py tests/integration/test_order_idempotency.py tests/integration/test_inventory_receipts.py tests/integration/test_provider_switching.py -q -rs
```

**完成条件：**错误hash/版本在任何外部写前拒绝，合法审批只POST一次，未知结果只lookup。真实ERP写actions仍为空。更新README/证据，提交`fix(p09): verify remote approval integrity before dispatch`并推送。

## C04：23工具真正非法参数的MCP验收

**修改：**test_p08_tool_matrix_r7.py及必要的实际MCP验证入口；保留现有正常写/owner/版本/重放矩阵。下面是新增非法输入，不是替代正常输入。

| 工具 | 必须实际发送到MCP的非法输入 |
|---|---|
| supplier_query | `{"page":"invalid-int"}` |
| supplier_page | `{"payload":[]}` |
| supplier_get | `{}`（缺supplier_id） |
| supplier_create | `{"payload":[]}` |
| supplier_update_status | `{"payload":[]}` |
| part_query | `{}`（缺part_id） |
| part_search | `{"page_size":"invalid-int"}` |
| part_by_supplier | `{"payload":[]}` |
| part_page | `{"payload":[]}` |
| part_create | `{"payload":[]}` |
| order_create | `{}`（缺draft_id/approval_id/idempotency_key） |
| order_update | `{"payload":[]}` |
| order_page | `{"page":"invalid-int"}` |
| order_get | `{}`（缺order_id） |
| order_search_details | `{"payload":[]}` |
| order_statistics | `{"payload":[]}` |
| order_update_status | `{"payload":[]}` |
| inventory_warning | `{"page_size":"invalid-int"}` |
| inventory_page | `{"page":"invalid-int"}` |
| inventory_check | `{"payload":[]}` |
| inventory_inbound | `{"payload":[]}` |
| inventory_outbound | `{"payload":[]}` |
| inventory_get | `{}`（缺inventory_id） |

1. 先从实际MCP list_tools核对23工具名字和参数形状；若签名已合法变化，按当前签名选择同等“缺必需/错误类型”反例，记录差异，不删除该工具测试。
2. 用真实Streamable HTTP客户端发送；必须有服务端验证错误证据。仅本地jsonschema.validate失败、查不到记录、合法空列表、不存在ID都不算该项非法结构验收。
3. 当前McpToolClient可能把服务端ToolError包装为MCP_UNAVAILABLE。此处使用已安装FastMCP原始Client.call_tool(name, arguments, raise_on_error=False)，保留原服务端错误标记/content；鉴权仍用原Bearer/ctx。验收需确认验证消息与参数类型/缺失有关，并核连接前后健康；不能把断网/连接拒绝也记参数拒绝通过。业务封装只有必要时细化错误分类，不伪造响应。
4. 非法读取/写入均核业务七集合的计数及被关注记录值；记录错误发生前后operations/approvals/库存/流水。新增回归不能修改合法调用的预期业务效果。
5. 形成23行证据：正常输入/结果、非法输入/真实错误、写前后事实、测试名。读15项、写8项，不再称23只读。

```powershell
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C04-$batch" tests/integration/test_p08_tool_matrix_r7.py tests/integration/test_mcp_tools.py tests/integration/test_business_mutations.py tests/integration/test_order_idempotency.py tests/integration/test_inventory_receipts.py -q -rs
```

**完成条件：**23项非法结构都真正到达服务端且被拒绝；正常8写仍有批准成功/重放/owner/版本和DB事实。环境错误不能入通过计数。更新P09-R7证据，提交`test(p09): validate malformed inputs on every MCP tool`并推送。

## C05：统一验收端口、数据库、URL、存储和重启环境

**修改：**scripts/p09_acceptance_env.ps1、frontend/playwright.config.ts、tests/e2e/order-flow.spec.ts及环境助手测试。

### 固定配置约定

1. 环境助手增加可选`-ApiPort`、`-FrontendPort`、`-McpPort`；默认专用组8131/3131/9131。三参数要么全不提供，要么一起提供，值1–65535且三者不同；模式切换沿用已选组，不重新猜端口。
2. 默认组回归用8030/3030/9030；最终验收实际运行统一用专用组。未知进程占用时不杀进程、不静默改端口，先记录并处理配置。
3. managedNames扩充三端口、P09_BROWSER_BASE_URL、LIVE_API_URL、STORAGE_ROOT、UV_CACHE_DIR、P06_REQUIRED。第一次保存原值与存在性，切mode不覆盖原快照；Restore完整还原。若同一PowerShell已有旧版不完整快照，先用C00材料恢复原环境并清除旧缓存，再加载新版；不能把测试配置补记成原值。
4. 派生P09_BROWSER_BASE_URL=`http://127.0.0.1:<FrontendPort>`，LIVE_API_URL=`http://127.0.0.1:<ApiPort>`。STORAGE_ROOT由各门禁指定独立目录，重启原样继承；不从旧进程或旧.next猜配置。
5. 三种固定库仍为verify/browser/live，不能改manifest绕开。干净检出专用库另按C09显式设置，E2E必须继承而不是强行换回browser固定库。

### 重启代码修改

- 提取`tests/e2e/support/acceptance-env.ts`的`resolveAcceptanceEnvironment(env: NodeJS.ProcessEnv, baseURL: string): NodeJS.ProcessEnv`，消费当前进程环境和Playwright实际baseURL，返回可信restartEnv。
- order-flow删除硬编码8031/3031/9031、固定数据库等覆盖。继承当前两Mongo URI、DB、compose文件/project、四来源、空快照路径、fake flags、三端口、baseURL、STORAGE_ROOT。
- 在seed或stop/start前验证fake/RUN0、四local_seed、数据库test前缀、loopback URL和前端端口匹配。不满足就明确失败；不要只改子进程而父服务仍是live/旧库。
- 默认与专用两组分别测试实际传入重启子进程的环境；再测自定义clean DB和STORAGE_ROOT不被覆盖，以及URL/端口不一致提前拒绝。配置回归可用测试替身捕获子进程参数，真实业务响应仍不得mock。
- 所有live HTTP测试使用LIVE_API_URL；检查是否有漏接的8030固定值，保持实际服务端口与调用端一致。单独TestClient live测试仍用同一Settings/测试URI。
- stop.ps1只停止有本项目有效记录的进程；不扩展成按端口杀未知进程。快照路径显式空值继续不被.env补回。
- E2E报告每个尺寸保存结构化facts JSON：run/thread/order/operation/approval/version、前后库存、产物ID/字节/hash/来源、实际配置和截图路径，供恢复验收复用；不记录cookie/token/密钥。

**定向命令：**

```powershell
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C05-$batch" tests/unit/test_p09_acceptance_environment.py tests/integration/test_startup_configuration.py -q -rs
npm --prefix frontend run typecheck
```

随后按专用组启动，真实跑order-flow双尺寸、workers=1；两套配置传递测试及完整真实专用组流程都通过才关闭。默认端口被未知进程占用时不强占，默认组配置传递回归仍必须执行；真实双尺寸用专用组。

**完成条件：**刷新/重启前后同库、同源、同模型、同URL/端口、同存储；clean DB不被seed到固定browser库；环境可恢复。提交`fix(p09): preserve acceptance configuration across restarts`并推送。

## C06：让备份恢复使用隔离目标，并准备完整恢复验收

**这不是重做业务。** 当前scripts/backup.ps1与restore.ps1写死technologyagent-mongodb/27027；直接照旧命令会碰原数据卷。必须先修目标选择，再做C09。

### 备份/恢复脚本

1. 两脚本增加可选`-MongoContainer`与`-MongoPort`，保留原默认值以兼容既有调用。所有docker exec/cp、mongosh、dump/restore及临时归档清理都使用所选目标，不能只改第一次连接。
2. 当COMPOSE_PROJECT_NAME为technologyagent-p09-acceptance时，必须显式选择technologyagent-p09-acceptance-mongodb与27028；选错或漏选就在读写前拒绝，不能静默fallback原容器。
3. 备份只接受test源库，恢复只接受test目标库；目标库/存储必须是新的、无歧义的目标，不能覆盖源库或已有业务目标。
4. 保留MaintenanceConfirmed、进程已停、namespace归属、manifest版本、路径/reparse point、文件hash、artifact owner/run/storage关联及未知文件拒绝。不得为了跑通删除guard或替换成“只比较数量”。
5. 恢复前检查所选容器真实ta-rs PRIMARY；验证源/目标namespace只属指定test库。归档nsFrom/nsTo和dry-run预检继续使用当前严格逻辑。
6. 给现有test_backup_restore_guards.py补“选错容器/端口拒绝、全部Docker调用一致用指定目标”回归；可用受控docker命令替身捕获参数，但真实恢复仍必须在C09执行。

### 在本卡创建干净检出恢复用例

创建`frontend/playwright.clean.config.ts`和`tests/acceptance/clean-restore.spec.ts`。独立testDir，project仍chromium/Chrome，workers=1、retries=0；不要让深度备份恢复用例混进普通full-browser套件。

- 仅在显式P09_CLEAN_ACCEPTANCE=1、test clean库、27028隔离来源、fake和local_seed环境执行；配置不满足就失败，不假装passed。
- 从R8提取可复用的真实报告/编辑/断言辅助到tests/e2e/support，不复制第二份采购规则。
- 完整场景固定：3格式报告→真实下载→P001/W01草稿55套/66000分→改60套/72000分、版本2→停应用时保持待审→备份整个test库与storage→恢复到全新test库/storage→启动恢复目标→找回同一thread/run/草稿/审批→批准并重放→恰好一单，inbound10→70、on_hand20。
- 恢复前后重新下载同一报告，字节/hash一致，owner/run和来源相同。恢复前先比较所有归档集合计数/关键文档/旧checkpoint内容；应用启动后新session/health等正常附加记录分开记，不混成归档差异。
- 必须用真实API、浏览器、Mongo及当前脚本，不route.fulfill业务/下载。保存完整facts JSON和关键步骤截图；截图条目注明关联artifact文件名/hash，截图本身另算hash。
- 新用例只在C09全新检出实际执行。此卡先完成脚本guard测试、类型/收集检查，确保后面冻结源码时已包含验收程序。

```powershell
uv run python -m pytest -p no:cacheprovider --basetemp ".runtime/pytest-C06-$batch" tests/unit/test_backup_restore_guards.py tests/unit/test_p09_acceptance_environment.py -q -rs
npm --prefix frontend run typecheck
npm --prefix frontend run test:e2e -- --config playwright.clean.config.ts --list
```

**完成条件：**脚本不再被测试环境误导至27027，原恢复安全边界保留，深度恢复用例可收集且位于独立套件。提交`test(p09): target isolated backups and define full restore acceptance`并推送。此时不能称F18已通过。

## C07：增加P09 CI并冻结验收源码

**修改：**`.github/workflows/ci.yml`及必要验证manifest；不删现有P06 job，不用P06 success冒充P09。

### 新job的固定要求

- job名p09-offline，runner沿用已验证ubuntu-22.04，timeout-minutes=90；运行当前check_mongo_kernel，保留真实Mongo健康与事务，不绕过保护。
- 使用compose.p09-acceptance.yaml及27028，MONGODB_URI与MONGODB_TEST_URI同源；MONGODB_DATABASE=technologyagent_test_p09_verify。
- MODEL_MODE=fake、RUN_LIVE_MODEL=0、四模块local_seed、INVENTORY_SNAPSHOT_PATH空；不映射模型/ERP凭证，不复制用户文件。
- 从uv.lock/npm lock安装；构建当前sandbox Dockerfile并使用现有镜像名technologyagent-sandbox:0.1.0，设置P06_REQUIRED=1，保证关键容器测试不能因无镜像默默skip。
- 执行`python -m scripts.run_acceptance --scope local --mode offline`，上传完整报告和脱敏失败输出；失败exit不可被upload步骤覆盖。
- 证明pytest执行、契约检查、类型/前端测试/build等所有必需子检查都通过。对平台专属skip逐项列原因，不能跳核心事务/安全/来源/工具/恢复测试。

### 冻结步骤

1. C01–C06全部定向通过并已push后，完成CI修改及必要合约生成检查。
2. 完整unit/受影响integration/前端检查通过，提交推送本卡，核main及两个job实际状态。
3. 若CI暴露产品失败，回对应卡修复，再重跑；环境下载失败可重试相同run，但不能改产品错误为成功。
4. 两job在同一验收代码提交通过后，记录candidate及其生产代码/测试/锁文件/脚本/compose树身份；写入`.runtime/private/p09-final-candidate.json`（source_sha、p06_run_id、p09_run_id、代码树标识）。这是后续验收源码，不能在后续工具进程丢失变量后随手用新HEAD替代。
5. 后续只允许更新docs/evidence；任何程序、依赖、配置、测试或CI变动都必须产生新candidate并重跑相关完整门禁，不继续引用旧SHA。

**完成条件：**当前candidate的P09 job真实通过，P06已有job也通过；本地和远端一致。提交说明`ci(p09): add complete offline acceptance gate`。不创建完成标签。

## C08：本地完整offline、browser和固定live

**前提：**C01–C07完成。不要把356单元或定向20项作为完整offline。

### A. Offline

```powershell
.\stop.ps1
. .\scripts\p09_acceptance_env.ps1 -Mode offline -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.runtime/uv-cache'
$env:P06_REQUIRED = '1'
$batch = Get-Date -Format 'yyyyMMdd-HHmmss'
$candidateInfo = Get-Content -LiteralPath '.runtime/private/p09-final-candidate.json' -Raw | ConvertFrom-Json
$candidate = [string]$candidateInfo.source_sha
# 先核当前源码与candidate相同；后续只文档差异也必须记录
[ordered]@{ batch=$batch; candidate=$candidate; original_checkout=(Get-Location).Path } | ConvertTo-Json | Set-Content -LiteralPath '.runtime/private/p09-final-session.json' -Encoding utf8
docker build -t technologyagent-sandbox:0.1.0 -f backend/app/sandbox/Dockerfile backend/app/sandbox
$buildExit = $LASTEXITCODE
if ($buildExit -ne 0) { throw "sandbox镜像构建失败，exit=$buildExit" }
uv run python -m scripts.run_acceptance --scope local --mode offline --report ".runtime/reports/P09-$batch-offline.json"
$offlineExit = $LASTEXITCODE
if ($offlineExit -ne 0) { throw "offline未通过，exit=$offlineExit" }
```

检查报告每一项command/status/exit/skip。全部必需项通过；不能只看最后一行。没有镜像/ACL/临时目录问题先修环境；不因此改成跳过Docker或事务。

### B. Browser

若是新的工具/PowerShell进程，先从`.runtime/private/p09-final-session.json`读取batch/candidate，不重新生成覆盖已验批次；恢复当前工作目录后再运行下列命令。

```powershell
.\stop.ps1
. .\scripts\p09_acceptance_env.ps1 -Mode browser -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:STORAGE_ROOT = Join-Path (Get-Location) ".runtime/acceptance-$batch/browser-storage"
.\start.ps1
$startExit = $LASTEXITCODE
if ($startExit -ne 0) { throw "browser服务启动失败，exit=$startExit" }
uv run python -m scripts.run_acceptance --scope local --mode browser --report ".runtime/reports/P09-$batch-browser.json"
$browserExit = $LASTEXITCODE
if ($browserExit -ne 0) { throw "browser未通过，exit=$browserExit" }
```

- 固定库technologyagent_test_p09_browser，端口三件套与baseURL必须同源。服务ready模型应为fake，实际inventory/parts来源为local_seed。
- 创建run后在该固定库查到同一run ID，证明服务与验收进程确实同库；不要只看shell变量。
- 全E2E workers=1，不只跑order-flow。两个尺寸各有真实下载、编辑金额、刷新、重启、批准与重放。
- 收集截图/facts：1440×900和390×844的报告、待审版本2、重启恢复、最终单号金额。截图和报告文件均注明准确文件名/hash/源run/源码SHA。
- 独立UI展示替身测试可保留，但不得计入真实业务闭环证据；真实闭环禁止mock成功响应。MD/CSV/JSON与已有三图/HTML确认保留，不要求用户重复手动打开；新格式或新发现异常才补实开。

### C. 固定live

仅offline/browser和确定性反例全部通过后执行。live权限沿用用户已授权最终验收；缺密钥/服务就not_run，不打印密钥、不用fake冒充。

新进程同样先读取session里的batch/candidate，并验证对应offline/browser报告已经成功；不能只相信对话中说过通过。

```powershell
.\stop.ps1
. .\scripts\p09_acceptance_env.ps1 -Mode live -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:STORAGE_ROOT = Join-Path (Get-Location) ".runtime/acceptance-$batch/live-storage"
.\start.ps1
$startExit = $LASTEXITCODE
if ($startExit -ne 0) { throw "live服务启动失败，exit=$startExit" }
uv run python -m scripts.run_acceptance --scope local --mode live --report ".runtime/reports/P09-$batch-live.json"
$liveExit = $LASTEXITCODE
if ($liveExit -ne 0) { throw "固定live未通过，exit=$liveExit；保留完整批次，先定位失败。" }
```

- 固定库technologyagent_test_p09_live，LIVE_API_URL端口必须与当前API_PORT一致（默认专用8131）；ready的configured仅代表已配置，不代表付费请求已成功。
- 原排程不改：13个外层记录；P03三题×三次=9次；F04/F08/F11/F12各三次外层，F12共9组内部偏好场景。每个evidence_path真实存在且唯一。
- 每个要求的run实际使用live模型，检查终态、hard/semantic review、最终正文与持久消息、来源/单位/金额、工具与预算trace、数据库事实，不以HTTP200替代。
- 保留所有失败与成功。失败后定位→反例→修复→定向→新candidate/新批次；不能只重跑失败一次并挑成功，不能增加总尝试次数当通过。
- 模型适配器内部允许的首delta前一次传输重试仍逐次计费/留trace；它不是增加逻辑验收尝试，也不能重放工具或整笔下单。

**本卡关闭条件：**完整offline、完整browser、固定live均通过，原需求必需场景没有被skip。更新evidence/P09-final-local.md和索引并push；如只是文档提交，记录其代码树与candidate相同。

## C09：当前源码干净检出、全库与文件恢复完整闭环

这一步不能用旧a9047b3启动、旧67字节文件恢复或复制现有venv/node_modules替代。

### 全新检出

```powershell
# 先在原checkout停止本项目验收服务，保留所有数据库/卷
.\stop.ps1
$session = Get-Content -LiteralPath '.runtime/private/p09-final-session.json' -Raw | ConvertFrom-Json
$candidate = [string]$session.candidate
$originalCheckout = (Get-Location).Path
$cleanStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$cleanRoot = Join-Path $originalCheckout ".runtime/p09-clean-$($candidate.Substring(0,8))-$cleanStamp"
if (Test-Path -LiteralPath $cleanRoot) { throw '新检出目录已存在，不能覆盖或清理它。' }
git clone https://github.com/newerwell/technologyagent.git $cleanRoot
git -C $cleanRoot checkout --detach $candidate
git -C $cleanRoot rev-parse HEAD
Set-Location -LiteralPath $cleanRoot
$env:UV_CACHE_DIR = Join-Path $cleanRoot '.runtime/uv-cache'
uv sync --frozen --group dev
npm --prefix frontend ci
```

每条分别检查退出码；新目录不复制.env/私有库存/依赖/旧.next。fake运行不需要真实模型密钥。

### 全闭环恢复场景

```powershell
. .\scripts\p09_acceptance_env.ps1 -Mode browser -ApiPort 8131 -FrontendPort 3131 -McpPort 9131
$env:MONGODB_DATABASE = "technologyagent_test_p09_clean_$cleanStamp"
$env:STORAGE_ROOT = Join-Path $cleanRoot '.runtime/clean-acceptance-storage'
$env:P09_CLEAN_ACCEPTANCE = '1'
.\start.ps1
npm --prefix frontend run test:e2e -- --config playwright.clean.config.ts --workers=1
$cleanExit = $LASTEXITCODE
if ($cleanExit -ne 0) { throw "干净检出恢复闭环未通过，exit=$cleanExit" }
```

深度用例按C06实现，实际执行以下事实链：

1. 新test库seed，订单基线2，P001/W01 on_hand20/reserved5/inbound10，生成实际3格式报告、保存字节/hash/来源。
2. 草稿55套/66000分→改60套/72000分、版本2。此时仍只有2张订单，审批待消费。
3. 停clone应用及MCP，registry为空、无进行中写；备份这个完整test库与独立storage。脚本必须传专用MongoContainer/27028与MaintenanceConfirmed。
4. 恢复目标`technologyagent_test_p09_restored_<cleanStamp>`及全新`.runtime/restored-storage-<cleanStamp>`；不能与源库/源存储相同，也不能已有内容。
5. 先在启动前核集合计数、关键文档、旧checkpoint与artifact文件hash；源库/storage不应被恢复操作修改。
6. 将clone服务切至恢复目标DB/storage并启动，用同owner访问同thread/run，实际显示待审批版本2/720.00元；恢复后批准，不重新生成草稿。
7. 同决定键重放仍同订单ID/单号，只新增1单/1成功operation，inbound10→70、on_hand20，审批消费一次。
8. 原报告经恢复后授权下载，字节/hash相同、owner/run/source关联不变，非法owner继续拒绝。恢复后的订单页/历史可读，关键节点截图保存。

手动复核脚本调用形状（测试内也必须使用这些显式目标）：

```powershell
.\scripts\backup.ps1 -DatabaseName $env:MONGODB_DATABASE -Destination $backupPath -StorageRoot $env:STORAGE_ROOT -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028 -MaintenanceConfirmed
.\scripts\restore.ps1 -BackupDirectory $backupPath -TargetDatabase $restoredDatabase -TargetStorageDirectory $restoredStorage -MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028 -MaintenanceConfirmed
```

此处backupPath/restoredDatabase/restoredStorage由深度用例生成、校验并写入facts，不接受空变量或手工猜路径。不要在已完成自动恢复后再重复执行这两条造成二次写入。

**完成条件：**全新clone的candidate源码、锁定安装、报告/文件/待审/完整恢复/审批/重放均有实际证据，不借外层未提交文件。证据保存clone路径、SHA、命令、facts、集合/文件hash与截图。若改程序才修好，必须回原checkout提交并产生新candidate，重新验受影响完整门禁及新的干净检出，不只patch clone。

## C10：恢复用户日常环境并关闭最终矩阵

1. 在clone目录stop其有效进程；回originalCheckout。不要用原目录的stop脚本猜停clone进程，也不kill未知PID。
2. 同一进程原快照存在时Restore；否则读取C00私有恢复材料还原本轮覆盖项的原值/存在性。不要从当前test值创建新“原快照”后假恢复。
3. 核对正常Settings：technologyagent_dev、原live配置、inventory/parts=local_snapshot、data/inventory_snapshot.json；供应商/订单及URI/端口/storage按C00原值。原模型密钥仍只在原.env，不输出。
4. 移除P09_CLEAN_ACCEPTANCE及测试专用URL/端口/compose等覆盖，或恢复它们原本存在的值。正常启动不是test seed；不得执行seed --reset、drop、迁移或rs.initiate原实例。
5. 正常start.ps1通过health/ready；页面与实际MCP各查询72条快照、72物料/6仓位，未知字段仍null/未知。真实快照数据不生成伪报价或完整采购建议。
6. 原始库存/副本/metadata与C00 hash一致，.env未被本轮意外改动，private/runtime/DB文件仍忽略且未跟踪。UI/MCP read-only检查不要求再下单或收费模型探针。
7. 最终矩阵逐项填写下表。旧失败/旧评分保留，追加纠正，不能把历史not_run直接改passed。

| 场景 | 当前完成时必须有的证据 |
|---|---|
| F01 | 库存范围/分页/完整汇总及合成数值；快照只表示已保存集合 |
| F02/F03 | 价格/交期推荐、无有效报价/未知字段，固定live每题3次且真实依据 |
| F04/F05 | 草稿补字段/编辑/拒绝/批准、并发/崩溃/幂等，只一单；副作用逐项核 |
| F06 | 当前v2变化生效时旧v1恢复/重放和namespace/原checkpoint内容保持 |
| F07 | SSE分块/断线/重放/取消，seq及终态持久消息一致 |
| F08 | 数量/金额/单位错误、必要覆盖、语义修订最多2次，失败不重写订单；固定live |
| F09 | 三图及HTML既有实开确认，MD/CSV/JSON实开记录/准确文件hash及真实下载/来源 |
| F10 | 当前CI/本地真实容器超时、禁网、只读挂载/资源边界，关键测试不skip |
| F11/F12 | 两类专家和三技能/偏好范围，固定live与无越权业务副作用 |
| F13 | 23工具正常及真正非法wire输入，8写审批/重放/owner/版本与DB效果 |
| F14 | thread/run/draft/approval/artifact/preference/trace等owner隔离 |
| F15/F16 | 明确not_run，无真实ERP联调/生产上线声明 |
| F17 | 当前源码两个尺寸各完整流程、配置一致、截图/facts和真实字节下载 |
| F18 | 当前candidate新clone、锁文件安装、完整DB+storage恢复后审批/下载/幂等 |

**完成条件：**用户日常环境实际恢复且所有本地必需项均有证据。Docker/端口未知占用等未解决时不能写恢复成功，也不能强杀不明进程。提交本卡证据与矩阵，不创建P10。

## C11：Git、阶段标签、最终报告

### 每卡提交规范

```powershell
git diff --check
git status --short
# git add -- 只列本卡已审查的确切路径，不使用点号或宽泛目录
git diff --cached --stat
git diff --cached --check
git diff --cached --name-only
git commit -m '本卡约定的提交说明'
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

以上stage/commit文字只是操作规范；实施时换成该卡确切文件列表与约定message，不能原样提交“本卡约定”。推送失败保留本地commit，查原因，不强推、不称上传、不进入下卡。

### 源码一致性和标签决定

1. 确认每张修复卡及CI修改都已push；所有全量门禁/clone恢复对应同一个candidate源码。
2. 最终main允许有随后docs/evidence摘要提交。`git diff --name-only $candidate HEAD`只能出现docs/或evidence/；若出现源码/测试/依赖/脚本/compose/CI变化，candidate已失效，不能打标签。
3. 为避免混淆，phase-p09指向实际验收的candidate提交；最终main文档提交SHA另列。核candidate为main祖先，不能把不同代码的旧SHA冒充当前通过。
4. phase-p06自身规格及当前candidate的P06 CI/产物打开等要求全关闭后，补缺失annotated tag，指向有实际通过证据的提交；旧标签若已存在则核验，不覆盖。
5. phase-p09只在C00–C10和本地F01–F14/F17–F18全部关闭、固定live与P09 CI/干净检出通过后创建。F15/F16 not_run不能被改成“已联调”。

```powershell
git ls-remote origin 'refs/tags/phase-p06*' 'refs/tags/phase-p09*'
# 仅对应标签确实不存在且该阶段门槛全部通过时执行
git tag -a phase-p06 $candidate -m 'P06 requirements verified; see final acceptance evidence'
git push origin refs/tags/phase-p06
git tag -a phase-p09 $candidate -m 'P09 local acceptance completed; real ERP F15/F16 not run'
git push origin refs/tags/phase-p09
git ls-remote origin refs/heads/main 'refs/tags/phase-p06' 'refs/tags/phase-p06^{}' 'refs/tags/phase-p09' 'refs/tags/phase-p09^{}'
```

annotated tag对象SHA不等于提交SHA；必须核`^{}`解引用结果。若标签已存在指向不同提交，停止并保留原标签，先核其验收依据，不能移动它来消除差异。

### 最终报告必须逐项填

| 字段 | 必须填写 |
|---|---|
| 源码 | candidate、本地main、远端main及源码差异核对 |
| 任务 | C00–C11各自已关闭/部分/未运行，具体修改 |
| 反例 | 修前真实失败和修后对应测试，不把环境错误当产品RED |
| 定向 | 命令、数量、退出码、关键断言 |
| 全量 | offline/browser/live和P09 CI各自批次、完整子检查和真实结果 |
| 业务事实 | 订单、operation、审批、库存、流水的具体变化 |
| 文件 | 报告/截图/源run/字节/hash/打开与授权下载 |
| 新检出 | 路径、安装锁文件、SHA、全库及storage恢复闭环 |
| 用户环境 | 正常进程/URI/端口/source和72条实际回读，私有文件保护 |
| Git | 每卡push、阶段tag及解引用SHA，未上传项明确列出 |
| 限制 | F15/F16 not_run及其他真实未满足项；不得藏进“全部通过” |

只有全部必需项已达到并能回查证据，才报告“P09本地完整版本完成”。任何产品失败、未运行的必需gate、源码不一致、恢复未确认或标签未上传，均继续保持未完成。不得靠删需求、扩展skip、挑成功或改验收表完成项目。

## 失败时下一步，不交给实施Agent猜

| 现象 | 处理 |
|---|---|
| Mongo standalone/无PRIMARY/pipe消失 | 记录失败时点及URI，检查同一专用容器/挂载/hello；恢复后重跑未执行体，不能切原库或重置卷 |
| uv/pytest cache ACL | 使用仓库内cache/basetemp与必要授权；保持断言，不记产品失败 |
| Next旧锁/旧构建/端口占用 | 先核本项目登记PID及配置，正常stop后新构建；不按端口乱kill、不删未知目录 |
| 迟到远程结果/别名误拒 | 回C01/C02补反例，不放宽完整性/字段校验 |
| 审批hash/版本异常或重复远程POST | 回C03；真实写继续关闭，已dispatch未知只能lookup |
| MCP参数错误被网络错误掩盖 | 回C04确认真实wire错误分类及服务健康，不能把断网当参数验收 |
| E2E重启后换库/端口/源 | 回C05核父/子环境、实际run所在库和baseURL |
| 备份namespace/hash/关联错误 | 回C06保持拒绝；不能去掉校验或只换目标名碰碰运气 |
| live硬事实/语义失败 | 保留全13记录，定位对应代码→反例→修复→新candidate及完整新批次；不加尝试挑成功 |
| 仅文档声称成功、原文件/trace缺失 | 补真实证据或保持not_run，不能按摘要补造轨迹 |
| 原环境无法恢复/未知进程占用 | 保留现场，报告确切阻断；不得先创建完成标签 |
