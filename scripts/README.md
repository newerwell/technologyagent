# scripts 运行与验证脚本

## 职责

- `init_db.py`：等待/初始化 MongoDB 单节点 replica set `ta-rs`，幂等创建 P00–P04 collection 与索引、`schema_version=1`。
- `check_compatibility.py`：真实导入并最小调用 FastAPI、LangGraph、模型适配、Mongo checkpointer、FastMCP、DeepAgents，以及真实 Mongo 事务回滚探针。
- `seed.py`：校验 `fixtures/v1`，核对 manifest 与订单/inbound 对账，默认只补缺失记录，不覆盖已有记录/version；`--write-manifest` 生成汇总，`--reset` 仅限测试库。
- `repair_p01_baseline.py`：显式修正旧 I004/I006/I007 基线；默认 dry-run 输出备份/变更，`--apply` 事务执行，冲突或相关新增订单时拒绝。
- `export_contracts.py`：生成领域/事件 JSON Schema、`frontend/src/lib/domain-types.ts` 与 `frontend/src/lib/events.ts`；`--check` 只检测差异。
- `verify_stage.py`：按阶段 manifest 运行真实命令，保存退出码、耗时和输出尾部到 JSON 报告。

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
```

## 限制

- `check_compatibility` 的 DB 探针需要 replica set 已启动（`docker compose up -d`）。
- `verify_stage` 不是“模拟通过”：pytest 退出码 5（无测试）会判失败；P00 manifest 不含 unit 命令，P01 起 unit 必跑。
- `seed --reset` 只允许 `technologyagent_test_*`；verify_stage 的 seed 使用专用测试库。默认 seed 的 `fixture_counts` 是种子输入数量，`database_counts` 是执行后实际 DB 数量。
- 旧基线修正默认 dry-run，不自动执行；不要用 reset 修正开发库，且当前开发库业务 collection 为空。
- P03 browser 模式运行 `tests/e2e/chat-flow.spec.ts`，需要本机 Chrome 与已启动的 3030/8030/9030；CI 只跑 offline。
- P03 live manifest 非空，固定执行 `tests/live/test_readonly_agent.py` 的 3 个问题各 3 次。运行前必须设置真实 `MODEL_API_KEY`、`MODEL_NAME`、`MODEL_MODE=live`、`RUN_LIVE_MODEL=1`，并使用 `technologyagent_test_*` 隔离数据库；配置不齐时报告 `not_run` / exit 2，禁止以 ScriptedModel/skip/空 manifest 计通过。
- live 通过条件包含实际 run 模式、成功终态、完整末事件、成功只读工具调用、调用参数与固定问题一致，以及成功事实与测试库 seed 对照；完整脱敏轨迹仅写入 `.runtime`，不要提交密钥或原始轨迹。
- P04 offline 覆盖持久检查点、审批/订单事务、并发幂等、崩溃租约和报价/库存版本冲突；browser 覆盖字段补充、服务进程重启后刷新恢复和实际订单查询。P04 live 先重置隔离的 `technologyagent_test_p04_live`，再运行 `tests/live/test_order_workflow.py` 的固定采购场景；缺少真实配置、隔离库或显式启用时为 `not_run`。
