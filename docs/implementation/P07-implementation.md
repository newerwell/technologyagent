# P07 专家、技能与记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**2026-10-25独立复核：** 实现及phase-p07→307edb4已交付；本轮8项P07缺口与前置残留见[P07审查](../reviews/2026-10-25-P07-review.md)，当前执行[P07补修计划](./P07-followup.md)。下方保留最初任务清单，不能仅凭spec全勾选宣称独立验收关闭，不开始P08。

**Goal:** 分析/订单专家共享业务服务与父预算，按需加载技能，并保存用户显式偏好。
**Architecture:** 新run用v2，旧run保持原v1图；专家是受约束子任务，不另起一套身份、批准或数据层。
**Tech Stack:** 锁定DeepAgents适配或具名LangGraph子图；Mongo偏好Store。
**Spec:** [P07](../specs/P07-specialists-skills-memory.md)、图升级和委派接口。

## Global Constraints

最多2次委派、不递归；父子共享模型/工具20/30上限；分析专家无业务写工具，订单专家不能自批；显式记住才持久化；不强行迁移旧checkpoint。

## Review Focus

旧审批升级后失效→T01；专家工具越界→T02；子调用漏计预算/中断丢失→T03；技能全量注入与无版本→T04；偏好跨用户/覆盖本轮→T05。

### P07-T01：封存v1并建立v2适配

**Files:** Create `agent/graph_versions.py`、`agent/versions/v1.py`、`agent/deepagent_adapter.py`、`tests/compatibility/test_graph_upgrade.py`；Modify graph入口。
**Interfaces:** resolve_graph(version)->AgentExecutor；Run持久graph_version，checkpoint namespace按版本分离。

- [ ] 在改图之前，用P06的实际v1 graph保存待审批检查点；该测试不能升级后才用新版代码重造所谓旧图。
- [ ] 封存v1 builder、状态schema、node names和依赖工厂；graph.py作为路由，不删除旧节点。新run默认v2，旧run恢复必须用记录的版本。
- [ ] DeepAgents只在adapter内封装内部事件/中断差异，外部EventSink/ExecutionOutcome不变；不兼容时用显式子图并记录ADR，不能牺牲审批规则换框架外观。
- [ ] 运行真实旧checkpoint恢复→批准→唯一订单，再新建run断言v2；P04/P05回归通过后继续。

### P07-T02：专家声明与工具范围

**Files:** Create `agent/specialists/{analyst,order}.yaml`、`contracts/delegation.py`；Modify registry/adapter；Test `tests/unit/test_specialist_policy.py`。
**Interfaces:** SpecialistSpec(name,objective,tools,skills,output_schema)；allowed_actors在Registry运行时也校验，不只靠模型可见列表。

- [ ] 分析专家只读业务+绘图/报告/analysis_execute；P06的main执行权限在v2收紧。旧v1运行保持原策略以维持升级兼容。
- [ ] 订单专家prepare/查询/请求批准，创建和变更最终仍走MutationService；无生成批准token能力。
- [ ] YAML启动时校验未知工具/循环委派配置，失败则该专家不可用并显式ready，而非悄悄放开全部工具。
- [ ] 测试analysis调用order_create被拒且DB不变；order请求sandbox_execute被拒；不能仅检查工具名称清单。

### P07-T03：结构化委派与中断透传

**Files:** Create `agent/specialists/dispatcher.py`、`tests/integration/test_specialists.py`；Modify graph/trace。
**Interfaces:** DelegationRequest与DelegationResult见映射；输入owner/run来自ctx，子任务只有限定data_scope和evidence_refs。

- [ ] 主Agent按任务先委派分析，返回证据/产物，再将结构化结果传订单专家，避免把整段聊天当唯一输入。
- [ ] 子调用带parent_call_id/actor，使用同RunBudget；第三次委派与递归直接拒绝，不重置计数。
- [ ] 专家内interrupt进入父run同一UI；resume路由回原子图和节点，不能让主Agent另造新草稿代替恢复。
- [ ] scripted集成验证分析→订单→确认；预算耗尽、专家失败、缺数据分别准确返回，不把子任务异常吞为成功。

### P07-T04：三个技能包

**Files:** Create `skills/{inventory-replenishment,supplier-comparison,procurement-report}/SKILL.md`及examples；Create `agent/skill_loader.py`、`tests/unit/test_skill_loader.py`。
**Interfaces:** LoadedSkill(id,version,hash,instructions,examples)；select_skills(task_type,actor)只返回需要的技能。

- [ ] 每技能写目标、何时用/不用、明确输入输出、调用规则、固定案例与缺信息行为；引用业务函数规则，不在SKILL中复制另一套可变计算实现。
- [ ] loader校验本地固定根目录、frontmatter版本，计算内容hash；输入不能穿越到其他文件，P07不支持联网安装。
- [ ] inventory/order/report任务各断言加载匹配集合，修改内容hash变化；不把所有技能全文每轮灌进上下文。
- [ ] 保存run中的skill版本/hash，完成能回溯哪些说明影响结果；跑loader测试。

### P07-T05：显式偏好与覆盖顺序

**Files:** Create `ports/preferences.py`、`repositories/preferences.py`、`services/preferences.py`、`api/preferences.py`、`frontend/src/app/preferences/page.tsx`；Test `tests/integration/test_preferences.py`。
**Interfaces:** 仅default_warehouse/preferred_supplier/max_lead_days；remember/get_effective/delete按owner；键值校验对应业务存在性。

- [ ] “默认仓库W01”只有明确要求记住才持久化；普通本轮指定W02不改长期记录，source=explicit_user。
- [ ] 优先级：本轮明确字段 > 同owner偏好 > 缺失并请求补充；偏好不能把停用供应商或过期报价变有效。
- [ ] 测试重启+新会话同用户有效，B用户无A偏好，删后失效；页面能查看/编辑/重置，不隐藏自动推断记忆。
- [ ] 执行preferences测试和前端检查；记录Store与checkpoint/消息历史的不同责任。

### P07-T06：真实组合场景与交付

**Files:** Create `tests/live/test_specialist_flow.py`、`evidence/P07.md`；Update验证manifest与v1退役条件说明。
**Interfaces:** 原run同图版本恢复，新run有两类专家事件、skill hash和共享预算。

- [ ] 真模型执行“分析补货→报告→准备订单→等待确认”，确认执行唯一订单并能追踪委派证据。
- [ ] 覆盖P07-A01..A07，尤其旧checkpoint实际升级测试和专家中断恢复；不只验证新图自己保存/恢复。
- [ ] 更新专家/skills/preferences/adapter的中文README，说明限制与锁定兼容版本。
- [ ] 上传并核对`phase-p07`，保留v1直到旧run结束且备份条件满足，停止。
