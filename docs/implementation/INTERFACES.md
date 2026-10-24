# 实施接口映射

以下固定**应用自己的接口**，不冒充第三方库API。除同步纯函数外均async；Context从可信服务端注入，不出现在模型工具参数中。类型字段以共享契约为准，本文补方法名与调用关系。

## 1. 公共类型与基础能力

| 文件 | 类型/接口 | 定义要点 |
|---|---|---|
| contracts/common.py | RequestContext(owner_id,request_id,run_id=None,actor='main',call_id=None) | 冻结对象；子调用派生新上下文，不修改全局变量 |
| contracts/common.py | PageQuery(page=1,page_size=10)、Page[T]、Envelope[T]、AppError | Page字段records/total/page/page_size/pages；响应使用共享meta |
| contracts/common.py | Clock.now() -> datetime | UTC；测试FixedClock，业务不得分散datetime.now |
| repositories/mongo.py | MongoResources.open(settings)、close()、transaction() | transaction是async context manager，向仓储传session |
| bootstrap.py | build_container(settings) -> Container | 注入clock、repos、services、ports、executor；不把DB客户端放domain |
| config.py | load_settings(environ) -> Settings | 读取配置；本机端口和测试库规则按手册 |

Settings至少有APP_MODE、FRONTEND_PORT、API_PORT、MCP_PORT、MONGODB_URI、MONGODB_DATABASE、MODEL_MODE/BASE_URL/NAME/API_KEY、LOCAL_SESSION_SECRET、STORAGE_ROOT；模块数据源配置P08增加。日志过滤secret字段。

## 2. P01业务接口

contracts/domain.py定义InventoryQuery(warehouse_id?,part_name?,page,page_size)、ReplenishmentRequest(part_ids:list[str],warehouse_id:str,max_lead_days:int|None=None)、PreviewLine、PreviewResult、SourceRef(call_id?,entity,id,data_source,as_of)。PreviewLine含available/projected/shortage、candidate_quotes、recommended_quote_id、quantity、total_cents、actionable、missing_fields。

```python
# ports/catalog.py
class CatalogReader(Protocol):
    async def search_parts(self, name: str | None, page: PageQuery) -> Page[Part]: ...
    async def get_part(self, part_id: str) -> Part: ...
    async def search_suppliers(self, name: str | None, page: PageQuery) -> Page[Supplier]: ...
    async def get_supplier(self, supplier_id: str) -> Supplier: ...
    async def list_quotes(self, part_ids: list[str]) -> list[Quote]: ...

# ports/inventory.py
class InventoryReader(Protocol):
    async def page(self, query: InventoryQuery) -> Page[Inventory]: ...
    async def get(self, inventory_id: str) -> Inventory: ...
    async def list_scope(self, part_ids: list[str], warehouse_id: str) -> list[Inventory]: ...

# domain/replenishment.py：纯函数
def calculate_replenishment(inventory: Inventory, quotes: list[Quote],
    suppliers: list[Supplier], max_lead_days: int | None, now: datetime) -> PreviewLine: ...

# services/replenishment.py
async def preview(self, request: ReplenishmentRequest, ctx: RequestContext) -> PreviewResult: ...
```

仓储负责查询，服务负责拉齐物料/报价/供应商与scope，纯函数负责计算。max_lead_days过滤之后先按单价、交期、supplier_id排序。PreviewResult附所有依据和snapshot_versions，供P04绑定审批，不能只保留一段自然语言。

## 3. P02运行与事件接口

contracts/events.py定义EventEnvelope及共享type联合；contracts/agent.py从P02先定义ExecutorInput(run_id,thread_id,message,ctx)、ExecutionOutcome(status,summary,interrupt?)，P03增补模型类型。

```python
class RunService:
    async def create(self, thread_id: str | None, message: str,
        request_id: str, ctx: RequestContext) -> Run: ...
    async def get(self, run_id: str, ctx: RequestContext) -> RunView: ...
    async def append_event(self, run_id: str, kind: str, payload: dict,
        ctx: RequestContext) -> EventEnvelope: ...
    async def events(self, run_id: str, after_seq: int,
        ctx: RequestContext) -> list[EventEnvelope]: ...
    async def cancel(self, run_id: str, ctx: RequestContext) -> RunView: ...

class AgentExecutor(Protocol):
    async def execute(self, request: ExecutorInput, sink: EventSink,
        budget: RunBudget) -> ExecutionOutcome: ...
```

EventSink.emit(type,payload)委托RunService.append_event持久化，之后观察者读取事件；SSE路由不是执行器。run创建和thread.active_run_id认领必须在事务中完成；同(owner,request_id)唯一。append_event同一事务增加last_seq并插入事件，避免断档/重复seq；(run_id,seq)唯一。run终态与thread.active_run_id释放、最终消息和run_finished在事务内更新；不会因客户端断线释放执行锁。

AgentExecutor/EventSink Protocol放ports/executor.py；RunBudget实现放agent/budget.py。P02先提供取消检查/活跃deadline这些FakeAgent实际使用的能力，P03扩展charge_model/charge_tool原子计数，不让P02导入尚未存在的P03模块。

前端`applyEvent(state:ChatState,event:EventEnvelope):ChatState`为纯reducer；SSEParser.push(chunk:Uint8Array):EventEnvelope[]支持流式TextDecoder和跨chunk缓存；finish()拒绝不完整末帧并触发恢复查询，而非吞成成功。

## 4. P03工具、模型与预算

