# scripts 运行与验证脚本

## 职责

- `init_db.py`：等待/初始化 MongoDB 单节点 replica set `ta-rs`，幂等创建 P00/P01/P02 collection 与索引、`schema_version=1`。
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
uv run python -m scripts.verify_stage P02 --mode offline --report .runtime/reports/P02-offline.json
uv run python -m scripts.verify_stage P02 --mode browser --report .runtime/reports/P02-browser.json  # 需先启动 3030/8030
```

## 限制

- `check_compatibility` 的 DB 探针需要 replica set 已启动（`docker compose up -d`）。
- `verify_stage` 不是“模拟通过”：pytest 退出码 5（无测试）会判失败；P00 manifest 不含 unit 命令，P01 起 unit 必跑。
- `seed --reset` 只允许 `technologyagent_test_*`；verify_stage 的 seed 使用专用测试库。默认 seed 的 `fixture_counts` 是种子输入数量，`database_counts` 是执行后实际 DB 数量。
- 旧基线修正默认 dry-run，不自动执行；不要用 reset 修正开发库，且当前开发库业务 collection 为空。
- P02 browser 模式运行 `tests/e2e/chat-flow.spec.ts`，需要本机 Chrome 与已启动的 3030/8030；CI 只跑 offline。
- P02 live 模式无检查，返回 not_run；FakeAgent 结果不能写成真实模型联调。
