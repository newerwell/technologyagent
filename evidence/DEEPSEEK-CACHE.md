# DeepSeek 输入缓存优化证据

status: baseline_insufficient
source_sha: `6e8576c12fb126c40f10ccdb53c671aed6b62758`
sampled_at: `2026-11-11`（本地 UTC+8）
model_mode: live（仅历史隔离证据；本次没有调用模型）
data_source: `evidence/P09/live` 的历史隔离 trace 聚合

## 改动前基线

当前可读取的隔离 live trace 来自 2026-10-26 02:54:19–05:19:27 UTC。统计时排除旧 F11 样本；跨文件按唯一 `call_id` 去重。没有复制原始事件，只记录聚合数字。

| purpose | calls | valid | missing | invalid | hit | miss | known hit rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| `agent_step` | 90 | 55 | 0 | 35 | 413,696 | 363,304 | 53.24% |
| `semantic_review` | 12 | 0 | 0 | 12 | 0 | 0 | unknown |
| `unknown` | 102 | 55 | 0 | 47 | 420,096 | 398,908 | 51.29% |
| **合计** | **204** | **110** | **0** | **94** | **833,792** | **762,212** | **52.24%** |

204 个唯一结束调用均能配对到开始事件，状态均为 `success`。94 个 invalid 调用的三个缓存计数字段不是非负整数；未将其纳入分子或分母。7 个隔离证据文件中同一调用平均重复出现于副本/包装文件，未按文件行数重复计数。

这不是可用于验收的当前基线：事件中缺少 `model_name`、`graph_version`、模板版本和工具集标识；102/204 个调用缺少 `purpose`；样本没有冷/暖标记，也无法按当前任务族与模板划分。当前进程未配置 `MODEL_NAME`、`MODEL_BASE_URL`、`MODEL_API_KEY` 环境变量。本轮没有访问 `.env` 或发起付费调用。因此结果只作历史诊断，整体状态保持 `baseline_insufficient`，不据此宣称任何优化收益。

## 前缀差异定位

- 主图 `build_specialist_system_prompt` 将专家规则、按任务加载的技能和本轮结构化约束拼入同一条 `system`；请求变化会改变较早的消息字节。
- v1 与 v2 的模型节点在每轮调用时将核验事实追加到首条 `system`，使后续工具轮次的前缀随运行时结果变化。
- `integrations/model.py::_tools_payload` 按授权 registry 的传入顺序输出工具，且没有递归规范化 schema 对象键；MCP 发现顺序可能改变请求体。
- 工具结果携带本轮 call ID、完整业务数据、错误和 meta，是动态后缀。没有证据支持截断或缓存它们，本计划不改变这些内容。
- 独立评审与订单入口采用固定 `system` + 动态 `user` 的形状；现有历史 trace 无法证明它们有值得前移的动态前缀。

以上是代码差异定位，不代表供应商缓存命中归因。历史 F11 样本没有并入本表。

## 本卡验证

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 项目状态 | 读取 `docs/delivery/STATUS.md` | P09 N00–N06 已完成，N07 起尚未运行；本功能保持独立，不更新 P09 验收状态 |
| 历史样本 | 只读扫描隔离 JSON，按 `call_id` 聚合 | 204 calls；110 valid、94 invalid、0 missing；未写出原始事件 |
| 缓存配置 | 检查进程环境中 `MODEL_NAME`、`MODEL_BASE_URL`、`MODEL_API_KEY` 是否存在 | 均不存在；没有读取 `.env` |
| 前缀来源 | 检查 `graph.py`、`versions/v2_impl.py`、`integrations/model.py` | 找到动态系统消息、每轮事实改写及未规范化工具顺序 |
| 代码基线 | `python -m pytest tests/unit/test_model_observation.py tests/unit/test_model_adapter.py tests/unit/test_event_contracts.py -q` | 38 passed；Python 3.12.7 / pytest 9.1.1 |

## 未运行

- 没有当前同模型、同任务族的冷/暖 trace，故未冻结可比暖请求基线。
- 没有真实 DeepSeek 协议探针或 A/B；需要单独记录真实 usage、费率时间窗、延迟和任务结果。
- P09 最终 offline/live/browser、干净检出恢复及环境恢复仍未完成；本证据不改变这些状态。
