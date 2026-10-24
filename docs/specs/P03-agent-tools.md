# P03：真实模型、MCP 与只读业务助手

状态：实现已推送 02a6e5c；本轮 offline 9/9、browser 6 E2E 通过，独立审查发现 9 项缺口，先执行 [P03 补修计划](../implementation/P03-followup.md)。**不只缺Key：流协议、事实校验和验收器也待修；live not_run，P03-A06 未满足，phase-p03 未创建。** 依赖：P02。目标：用户用自然语言查询库存、比较报价，结果由真实工具数据支撑。

下列勾选保留原实现交付记录，不表示 [审查 R01–R09](../reviews/2026-10-24-P03-review.md) 已关闭。

## 任务

- [x] **P03-T01 模型适配器。** `integrations/model.py` 提供统一流式与工具调用接口，支持 fake/live；从配置读取 base_url/model/key；校验供应商工具调用与流式能力。将模型请求耗时、usage 是否可用写日志，不泄露 Key。
- [x] **P03-T02 首批 MCP 工具。** `mcp_server/server.py` 注册 CONTRACTS 九个只读工具，复用 P01 服务；输入 schema 清晰、错误结构一致；`integrations/mcp.py` 发现工具并转换为模型工具，验证所选传输。
- [x] **P03-T03 单 Agent 工具循环。** `agent/graph.py` 使用 LangGraph 组织 model → tool → model，注册白名单只读工具；绑定owner/run/call上下文，Run记录graph_version=v1；启用共享模型/工具次数及超时限制，未知工具和非法参数可解释失败。
- [x] **P03-T04 接入流式 UI。** 替换 FakeAgent，映射真实 token、tool_started/finished，tool card 中显示参数摘要、数据源和实际结果；普通问候无需查库，库存数量类问题必须查工具。
- [x] **P03-T05 数据依据。** `agent/evidence.py` 为结论保存工具 call_id 和业务 record_id；响应明确范围与时间，不把缺失报价补成数字，不从前一会话偷用数据。
- [ ] **P03-T06 双层评测。** `tests/integration/test_agent_tools.py` 使用脚本模型验证工具选择与错误链路；`tests/live/test_readonly_agent.py` 在显式 live 模式下执行固定问题，记录真实 call trace 与数据库对照。

## 验收

| ID | 用户输入/故障 | 通过条件 |
|---|---|---|
| P03-A01 | “哪些零件要补货？只看W01。” | 实际调用库存/补货工具；范围正确，P001缺口55 |
| P03-A02 | “刹车片要求7天内到货，推荐哪家？” | 获取报价/预览，推荐S01并给出5天、55件、660.00元 |
| P03-A03 | “P003买哪家的最便宜？” | 明确无有效报价，不编造供应商与金额 |
| P03-A04 | “直接帮我下单” | 当前只读版本明确不可执行，不声称订单已创建 |
| P03-A05 | MCP断线、工具超时、模型返回非法工具参数 | 工具显示失败，无伪成功；限定次数内停止并说明未完成项 |
| P03-A06 | 真模型执行前三个问题各3次 | **not_run**：未配置真实模型 Key；脚本模型/MCP 数据不能替代 9 次轨迹 |

P03 offline/browser 实际结果：37 unit、86 integration、23 frontend、6 E2E；MCP 9 工具真实进程测试通过。证据见 [evidence/P03.md](../../evidence/P03.md)。

## 本阶段结束后

完成补修与真实验收后，才可确认“真实模型 → MCP → 本地业务 → 页面回答”可演示，尚无订单写入。离线脚本通过不能代替 P03-A06 的真实模型验收。

## 阶段 Git 交付

- [ ] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [ ] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [ ] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p03` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [ ] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
