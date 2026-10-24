# fixtures/events 事件协议样本

## 职责

`v1.json` 是 P02 12 类事件的代表性 fixture：run_started/token/tool_started/tool_finished/interrupt/phase/plan/review/artifact_ready/error/run_finished/stream_end，覆盖所有共享事件类型。

## 约束

- 每个事件必须通过 `backend/app/contracts/events.py` 的 EventEnvelope/payload 校验。
- 时间带时区且解析为 UTC；seq 从 1 递增；工具 started/finished 使用同 call_id。
- 该 fixture 只验证 schema，不表示对应未来事件已有业务实现（phase/plan/review/artifact 等）。
- 修改 schema 后运行 `uv run python -m scripts.export_contracts` 并提交生成差异。

## 验证

`uv run pytest tests/unit/test_event_contracts.py -q`
