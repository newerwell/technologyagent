# P07 专家声明与委派

## 职责

`analyst.yaml`声明只读采购分析及分析产物能力；`order.yaml`声明订单查询/草稿/审批工作流能力。声明包含任务目标、工具与技能白名单、输入/输出Schema，并明确禁止递归和专家自批。`policy.py`启动时拒绝未知工具、非法schema或不安全声明；`RoleToolRegistry`在列出工具和实际调用时都按actor及白名单拒绝越权。

`SpecialistDispatcher`从可信调用上下文构造`DelegationRequest`，限制每个父run最多两次委派，且传入同一个`RunBudget`。父run的owner、run id与parent_call_id不采纳模型改写。`evidence_refs`保留字段、来源和原始数值类型，供后续专家继续核对。

## 使用与权限

`graph_versions.route_executor`先解析偏好命令、分析、订单查询、订单准备和否定范围。聊天明确“记住”才写入同一owner的`PreferenceService`；分析读取已存默认仓库，本轮字段优先并同时约束工具参数与评审。纯订单直接进入订单工作流，不创建空分析委派；查询只在order actor下调用`order_page`/`order_get`，不创建草稿或审批。组合任务把分析专家结构化证据交给订单专家。

订单意图抽取支持全部明确物料ID、仓库、供应商和交期；物料经可信目录重新查询，停用或不存在的物料拒绝，多物料缺项拒绝。订单专家通过既有`OrderWorkflowService`准备草稿；只有原run中的人工审批恢复流程才能触发`MutationService`。取消、deadline和budget limit作为控制异常保留，不改写成普通专家失败。

`analysis_execute`只对v2 analyst actor开放；main、order和v1工具策略不会因本阶段扩大。v1状态schema、节点名与checkpoint namespace固定在`agent/versions/v1.py`；稳定业务服务仍共享。

订单意图的物料ID来自用户原始请求并经目录逐一核验；组合分析证据用于衔接，不是直接订单的强制前置。最终回答会从同一实体/范围的结构化证据构造事实核心，保留真实单位，并在引用比较报价前绑定部件与供应商；模型生成的总额、单位或来源不能替代服务端事实。真实live验收必须单独记录真实调用和数据库快照；仅停在`waiting_input`不等于live订单写入验收。

```python
outcome = await dispatcher.dispatch(
    owner_id=ctx.owner_id, run_id=ctx.run_id, specialist="analyst",
    task="分析W01补货需求", data_scope={"warehouse_id": "W01"},
    evidence_refs=[], preferences={}, parent_call_id="delegate_run_analyst",
    budget=parent_budget, invoke=invoke_specialist,
)
```

## 错误与限制

- 超过两次返回`DELEGATION_LIMIT`；递归返回`DELEGATION_RECURSION`。
- 专家不能互相更改actor、owner或run身份，也没有自批能力。
- DeepAgents锁定版本的工厂默认包含宿主文件/执行能力且不能保留本项目ModelPort、事件与中断契约；适配器因此使用LangGraph具名子图，不创建不受控DeepAgents工具集。
- 专家输入Schema只描述稳定协议；运行时请求/结果另由严格Pydantic契约校验。新旧图依据持久graph_version路由。

## 验证

`uv run pytest tests/unit/test_p07_specialists_skills.py tests/integration/test_graph_upgrade.py tests/integration/test_specialists.py -q`
