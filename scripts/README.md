# scripts 运行与验证脚本

## 职责

- `init_db.py`：等待/初始化 MongoDB 单节点 replica set `ta-rs`，幂等创建 P00/P01 collection 与索引、`schema_version=1`。
- `check_compatibility.py`：真实导入并最小调用 FastAPI、LangGraph、模型适配、Mongo checkpointer、FastMCP、DeepAgents，以及真实 Mongo 事务回滚探针。
- `seed.py`：校验 `fixtures/v1`，核对 manifest，幂等 upsert 合成数据；`--write-manifest` 生成汇总，`--reset` 仅限测试库。
- `export_contracts.py`：生成 `domain-schema.v1.json` 与 `frontend/src/lib/domain-types.ts`；`--check` 只检测差异。
- `verify_stage.py`：按阶段 manifest 运行真实命令，保存退出码、耗时和输出尾部到 JSON 报告。

## 入口

```powershell
uv run python -m scripts.init_db
uv run python -m scripts.seed
uv run python -m scripts.export_contracts --check
uv run python -m scripts.check_compatibility
uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-offline.json
```

## 限制

- `check_compatibility` 的 DB 探针需要 replica set 已启动（`docker compose up -d`）。
- `verify_stage` 不是“模拟通过”：pytest 退出码 5（无测试）会判失败；P00 manifest 不含 unit 命令，P01 起 unit 必跑。
- `seed --reset` 只允许 `technologyagent_test_*`；verify_stage 的 seed 使用专用测试库。
- live/browser 模式当前无检查，返回未执行状态而不是通过；浏览器验收按 evidence 手工步骤记录。
