# scripts 运行与验证脚本

## 职责

- `init_db.py`：等待/初始化 MongoDB 单节点 replica set `ta-rs`，幂等创建 P00–P04 collection 与索引、`schema_version=1`。
- `check_compatibility.py`：真实导入并最小调用 FastAPI、LangGraph、模型适配、Mongo checkpointer、FastMCP、DeepAgents，以及真实 Mongo 事务回滚探针。
- `seed.py`：校验 `fixtures/v1`，核对 manifest 与订单/inbound 对账，默认只补缺失记录，不覆盖已有记录/version；`--write-manifest` 生成汇总，`--reset` 仅限测试库。
- `repair_p01_baseline.py`：显式修正旧 I004/I006/I007 基线；默认 dry-run 输出备份/变更，`--apply` 事务执行，冲突或相关新增订单时拒绝。
- `export_contracts.py`：生成领域/事件 JSON Schema、`frontend/src/lib/domain-types.ts` 与 `frontend/src/lib/events.ts`；`--check` 只检测差异。
- `verify_stage.py`：按阶段 manifest 运行真实命令，保存退出码、耗时和输出尾部到 JSON 报告。
- `run_acceptance.py`：P09验收入口，`--scope local|erp`独立记录，ERP环境未明确授权时记`not_run`。
- `check_mongo_kernel.py`：CI启动MongoDB 8前核对Linux内核版本；拒绝已知不兼容的6.19+及7.0.13及以下区间，其他平台跳过。
- `backup.ps1`/`restore.ps1`：只允许`technologyagent_test_*`库；要求维护窗口确认，校验Mongo归档与storage文件哈希，并恢复到新的空测试库及新目录。
- `backup_target.ps1`：两脚本共用目标/PRIMARY保护；P09隔离环境必须显式传`-MongoContainer technologyagent-p09-acceptance-mongodb -MongoPort 27028`，全部Docker命令使用同一目标，禁止静默访问日常27027。备份和恢复前都须停止当前应用；恢复拒绝源库/已存在目标。
- `p09_restore_facts.py`：只读专用27028的严格clean/restored测试库，对每个集合的完整BSON规范文档、数量及artifact内容/owner/run关联生成摘要，供完整恢复比较；不能代替真实backup/restore或批准闭环。用例位于tests/acceptance，结果留.runtime。

## 入口

```powershell
uv run python -m scripts.init_db
uv run python -m scripts.seed
uv run python -m scripts.repair_p01_baseline --database technologyagent_dev  # dry-run
uv run python -m scripts.export_contracts --check
uv run python -m scripts.check_compatibility
uv run python -m scripts.verify_stage P03 --mode offline --report .runtime/reports/P03-offline.json
uv run python -m scripts.verify_stage P03 --mode browser --report .runtime/reports/P03-browser.json  # 需先启动 3030/8030/9030
uv run python -m scripts.verify_stage P03 --mode live --report .runtime/reports/P03-live.json  # 需真实模型配置、隔离测试库与显式启用
uv run python -m scripts.verify_stage P04 --mode offline --report .runtime/reports/P04-offline.json
uv run python -m scripts.verify_stage P04 --mode browser --report .runtime/reports/P04-browser.json  # 需先启动 3030/8030
uv run python -m scripts.verify_stage P04 --mode live --report .runtime/reports/P04-live.json  # 需真实模型配置、隔离测试库与显式启用
uv run python -m scripts.verify_stage P07 --mode offline --report .runtime/reports/P07-offline.json
uv run python -m scripts.verify_stage P07 --mode browser --report .runtime/reports/P07-browser.json  # 需先启动隔离的fake服务
uv run python -m scripts.verify_stage P07 --mode live --report .runtime/reports/P07-live.json  # 需真实模型、隔离测试库与RUN_LIVE_MODEL=1
uv run python -m scripts.run_acceptance --scope local --mode offline --report .runtime/reports/P09-offline.json
uv run python -m scripts.run_acceptance --scope local --mode browser --report .runtime/reports/P09-browser.json  # 需先启动隔离fake服务
uv run python -m scripts.run_acceptance --scope local --mode live --report .runtime/reports/P09-live.json  # 需真实模型与RUN_LIVE_MODEL=1
uv run python -m scripts.run_acceptance --scope erp --mode live --report .runtime/reports/P09-erp.json
```

P07 live的seed与HTTP测试继承调用环境中的同一个`MONGODB_DATABASE`。先用`MODEL_MODE=live`和`technologyagent_test_*`数据库启动本地服务，再在该数据库环境下运行verify_stage，并显式设置`RUN_LIVE_MODEL=1`；不要把服务端与测试端分别指向不同隔离库。

## P09 live 验收

P09 offline有独立GitHub Actions job，使用专用27028、副本集、fake与合成数据；当前sandbox镜像必须实际构建且P06_REQUIRED=1。完整manifest包含8项必需检查（包括typecheck:e2e）；失败日志和JSON总是上传，P06成功不能代替P09成功。browser/live/人工打开与新检出恢复仍单独验收。

