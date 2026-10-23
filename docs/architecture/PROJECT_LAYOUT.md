# 整体文件布局与阶段归属

状态：工程蓝图。目录树中除文档和.gitignore外均为**未来计划路径**，不表示代码已经存在。先确定全局分工，每阶段只创建实际用到的模块；空目录不用于宣称完成。

## 1. 总体原则

采用单仓库：一个前端、一个Python业务代码包、一个MCP入口、一个数据库。FastAPI与MCP是两个接入方式，调用相同应用服务；业务规则不复制。后端核心不依赖Next.js、MCP或模型供应商，便于更换交互和外部系统。

以现有阶段spec中的`frontend/`、`backend/app/`、`mcp_server/`为稳定根，不在后续阶段改成另一套apps/packages结构。新功能按下面的职责归属加入，不依赖无限增长的main.py或通用utils.py。

## 2. 全量计划文件树

括号是首次交付阶段；`README.md`跟随模块首次实现。以后同模块扩展时更新原说明。

```text
technologyagent/
├─ AGENTS.md                         已建立：项目规则
├─ README.md                         已建立：入口与实际状态
├─ .gitignore                        已建立：密钥、依赖、运行文件排除
├─ .env.example                      P00：无密钥配置样例
├─ compose.yaml                      P00：Mongo单节点replica set
├─ pyproject.toml                    P00：Python包、测试与检查配置
├─ uv.lock                           P00：选定uv后生成的Python锁文件
├─ start.ps1 / stop.ps1               P00：本机启停入口
├─ frontend/
│  ├─ package.json / package-lock.json P00：前端依赖与命令
│  ├─ next.config.ts                 P00：同源/api转发
│  └─ src/
│     ├─ app/
│     │  ├─ layout.tsx / page.tsx     P00：应用布局与主页
│     │  ├─ globals.css              P00：全局样式及基础设计变量
│     │  ├─ data/page.tsx            P01：业务数据浏览
│     │  ├─ orders/page.tsx          P04：订单查询
│     │  └─ preferences/page.tsx     P07：显式偏好管理
│     ├─ components/
│     │  ├─ common/                 P00：状态、加载、错误等基础组件
│     │  ├─ data/                   P01：库存、供应商、报价、补货表格
│     │  ├─ chat/                   P02：消息、输入、工具卡片
│     │  ├─ sidebar/                P02：会话列表与搜索
│     │  ├─ approval/               P04：确认卡片与字段补充
│     │  ├─ workflow/               P05：阶段、计划、评审面板
│     │  └─ artifacts/              P06：图表预览、报告下载
│     ├─ hooks/
│     │  ├─ useChat.ts / useSSE.ts   P02：运行状态与流生命周期
│     │  └─ useHistory.ts           P02：历史加载与选择
│     ├─ lib/
│     │  ├─ api.ts                  P00：统一请求与错误处理
│     │  ├─ domain-types.ts         P01：生成的业务类型
│     │  ├─ events.ts               P02：生成的事件类型
│     │  ├─ sse-parser.ts           P02：字节流与事件解析
│     │  └─ event-reducer.ts        P02：去重、状态更新
│     └─ tests/                     对应阶段：前端单元/解析测试
├─ backend/
│  ├─ README.md                      P00：后端入口、环境和调用链
│  └─ app/
│     ├─ main.py                    P00：只组装应用与路由
│     ├─ config.py                  P00：配置加载和校验
│     ├─ bootstrap.py               P00：依赖组装、启停，不写业务
│     ├─ api/
│     │  ├─ health.py / session.py   P00：健康和本地身份
│     │  ├─ dependencies.py         P00：可信上下文、服务注入
│     │  ├─ catalog.py              P01：供应商/零件/报价查询
│     │  ├─ inventory.py            P01：库存和补货预览
│     │  ├─ chat.py / history.py    P02：流、历史、重放
│     │  ├─ runs.py                 P02：运行状态与取消，P04增加resume
│     │  ├─ drafts.py / orders.py   P04：草稿、确认、订单读取
│     │  ├─ artifacts.py            P06：产物授权下载
│     │  └─ preferences.py          P07：偏好管理
│     ├─ contracts/
│     │  ├─ common.py               P00：响应、错误、上下文
│     │  ├─ domain.py               P01：实体与业务请求
│     │  ├─ events.py               P02：事件schema与版本
│     │  ├─ agent.py                P03：工具与模型结果
│     │  ├─ approval.py             P04：审批、草稿、幂等请求
│     │  ├─ artifacts.py            P06：文件与图表输入输出
│     │  └─ delegation.py           P07：专家委派输入输出
│     ├─ ports/                     P01起：外部能力接口，不含实现
│     │  ├─ catalog.py / inventory.py P01：业务数据读取接口
│     │  ├─ model.py / tools.py     P03：模型与工具执行接口
│     │  ├─ orders.py               P04：本地/远程订单业务能力
│     │  ├─ artifacts.py / sandbox.py P06：产物和隔离执行能力
│     │  └─ preferences.py          P07：偏好存取接口
│     ├─ domain/
│     │  ├─ money.py                P01：整数分、行金额和总额
│     │  ├─ replenishment.py        P01：缺口、报价过滤与推荐
│     │  ├─ orders.py               P04：订单与版本规则
│     │  └─ inventory.py            P04：在途量规则；P08扩展收发货
│     ├─ repositories/
│     │  ├─ mongo.py / indexes.py   P00：连接、事务与索引
│     │  ├─ catalog.py / inventory.py P01：本地业务数据
│     │  ├─ runs.py / messages.py   P02：运行、事件与展示消息
│     │  ├─ drafts.py / orders.py   P04：草稿和订单持久化
│     │  ├─ operations.py          P04：审批、认领、幂等结果
│     │  ├─ artifacts.py           P06：产物元数据
│     │  ├─ preferences.py         P07：显式偏好
│     │  └─ movements.py           P08：收货单与库存流水
│     ├─ services/
│     │  ├─ catalog.py / replenishment.py P01：查询与补货用例
│     │  ├─ runs.py / chat.py      P02：调度、持久化和取消
│     │  ├─ drafts.py / mutations.py P04：草稿、审批与写入统一入口
│     │  ├─ approvals.py           P04：可信确认与中断恢复校验
│     │  ├─ reconciliation.py      P04：已提交/未知结果核对
│     │  ├─ artifacts.py           P06：产物登记、读取和授权
│     │  ├─ preferences.py         P07：显式偏好的使用规则
│     │  ├─ inventory.py           P08：收发货事务与订单对账
│     │  └─ tracing.py / recovery.py P09：运行追踪与恢复协调
│     ├─ agent/
│     │  ├─ graph.py / state.py    P03：单Agent工具循环与状态
│     │  ├─ tool_registry.py       P03：工具声明、执行、权限元数据
│     │  ├─ evidence.py           P03：结论和实际数据引用
│     │  ├─ checkpoints.py        P04：持久检查点
│     │  ├─ order_nodes.py        P04：补充、展示、确认、提交
│     │  ├─ harness.py / review.py P05：工作阶段与结果检查
│     │  ├─ rubrics.yaml          P05：任务类型评审规则
│     │  ├─ graph_versions.py     P07：v1/v2运行版本路由
│     │  ├─ deepagent_adapter.py  P07：框架差异封装
│     │  ├─ specialists/          P07：分析、订单专家配置
│     │  └─ skill_loader.py       P07：技能选择、版本、hash
│     ├─ integrations/
│     │  ├─ model.py              P03：可配置模型供应商适配
│     │  ├─ mcp.py                P03：MCP客户端与协议适配
│     │  ├─ business_provider.py  P08：组合ports及能力声明
│     │  ├─ local_provider.py     P08：本地服务的Provider封装
│     │  ├─ erp_provider.py       P08：ERP业务适配
│     │  └─ erp/client.py / mappings.py P08：HTTP和字段转换
│     ├─ sandbox/
│     │  ├─ runner.py / Dockerfile P06：容器执行生命周期
│     │  ├─ charts.py / reports.py P06：固定绘图与报告
│     │  └─ collectors.py         P06：输出限制与产物收集
│     └─ skills/                  P07：三个本地采购技能包
├─ mcp_server/
│  ├─ server.py                    P03：独立MCP入口
│  └─ tools/{catalog,inventory,orders}.py P03起：声明/鉴权/转发
├─ fixtures/v1/                    P01：合成数据、manifest、固定时钟
├─ tests/
│  ├─ unit/                        P01起：确定性业务规则
│  ├─ integration/                 P00起：数据库、HTTP、MCP、运行恢复
│  ├─ e2e/                         P02起：浏览器完整交互
│  ├─ live/                        P03起：真实模型/ERP，显式启用
│  └─ compatibility/               P07：旧运行升级后恢复
├─ scripts/
│  ├─ check_compatibility.py       P00：实际依赖接口探针
│  ├─ init_db.py                   P00：replica set/索引初始化
│  ├─ seed.py                      P01：幂等合成数据初始化
│  ├─ export_contracts.py          P01起：schema和前端类型生成
│  ├─ verify_stage.py             P00：按阶段运行已有检查
│  └─ backup.ps1 / restore.ps1     P09：显式目标备份恢复
├─ evidence/P00.md … P09.md        对应阶段：真实执行证据
├─ docs/
│  ├─ architecture/                已建立：结构与扩展约束
│  ├─ specs/                       已建立：共享契约和P00–P09
│  ├─ delivery/                    已建立：推送规则与状态
│  ├─ implementation/              已建立：其他Agent逐阶段实施手册
│  ├─ decisions/                   有重要变更时：ADR决策记录
│  └─ erp-mapping.md               P08：实测外部接口映射
└─ .github/workflows/ci.yml        P00：已可执行的离线检查
```

