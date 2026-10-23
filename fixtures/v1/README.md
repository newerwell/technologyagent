# fixtures/v1 合成数据

## 职责

P01 固定验收数据，全部为合成数据：6 零件、3 供应商、8 报价、8 库存、2 历史草稿、2 历史订单。

## 文件与约束

- `parts.json` / `suppliers.json` / `quotes.json` / `inventories.json` / `drafts.json` / `orders.json`。
- `manifest.json` 由 `scripts.seed --write-manifest` 生成：计数、按仓库汇总、全量汇总、canonical SHA256、固定时钟 `2026-10-23T02:00:00Z`。
- `inventory.inbound` 必须等于同 part/warehouse 的未关闭订单（非 completed/cancelled）剩余量之和；没有订单依据必须为 0。`validate_bundle` 拒绝不满足的 fixture，seed 不会先写库再看报告。
- 固定案例：
  - P001/W01：20 在手、5 预留、10 在途、30 安全、80 目标 → 15/25/55；O001 未收 10 件是唯一在途依据。
  - Q01=S01/1200/MOQ10/5天；Q02=S02/1100/MOQ1/12天；Q03 已过期且 S03 停用。
  - P002/W02：I004 在手 15、inbound 0 → 预计 15=safety 15，不预警。
  - P003/W01：有缺口但无有效报价。
  - P004/W01：I006 在手 12、预留 2 → 预计 10=safety 10，不预警。
  - P005/W02：I007 在手 5、inbound 0 → 预计 5=safety 5，不预警。
  - 精确预警集合只有 I001、I005；O002 已完成，不产生 inbound。

## 使用

```powershell
uv run python -m scripts.seed --write-manifest
uv run python -m scripts.seed                 # 只补齐缺失的固定记录，不覆盖已有记录
uv run python -m scripts.seed --reset --database technologyagent_test_p01_local
```

默认 seed 使用固定 `_id` + `$setOnInsert`：已有记录（包括用户修改、业务 version 和新增订单）不会被重置回 fixture 值。`--reset` 只允许 `technologyagent_test_*` 库，且只用于测试库。

### 旧基线迁移

如果某个已初始化的本地库仍是修复前的错误库存，使用显式修正命令，不要 reset 开发库：

```powershell
uv run python -m scripts.repair_p01_baseline --database technologyagent_dev
uv run python -m scripts.repair_p01_baseline --database technologyagent_dev --apply
```

默认 dry-run，只打印备份/变更列表；`--apply` 在事务内只处理 I004/I006/I007 且要求完整旧字段与 version=1 匹配。发现库存已被修改、版本变化或存在相关新增订单时拒绝覆盖，等待人工处理。当前仓库开发库 `technologyagent_dev` 的 P01 业务 collection 均为空，未执行修正。

## 修改 fixture

修改 JSON 后必须重新生成 manifest：

```powershell
uv run python -m scripts.seed --write-manifest
uv run python -m scripts.seed --database technologyagent_test_p01_fixture_check
```

manifest 是 fixture 的派生校验，不是修复错误的替代品；inbound 对账与预警集合由测试独立断言。
