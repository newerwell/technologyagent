# fixtures/v1 合成数据

## 职责

P01 固定验收数据，全部为合成数据：6 零件、3 供应商、8 报价、8 库存、2 历史草稿、2 历史订单。

## 文件与约束

- `parts.json` / `suppliers.json` / `quotes.json` / `inventories.json` / `drafts.json` / `orders.json`。
- `manifest.json` 由 `scripts.seed --write-manifest` 生成：计数、按仓库汇总、全量汇总、canonical SHA256、固定时钟 `2026-10-23T02:00:00Z`。
- 固定案例：
  - P001/W01：20 在手、5 预留、10 在途、30 安全、80 目标 → 15/25/55。
  - Q01=S01/1200/MOQ10/5天；Q02=S02/1100/MOQ1/12天；Q03 已过期且 S03 停用。
  - P002/W02 预计可用量=15=safety，不预警。
  - P003/W01 有缺口但无有效报价。
  - O001/P001/W01 未收 10 件支撑 inbound=10。

## 使用

```powershell
uv run python -m scripts.seed --write-manifest
uv run python -m scripts.seed                 # 幂等 upsert，不删用户订单
uv run python -m scripts.seed --reset --database technologyagent_test_p01_local
```

`--reset` 只允许测试库；默认 seed 不删除数据。修改 fixtures 后必须重新生成 manifest 并让 `--check` 通过。
