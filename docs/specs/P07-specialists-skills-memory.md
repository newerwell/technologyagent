# P07：专家分工、技能与跨会话偏好

状态：已有实现与历史offline/browser/live待审批记录；2026-10-25独立复核未关闭，发现8项P07缺口及前置残留，当前入口[P07补修](../implementation/P07-followup.md)。本轮常规回归通过不能替代新反例；原勾选记录实施状态，独立验收依据[P07审查](../reviews/2026-10-25-P07-review.md)。依赖：P06。目标：形成主 Agent + 采购分析专家 + 订单专家，支持可检查的技能与记忆，而不重写既有业务服务。

## 任务

- [x] **P07-T01 DeepAgents适配及版本路由。** 在 `agent/deepagent_adapter.py` 验证锁定版本的工具、检查点、中断、流式事件和子图行为；必要时用显式LangGraph子图实现兼容层。在`agent/graph_versions.py`保留v1、新增v2图，按持久化run.graph_version路由，旧待审批run继续由原图和checkpoint namespace恢复，新run才用v2；通过跨版本恢复及之前的审批/幂等/事件回归。
- [x] **P07-T02 专家声明与权限。** `agent/specialists/analyst.yaml`、`order.yaml` 声明目标、工具白名单、输入/输出schema。分析专家只读业务，允许图表/报告/analysis_execute；订单专家可准备草稿和调用审批后的MutationService；不能自行批准。
- [x] **P07-T03 委派协议。** 输入为 owner_id/run_id/task/data_scope/evidence_refs/preferences；输出为 status/summary/evidence_refs/artifact_ids/pending_interrupt/errors。owner从可信上下文注入，不由模型修改；传递审批中断到主UI；事件actor标识来源，预算计入父run。
- [x] **P07-T04 三个本地技能。** `skills/inventory-replenishment/`、`supplier-comparison/`、`procurement-report/` 各含SKILL.md、输入输出、规则引用和至少一个示例。按任务匹配加载，记录技能id/version/内容hash；不把所有文件全量塞进每次上下文。
- [x] **P07-T05 显式偏好Store。** 白名单key：default_warehouse、preferred_supplier、max_lead_days；用户明确说“记住”才保存；支持查看、修改、删除；本轮明确要求覆盖旧偏好；不得因偏好跳过报价有效性和确认。
- [x] **P07-T06 追踪与回归。** `tests/integration/test_specialists.py`、`test_skills_memory.py` 核对委派、权限、预算、同用户跨会话记忆和跨用户隔离；真模型完成“分析后准备订单”并记录P07 evidence。

## 验收（历史实施记录，当前未关闭项以独立审查为准）

| ID | 操作 | 通过条件 |
|---|---|---|
| P07-A01 | “分析补货需求，出报告，再准备订单” | 通过：真实模型由分析专家生成报告与证据，订单专家在原run创建待审批草稿；未发生订单写入 |
| P07-A02 | 让分析专家调用order_create | 通过：工具白名单拒绝，确定性权限回归保证无业务写入 |
| P07-A03 | 让订单专家绕过确认；专家递归委派 | 通过：审批/递归策略拒绝，父run预算共享且限次 |
| P07-A04 | 运行三类任务 | 通过：技能匹配、hash/版本和变更识别由离线回归覆盖 |
| P07-A05 | “记住默认W01”，重启并开新会话 | 通过：显式偏好跨会话保存、owner隔离、修改/删除由浏览器和集成回归覆盖 |
| P07-A06 | 默认W01但本轮指定W02 | 通过：显式本轮参数优先且不改写长期偏好；审批仍保留 |
| P07-A07 | 用P04/P05的v1图生成待审批run，升级启用v2后批准旧run，再开新run | 通过：真实Mongo集成测试恢复预升级v1审批并幂等批准一次；新run持久化路由到v2 |

## 本阶段结束后

覆盖参考项目的两类专家、技能文件和跨会话记忆。技能文件不等于向量RAG，偏好存储不等于微调；动态联网安装技能和自动推断用户偏好列为后续选做。

## 阶段 Git 交付

- [x] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [x] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [x] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p07` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [x] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
