# 扩展设计：预留边界与后续功能接入

这里的“冗余”指预留清晰接口、目录和兼容方式。未来功能在对应阶段实现，不提前创建不可运行的占位服务。第一版保持单仓库、模块化应用；暂不引入微服务、消息总线、插件市场或通用规则引擎。

## 1. 从一开始保留的扩展边界

| 边界 | 首次阶段 | 固定输入输出 | 以后怎么扩展 |
|---|---|---|---|
| 可信调用上下文 | P00 | owner_id、request_id；后续run_id/call_id | 新认证只替换身份解析，业务不读取前端user_id |
| 业务数据ports | P01 | Catalog/Inventory查询与共享实体 | P08增加ERP实现，通过bootstrap配置切换 |
| 补货策略 | P01 | ReplenishmentRequest → PreviewResult | 增加策略模块与规则测试，不在提示词里藏计算公式 |
| 模型端口 | P03 | messages、tools、limits → token/tool_call/usage | 添加供应商适配并跑工具调用能力探针 |
| 工具注册表 | P03 | ToolSpec(name,input/output schema,effect,allowed_actors,capability,handler) | 新工具声明+处理器+权限+契约测试，不修改聊天解析器 |
| 写入协调 | P04 | action、payload、approval、idempotency、可信owner → OperationResult | 新写操作接同一确认、幂等、对账入口 |
| 工作流状态 | P03/P05 | graph state、phase、review、版本 | 新任务类型增加配置/节点并保留旧图路由 |
| 产物/执行端口 | P06 | ArtifactRef；SandboxJob → SandboxResult | 新格式、新容器后端只实现各自适配，不改UI下载协议 |
| 专家/技能 | P07 | 结构化委派、工具白名单、证据引用 | 加专家和技能包，不让子Agent复制业务数据层 |
| 业务Provider | P08 | 多个业务ports + capabilities | 增加ERP厂商、快照模式，明确不支持能力 |

ToolSpec.effect固定为read/domain_write/artifact_write/sandbox_execute。domain_write必须走MutationService；不能通过将名称写成“查询”绕过策略。artifact_write与sandbox_execute仍有owner/run范围和资源限制。未配置能力不出现在模型可用工具中，同时ready说明不可用原因。

接口先以Protocol/结构化契约定义，当前只有一个实现时只实现这个版本，不提前写三个空适配器。domain规则保持纯函数，外部调用由ports注入，便于用假模型与HTTP模拟器独立验收。

## 2. 版本与数据演进

- 数据实体、事件、工具结果分别使用schema_version；改字段先定义默认值、迁移脚本、旧输入行为和回归样例。
- SSE只追加兼容字段时保持v1；新增事件前更新schema生成和前端reducer。旧前端遇到未知事件记录并忽略，不因此把任务标成功；未知schema_version明确提示升级。
- core业务字段使用具名强类型。供应商自定义字段如有真实需求放`extensions[provider]`，只作补充展示；不能把金额、状态或库存塞入无类型metadata。
- thread_id与run_id独立，消息历史与checkpoint独立。v1待审批运行继续使用v1图，新run使用v2；不把框架升级当作可无损加载旧检查点的保证。
- 数据库索引、字段迁移、回滚/恢复方案都随阶段提交；测试使用独立库，不对用户日常数据执行重置。

## 3. 后续常见功能的接入位置

| 新需求 | 主要新文件/目录 | 复用内容 | 新增验收 |
|---|---|---|---|
| 换模型供应商 | integrations/models/<provider>.py | ModelPort、工具schema、预算和事件 | 流式、tool call、错误与usage探针 |
| 新ERP厂商 | integrations/erp_<vendor>/ | 业务ports、MutationService、幂等/对账 | 字段/金额/状态/分页/写入未知结果 |
| 需求预测补货 | domain/forecasting.py、services/forecasting.py | 库存ports、预览输出、数据证据 | 历史不足行为、回测范围、与固定规则对照 |
| 采购文档RAG | integrations/retrieval/、services/knowledge.py | ToolSpec、source_refs、artifact授权 | 证据引用、无答案、权限、索引版本 |
| Excel/PDF报告 | sandbox/exporters/ | ArtifactPort、下载UI、沙箱限制 | 文件可解析、金额一致、视觉检查 |
| 邮件/飞书提醒 | integrations/notifications/、services/notifications.py | 订单事件、可信owner、幂等 | 明确发送授权、去重、失败重试与投递结果 |
| 新专家 | agent/specialists/<name>.yaml | 委派协议、预算、白名单、trace | 中断传递、权限和父run调用计数 |
| 多组织/角色 | contracts/identity.py、api身份解析、ports/repositories作用域 | owner上下文和应用服务边界 | tenant字段迁移、复合索引、全链路隔离 |
| 定时任务 | services/scheduling.py、独立worker入口 | 相同run/mutation/预算协议 | 任务重复触发、取消、重启恢复、授权有效期 |

多组织、对外部署、通知和RAG不在P00–P09的承诺范围内。列出接入点不表示已经授权外发消息、创建定时任务或部署公网服务。

## 4. 新功能的固定落地步骤

1. 确定所属阶段/增量版本，补目标、非目标、输入输出、失败情况及验收。
2. 在本蓝图登记文件归属；跨边界功能先更新ports/contracts，业务规则只放一处。
3. 实现所需最小功能；为核心规则、未知边界和外部适配补相称测试。
4. 接入现有注册表/装配入口，完成真实可操作用例，更新模块README。
5. 更新证据和状态，按Git交付规则提交、推送并核对远程。

只有依赖方向、数据契约、状态语义或外部契约发生变化时才需要ADR；日常小改动不强制新增决策文档。