ToolSpec(name,input_schema,output_schema,effect,allowed_actors,capability,handler)、ToolResult(ok,data,error,meta,call_id)、ModelDelta(kind='token'|'tool_call'|'usage',payload)。模型工具调用ID映射到内部call_id，原始第三方响应仅留脱敏摘要。

```python
class ModelPort(Protocol):
    def stream(self, messages: list[ModelMessage], tools: list[ToolSpec],
        ctx: RequestContext) -> AsyncIterator[ModelDelta]: ...

class ToolRegistry:
    def available(self, ctx: RequestContext) -> list[ToolSpec]: ...
    async def invoke(self, name: str, arguments: dict,
        ctx: RequestContext, budget: RunBudget) -> ToolResult: ...

class RunBudget:
    async def charge_model(self) -> None: ...
    async def charge_tool(self) -> None: ...
    async def check_cancelled(self) -> None: ...
```

预算由run文档原子计数，不用每个专家各自的内存计数器；限制取共享契约。失败调用也计数。MCP受信身份使用每run短期opaque bearer token，服务端从sessions映射owner/run/actor/expiry；模型schema没有这些字段。MCP客户端按run维护独立session/header，禁止改共享全局headers造成用户串扰。默认运行在本机，服务令牌不作为公网身份方案。

## 5. P04草稿、审批与事务

contracts/order_workflow.py：DraftPrepareRequest(part_ids,warehouse_id?,supplier_id?,max_lead_days?,quantities)、DraftPatch(expected_version,items)、DraftPreparation(drafts,missing_fields)、ResumeRequest、OrderCreateRequest、WorkflowStartRequest。

```python
class DraftService:
    async def prepare(self, payload: DraftInput, ctx: RequestContext) -> DraftPreparation: ...
    async def patch(self, draft_id: str, expected_version: int,
        patch: DraftPatch, ctx: RequestContext) -> OrderDraft: ...

class ApprovalService:
    async def request(self, draft_id: str, ctx: RequestContext) -> Approval: ...
    async def resolve(self, run_id: str, request: ResumeRequest,
        ctx: RequestContext) -> ResumeResolution: ...

class MutationService:
    async def execute(self, draft_id: str, approval_id: str,
        idempotency_key: str, ctx: RequestContext) -> dict: ...

class ReconciliationService:
    async def reconcile(self, operation_id: str, ctx: RequestContext) -> dict: ...
```

新增services/approvals.py保存ApprovalService。request绑定run/owner/action/version/hash；resolve先验证再向同一检查点传Command。approve只作可信决定，不让模型自己造批准参数。MutationService在事务内再次验证决定与业务版本、真正消费审批；resolve不能提前消费以致崩溃后无法提交。

重要：幂等查原结果发生在检查审批已消费之前，合法重传可返回原订单；但先验证请求owner与payload hash，不能泄露他人订单或接受同key不同payload。订单明细与金额只能从服务端草稿读取。

P04补`OrderWriter.create_from_draft(draft,operation_id,session)`与InventoryRepository.adjust_inbound(inventory_id,delta,expected_version,session)。纯领域inbound变化从P04放domain/inventory.py，P08扩展收货与出库；避免P04先在路由手写另一套。草稿保存库存版本和全字段报价 hash；报价任一字段变化都要求重新确认。ReconciliationService只读对账，不自动补写。

## 6. P05–P09扩展接口

| 文件 | 签名 | 所属任务 |
|---|---|---|
| agent/review.py | deterministic_review(state:AgentStateV1)->ReviewResult | P05-T03 |
| agent/review.py | semantic_review(state,model,budget)->ReviewResult（async） | P05-T04 |
| ports/sandbox.py | execute(job:SandboxJob,ctx)->SandboxResult（async） | P06-T04 |
| services/artifacts.py | register(output:CollectedOutput,ctx)->Artifact；open(artifact_id,ctx)->ArtifactStream（async） | P06-T01 |
| sandbox/charts.py | build_chart_spec(kind,data,source_refs)->ChartSpec | P06-T02 |
| sandbox/reports.py | build_report_spec(format,analysis)->ReportSpec | P06-T03 |
| agent/graph_versions.py | resolve_graph(graph_version:str)->AgentExecutor | P07-T01 |
| agent/specialists/dispatcher.py | delegate(request:DelegationRequest,ctx,budget)->DelegationResult（async） | P07-T03 |
| agent/skill_loader.py | select_skills(task_type,actor)->list[LoadedSkill] | P07-T04 |
| services/preferences.py | get_effective(explicit,ctx)->EffectivePreferences；remember(key,value,ctx)（async） | P07-T05 |
| integrations/business_provider.py | capabilities()->ProviderCapabilities；组合既有ports | P08-T01 |
| services/inventory.py | receive(request:ReceiptInput,approval_id,key,ctx)->OperationResult（async） | P08-T04 |
| services/reconciliation.py | reconcile(operation_id,ctx)->OperationResult（async） | P04-T05、P08-T05 |
| services/recovery.py | recover_orphan_runs(now)->RecoverySummary（async） | P09-T02 |

SandboxJob含code/input_files/timeout/output_allowlist；SandboxResult含exit_code/timed_out/outputs/diagnostics；CollectedOutput只代表已收集且校验过的文件，不能直接传用户宿主路径。所有这些DTO在所属阶段contracts中定义，并由调用方共享，不在每个文件重复定义近似类。

AgentStateV1至少包括messages、run/thread/owner、graph_version、task_type、plan、phase、evidence_refs、review、revision_count、pending_interrupt、last_mutation_result。P03先定义用到的子集，P05增加字段给兼容默认值。P07封存完整v1图builder/state schema/node name，v2沿用外部ExecutionOutcome与事件契约。
