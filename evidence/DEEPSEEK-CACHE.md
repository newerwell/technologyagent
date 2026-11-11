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

## C01 缓存计量与 trace 契约

实现`cache_metrics.summarize_cache_events`，只将同`run_id + call_id`的成功起止事件配对；三个缓存字段必须是非负整数且`prompt_tokens = hit + miss`。缺字段归为missing，类型/非负/总量不一致归为invalid；重复相同事件去重；失败调用usage单列。`TraceService`在原`model.usage`旁增加`model.cache`，旧事件仍可读取。`model_started`新增可选模型名、模板ID和工具集ID；`model_finished.first_output_ms`从实际开始收流到首个token/tool-call计时，usage-only与无输出失败为null。

| 验收 | 命令 | 结果 |
|---|---|---|
| RED | `python -m pytest tests/unit/test_cache_metrics.py tests/unit/test_model_observation.py tests/unit/test_model_adapter.py tests/unit/test_event_contracts.py -q` | 19 failed / 37 passed；新字段与统计函数尚不存在 |
| GREEN | 同上 | 56 passed，exit 0；覆盖缺失、异常、bool/负数/浮点、零分母、重复事件、未配对事件、失败usage、首delta前重试、token/tool-call计时和MockTransport usage链路 |
| schema生成 | `python -m scripts.export_contracts` | exit 0 |
| schema核对 | `python -m scripts.export_contracts --check` | exit 0，contracts are up to date |
| Mongo trace集成 | `python -m pytest tests/integration/test_trace_summary.py::test_trace_summary_reports_cache_metrics_without_redefining_usage -q` | 未进入测试；系统Python缺少`pymongo`，exit 1。未写Mongo数据 |

本轮改用系统Python 3.12.7 / pytest 9.1.1。`uv`默认缓存目录ACL拒绝访问；改用项目内缓存后，锁文件所需的NumPy轮子不在离线缓存且网络不可用。现有`.venv`解释器启动未返回，无法复用。集成夹具导入阶段因缺依赖停止；虽本机Mongo端口在监听，仍没有声称Mongo集成通过。

## C02 固定授权工具定义

`_tools_payload`现在只规范化本次传入的授权工具：按`name`排序，递归排序JSON对象键并保持数组顺序；`toolset_id_for`对相同规范化payload计算`sha256:`摘要。没有缓存MCP发现、没有扩展工具白名单，也没有把owner、token或结果放进摘要。

| 验收 | 命令 | 结果 |
|---|---|---|
| RED | `python -m pytest tests/unit/test_model_adapter.py::test_authorized_tool_payload_and_toolset_id_ignore_discovery_order tests/unit/test_model_adapter.py::test_toolset_id_changes_with_schema_and_empty_toolset_is_stable -q` | 2 failed；发现顺序改变请求数组，且适配器尚无摘要方法 |
| GREEN | `python -m pytest tests/unit/test_model_adapter.py tests/unit/test_p07_specialists_skills.py::test_specialist_declarations_and_runtime_registry_enforce_both_directions -q` | 19 passed，exit 0 |
| 适配器与P07回归联合命令 | `python -m pytest tests/unit/test_model_adapter.py tests/unit/test_p07_specialists_skills.py -q` | 24 passed / 11 failed；11项在导入`pymongo`时被环境缺依赖阻断 |

受控真实 DeepSeek 协议探针未运行：本轮进程环境没有`MODEL_API_KEY`配置。本卡确定性序列化已验证，供应商侧缓存收益仍未知，不宣称命中率改善。

## C03 新 v2 run 的稳定提示前缀

新 v2 run 现在使用`ta-v2-base-1:<variant>`模板标识。基础采购规则保持第一条system；角色规则与按版本选取的技能保持在第二条system；可信结构化约束独立位于其后，用户请求再随后。分析报告使用独立`analyst_report`变体。核验事实仍是可信system内容并放在用户请求前，只在本次模型调用副本中加入；state中的静态消息不被改写。没有模板ID的旧v2状态继续使用旧的首条system事实注入。v1的提示构造函数和`versions/v1_impl.py`未改变。

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| RED | `python -m pytest tests/unit/test_prompt_layout.py -q` | 1 error；新模块尚不存在，符合预期 |
| GREEN | `python -m pytest tests/unit/test_prompt_layout.py -q` | 3 passed、1 skipped，exit 0；跳过项需导入`versions.v2_impl`，当前Python环境缺少`pymongo` |
| 定向离线回归 | `python -m pytest tests/unit/test_prompt_layout.py tests/unit/test_cache_metrics.py tests/unit/test_model_observation.py tests/unit/test_model_adapter.py tests/unit/test_event_contracts.py tests/unit/test_graph_answer_preservation.py -q` | 61 passed、1 skipped、2 failed；2项旧事实保留图测试在导入版本化订单模块时被缺少`pymongo`阻断 |
| 语义评审定向回归 | `python -m pytest tests/unit/test_semantic_review.py -q` | 8 passed、1 failed；最后一项现有测试导入`tests.unit.test_deterministic_review`失败（当前环境将`tests`解析到外部包）。新模板ID断言通过 |
| v2图节点/旧状态路径 | 测试已添加至`test_prompt_layout.py` | 本环境因缺`pymongo`跳过，未执行图节点断言 |
| 真实多消息/工具循环探针 | 检查进程配置后不发请求 | 未运行；没有`MODEL_API_KEY`，不验证DeepSeek对末尾/中间system消息的协议表现 |

协议探针缺失时按保守布局实施：核验事实维持可信system角色，并位于原始用户请求之前；未把事实降为普通用户文本或删去。合成提示单测覆盖静态前缀、动态约束、报告模板区分、消息顺序、事实完整性和副本不变性。Mongo/图版本/审批恢复回归仍须在项目依赖与Mongo replica set就绪后执行。

## C04 独立模型入口计量标识

C00历史数据中`semantic_review`有12个结束调用，但12个均为invalid缓存usage；旧事件没有足以区分模板与用途的字段，订单意图提取和订单说明修订没有可归因的调用样本。有效命中率、平均未命中token、冷暖差异与任务频率均无法从该批数据可靠计算。因此三个入口不重写已有固定system/动态user提示，不压缩证据或订单事实；只为未来trace分别增加模板标识：语义评审按已知rubric类型细分，订单意图提取与说明修订各有独立标识。原有purpose、预算、重试、工具约束、JSON与订单事实检查保持原样。

RED/GREEN核验：`test_semantic_review_reports_its_versioned_prompt_template`在实现前捕获`model_started.prompt_template_id=null`而失败；实现后同一断言通过（`python -m pytest tests/unit/test_semantic_review.py::test_semantic_review_reports_its_versioned_prompt_template -q`：1 passed）。订单入口对应断言加入现有单测，但这些测试模块导入`OrderWorkflowService`时因当前Python环境缺少`pymongo`而未进入收集，不能报告为通过。提示没有改写，故没有可声称的缓存性能提升。

## C05 对照与交付状态

代码和离线聚合证据已准备，真实DeepSeek冷/暖A/B、价格快照、任务结果、首输出延迟和有效usage覆盖仍未采集。当前基线为`baseline_insufficient`，本轮无API凭证且未发起任何真实或付费模型调用；计划要求的命中率提升至少10个百分点、输入费用下降及业务正确性门槛均未验证。缓存优化实现不等同于P09正式验收通过；不更新`docs/delivery/STATUS.md`，也不创建或复用`phase-p09`。