P09 live wrapper按唯一batch/attempt保存完整轨迹，seed前记录开始时间；timeout/异常也落盘。子pytest必须有实际passed用例，空收集、全skip、部分skip、失败或timeout均不能标记通过。F12还需核对两段run终态/评审、成功工具结果、偏好持久化、最终回答和业务库前后事实。

## 限制

- `check_compatibility` 的 DB 探针需要 replica set 已启动（`docker compose up -d`）。
- GitHub Actions的P06 job固定使用`ubuntu-22.04`；MongoDB healthcheck必须确认`ta-rs` PRIMARY，不能仅输出布尔值。内核保护依据MongoDB 8已知启动兼容区间，runner实际值仍在CI日志核对。
- `verify_stage` 不是“模拟通过”：pytest 退出码 5（无测试）会判失败；P00 manifest 不含 unit 命令，P01 起 unit 必跑。
- `seed --reset` 只允许 `technologyagent_test_*`；verify_stage 的 seed 使用专用测试库。默认 seed 的 `fixture_counts` 是种子输入数量，`database_counts` 是执行后实际 DB 数量。
- 旧基线修正默认 dry-run，不自动执行；不要用 reset 修正开发库，且当前开发库业务 collection 为空。
- P03 browser 模式运行 `tests/e2e/chat-flow.spec.ts`，需要本机 Chrome 与已启动的 3030/8030/9030；CI 只跑 offline。
- P03 live manifest 非空，固定执行 `tests/live/test_readonly_agent.py` 的 3 个问题各 3 次。运行前必须设置真实 `MODEL_API_KEY`、`MODEL_NAME`、`MODEL_MODE=live`、`RUN_LIVE_MODEL=1`，并使用 `technologyagent_test_*` 隔离数据库；配置不齐时报告 `not_run` / exit 2，禁止以 ScriptedModel/skip/空 manifest 计通过。
- live 通过条件包含实际 run 模式、成功终态、完整末事件、成功只读工具调用、调用参数与固定问题一致，以及成功事实与测试库 seed 对照；完整脱敏轨迹仅写入 `.runtime`，不要提交密钥或原始轨迹。
- P04 offline 覆盖持久检查点、审批/订单事务、并发幂等、崩溃租约和报价/库存版本冲突；browser 覆盖字段补充、服务进程重启后刷新恢复和实际订单查询。P04 live 先重置隔离的 `technologyagent_test_p04_live`，再运行 `tests/live/test_order_workflow.py` 的固定采购场景；缺少真实配置、隔离库或显式启用时为 `not_run`。

## P09隔离验收环境

在PowerShell 7的项目根目录点加载 `p09_acceptance_env.ps1`，它会为当前进程配置P09固定测试Mongo、独立Compose项目、四个 `local_seed` 来源和显式空的库存快照路径。`offline`、`browser`、`live`分别使用独立的`technologyagent_test_*`数据库；前两种启用fake，live仅设置live开关，不会自动发起模型调用。脚本第一次加载时只在当前PowerShell进程内保存受管理环境变量原来的“存在状态+值”，切换模式不覆盖原快照；结束后用 `-Restore`恢复。快照不写文件、不打印，也不触碰真实`.env`密钥。

```powershell
. .\scripts\p09_acceptance_env.ps1 -Mode offline
docker compose config
docker compose up -d mongodb
# 完成当次验收后恢复当前PowerShell的原始环境
. .\scripts\p09_acceptance_env.ps1 -Restore
```

该脚本使用自身位置解析检出根目录。它只选择`compose.p09-acceptance.yaml`；该配置绑定`127.0.0.1:27028`，使用专属命名卷`technologyagent-p09-acceptance-mongo`。不要执行`down -v`，也不要将日常`mongo-data`用于验收。`start.ps1`只在环境变量缺失时导入`.env`；显式空值保持空。隔离Compose启动时，`start.ps1`会在创建runtime目录或启动服务之前拒绝非`technologyagent_test_*`数据库及不匹配的Mongo URI。

对应回归：`tests/unit/test_start_dotenv.py`、`tests/unit/test_p09_acceptance_environment.py`。

C05环境助手另管理三服务端口、`P09_BROWSER_BASE_URL`、`LIVE_API_URL`、`STORAGE_ROOT`、`UV_CACHE_DIR`和`P06_REQUIRED`的原值与存在性。默认专用端口为8131/3131/9131，与已验证R8专用配置一致；可一起指定`-ApiPort/-FrontendPort/-McpPort`，三个必须合法且不同。模式切换沿用所选端口，URL统一派生；默认组回归可显式指定8030/3030/9030。存储路径由调用者选择，重启继承，Restore还原原路径。旧版不完整全局快照会拒绝操作，须先按C00私有材料恢复，不能把测试值补记成原值。
