# scripts 运行与验证脚本

## 职责

- `init_db.py`：等待/初始化 MongoDB 单节点 replica set `ta-rs`，幂等创建 P00 索引和 `schema_version=1`。
- `check_compatibility.py`：真实导入并最小调用 FastAPI、LangGraph、模型适配、Mongo checkpointer、FastMCP、DeepAgents，以及真实 Mongo 事务回滚探针。
- `verify_stage.py`：按阶段 manifest 运行真实命令，保存退出码、耗时和输出尾部到 JSON 报告。

## 入口

```powershell
uv run python -m scripts.init_db
uv run python -m scripts.check_compatibility
uv run python -m scripts.verify_stage P00 --mode offline --report .runtime/reports/P00-offline.json
```

## 限制

- `check_compatibility` 的 DB 探针需要 replica set 已启动（`docker compose up -d`）。
- `verify_stage` 不是“模拟通过”：pytest 退出码 5（无测试）会判失败；P00 无 unit 测试，因此 manifest 不包含 unit 命令。
- live/browser 模式在 P00 无检查，返回未执行状态而不是通过。