Python以`backend.app`为统一导入路径，通过pyproject安装本地包，使MCP入口不依赖当前工作目录；不用手工修改sys.path。`uv.lock`为本设计默认工具选择，P00如因环境改用其他锁工具，应先记录ADR并同步启动/CI命令，始终只维护一套Python锁定来源。

## 3. 依赖方向

```text
UI → HTTP/SSE → api → services → domain
                       ↓         ↓
                     ports ← contracts
                       ↑
              repositories / integrations

MCP入口 → tools声明 → 同一services
Agent → 受控tool_registry → MCP或应用服务
bootstrap → 组装全部依赖（仅此处知道具体实现）
```

services调用ports，不直接创建HTTP客户端或MongoClient；repositories实现本地端口，integrations实现外部端口。P08 Provider是这些端口的组合适配，不创建第二套业务公式。写入统一经过MutationService；本地事务协调和ERP远程请求分别实现，不能把远程HTTP放进MongoDB事务假装原子提交。

domain只导入标准库和纯业务类型，不导入FastAPI、LangGraph、MongoDB、Docker。contracts可用Pydantic验证数据，但不得导入外部客户端。main.py/bootstrap.py只负责装配，不能成为全部功能汇集处。

## 4. 阶段实施时必须同步的文件

| 阶段 | 新建重点 | 需要扩展的稳定入口 |
|---|---|---|
| P00 | 基础前后端、DB、CI、配置、启停 | 根README、布局、STATUS、evidence/P00 |
| P01 | 业务契约/ports/domain/repository/service/API/数据页 | bootstrap、API路由、生成类型与种子 |
| P02 | Run/Event/Message、SSE、history、chat UI | bootstrap、主页、事件schema |
| P03 | Model/MCP、graph、tool registry、真实工具 | chat执行器、配置、ready能力状态 |
| P04 | 草稿/审批/订单/幂等/检查点 | run.resume、mutation入口、审批UI |
| P05 | Harness、rubric、review UI | graph状态、phase/plan/review事件 |
| P06 | 容器、图表、报告、产物下载 | registry、ready、artifacts UI、依赖镜像 |
| P07 | 专家、skills、preferences、graph版本路由 | registry权限、可信上下文、trace actor |
| P08 | 完整业务/Provider/ERP/库存流水 | ports、API/MCP注册、字段映射与配置 |
| P09 | 追踪/恢复/交付/备份 | 启停、CI、操作手册、最终验收 |

每阶段交付完整用例所需的前后端、测试、模块README和证据，不分成“先把所有后端写完、最后再接UI”的路线。

详细任务的具体辅助文件以`docs/implementation/`为补充：P00服务会话services/sessions.py、P02执行器ports/executor.py与fake_executor.py/budget.py、P05 contracts/workflow.py、P06 agent/tools/analysis.py、P07 agent/versions/v1.py与specialists/dispatcher.py、P09 api/diagnostics.py。这些文件归属对应层，不改变目录边界；需要额外拆私有文件时更新本蓝图。
