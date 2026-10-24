# 可复制给实施 Agent 的提示词

用户在另一个Agent/工具中自行粘贴。本文件不会自动发消息、调用Agent或开始实现。建议每次只交付一个阶段，避免上下文过长后跳过验收。

当前入口更新（2026-10-24）：P00 两项与 P01 四类补修已复核关闭；P02 六项并发问题待修。下一实施 Agent 先复制 [P02 补修计划](./P02-followup.md)文末提示词，不开始 P03。历史阶段提示词保留，当前状态以 STATUS 和审查报告为准。

## 第一次：执行 P00

```text
你是TechnologyAgent的实施Agent。请在https://github.com/newerwell/technologyagent.git对应的本地仓库中，从零实现P00；不要在ERP-AGENT目录修改，也不要复制其实现。

先检查pwd、git status、git log、origin和远程main，保留无关改动。读取：
1. AGENTS.md
2. docs/architecture/PROJECT_LAYOUT.md、EXTENSION_GUIDE.md
3. docs/specs/CONTRACTS.md、P00-foundation.md
4. docs/implementation/IMPLEMENTER-HANDBOOK.md、INTERFACES.md
5. docs/implementation/P00-implementation.md
6. docs/delivery/GIT_WORKFLOW.md、STATUS.md

按P00-T01至T05执行。计划中的代码和命令目前尚不存在，需要你创建；不要把规格当成已有功能。先做最小可运行工程，验证依赖、Mongo replica set事务、配置/本地会话、启停和验证脚本；不提前写采购、聊天、真实模型、订单、专家或沙箱功能。

关键行为补相称测试，按计划运行并保存真实退出码；创建模块中文README和evidence/P00.md。不能用mock通过代替事务实测，不能把未运行项目写成通过。

P00所有必需验收完成后，更新spec勾选、STATUS和必要架构说明，检查diff，只暂存本阶段明确文件，commit并push origin/main；创建并推送phase-p00标签，核对远程分支和标签的commit SHA。用户已授权阶段推送，不需重复询问是否上传。失败时保留本地提交并准确报告，不能宣称阶段完成。

最后报告：实现内容、实际检查/退出码、浏览器结果、未验证项、GitHub commit/tag链接、下一阶段交接入口。完成P00后停止，不自动开始P01。
```

## 后续阶段通用前缀

每次给另一个Agent时复制下面前缀，再附下方对应阶段指令。若同一个Agent续写也先检查仓库实际状态，不能只信上一轮聊天。

```text
你是TechnologyAgent的实施Agent。只实施我本次指定的阶段，按仓库docs/implementation/中的详细计划执行。
先检查仓库路径、Git状态、origin/main和前置阶段标签，保留无关改动。读取AGENTS.md、整体架构、共享契约、实施手册、接口映射、当前阶段spec/plan、STATUS及前一阶段evidence。若有HANDOFF.md一并核对实际代码。
不重新搭建已完成模块，不擅自改目录/契约/依赖版本，不复制参考ERP-AGENT代码。计划中的小实现细节自行合理解决；跨层契约变更同步更新文档、调用方与测试。
先实现当前任务的可检查行为，关键边界补测试并真实运行；更新模块README、evidence、spec勾选及STATUS。未执行的真实模型、浏览器或ERP项目明确not_run，不能用模拟结果冒充通过。
阶段必需验收满足后显式暂存本阶段路径、commit、push origin/main、核对远程SHA、推对应phase-pxx标签并核对解引用commit。推送未成功不算完成。最后给出实现/检查/限制/commit/tag和下一步，随后停止，不自动越到下一阶段。
```

### P01 阶段指令

```text
只实现P01。读取docs/specs/P01-domain-data.md和docs/implementation/P01-implementation.md。
前置phase-p00必须具备真实工程与验收证据。按T01-T06实现合成数据、查询端口、纯补货算法、业务API/类型生成及数据页。
核对P001可用15/预计25/缺55；价格优先S02/60500分，7天交期S01/66000分。MOQ不是包装倍数。
不接模型、不开放创建订单。验收并上传phase-p01后停止。
```

### P02 阶段指令

```text
只实现P02。读取docs/specs/P02-chat-streaming.md和docs/implementation/P02-implementation.md。
复用P01工程，建立原子run/事件/消息、FakeAgent、SSE、历史/取消和前端解析器。
重点验证同thread单活跃run、request去重、中文跨字节块、断线不取消、重放不重复、重启孤儿run明确失败。
页面及证据明确fake；不接真实模型。验收并上传phase-p02后停止。
```

### P03 阶段指令

```text
只实现P03。读取docs/specs/P03-agent-tools.md和docs/implementation/P03-implementation.md。
用真实ModelPort/LangGraph/MCP替换执行器，保留P02事件/UI契约；注册指定9个只读工具，身份从可信上下文注入。
验证预算/超时/错误链路，并将三个固定真实模型问题各运行3次，记录全部轨迹；没有Key明确not_run，不能宣称live通过。
不写订单。满足本阶段必需条件并上传phase-p03后停止。
```

### P04 阶段指令

```text
只实现P04。读取docs/specs/P04-orders-approval.md和docs/implementation/P04-implementation.md。
按T01-T06完成草稿/补充/编辑/确认、Mongo持久检查点、MutationService事务、审批UI与恢复。
批准、订单、inbound变化、幂等结果同事务；55件只新增一单，inbound10→65，on_hand仍20。测试重复/并发/旧版本/事务中崩溃和commit丢响应。
完成真实模型与浏览器MVP验收，上传phase-p04后停止。
```

### P05 阶段指令

```text
只实现P05。读取docs/specs/P05-harness-review.md和docs/implementation/P05-implementation.md。
增加结构化阶段、计划、确定性和语义评审。最多2次修订/3次检查，模型不能覆盖数值/来源/审批硬失败。
已成功订单只查询结果，评审不得重放提交。保留P04中断恢复与事件兼容。
验收并上传phase-p05后停止。
```

### P06 阶段指令

```text
只实现P06。读取docs/specs/P06-artifacts-sandbox.md和docs/implementation/P06-implementation.md。
实现Artifact授权下载、bar/line/pie、md/html/csv/json报告、真实Docker分析执行与预览。
遵守资源、禁网、无宿主挂载和输出校验；Docker失败不回退宿主shell。此阶段主Agent可用analysis_execute。
实际打开图表/报告核对中文、金额及scope；验收并上传phase-p06后停止。
```

### P07 阶段指令

```text
只实现P07。读取docs/specs/P07-specialists-skills-memory.md和docs/implementation/P07-implementation.md。
先以旧v1图建立待审批checkpoint，再引入v2/DeepAgents适配及版本路由，验证升级后旧审批继续由v1恢复。
增加分析/订单专家、3技能及显式偏好。共享父run预算、不递归、不自批；v2的analysis_execute仅分析专家可用。
完成跨版本与真实委派验收，上传phase-p07后停止。
```

### P08 阶段指令

```text
只实现P08。读取docs/specs/P08-erp-integration.md和docs/implementation/P08-implementation.md。
实现Provider、参考23业务工具、通用操作提案、收发货/改单事务和ERP字段/HTTP适配。
Receipt/Movement/订单已收/库存/批准/operation同事务；receipt换operation仍不能重复收货；inbound生命周期按固定数值验证。
远程超时先对账，禁止盲目重复写；真实ERP只在明确测试环境验证，无环境not_run。本地与真实ERP结果分开报告。
验收并上传phase-p08后停止。
```

### P09 阶段指令

```text
只实现P09。读取docs/specs/P09-acceptance-operations.md、FINAL-ACCEPTANCE.md和docs/implementation/P09-implementation.md。
完成run追踪、故障矩阵、F01-F18实际验收、桌面/手机操作、新环境启动与一致备份恢复。
本地必需F01-F14/F17-F18；F15/F16真实ERP独立记录。真模型代表场景各至少3次并保留全部尝试。
最终核对所有DB/文件/浏览器证据，上传phase-p09，报告本地交付与ERP边界，不将本机版本称为生产上线。完成后停止。
```

## 中途换 Agent

```text
请接续TechnologyAgent当前未完成阶段，不要从头重写。先读docs/delivery/HANDOFF.md，再核对实际HEAD、Git状态、当前plan/spec、evidence和最后失败命令。
只从第一个未完成且前置满足的任务继续；保留已有正确实现与无关改动。先复现失败再修复；不得把上一Agent口头声称通过当证据。
按当前阶段交付规则完成测试、文档、提交和上传。当前阶段完成后停止。
```

## 发回规划者审查

```text
其他Agent已实施TechnologyAgent的Pxx，请只审查与规划，不直接修改产品代码。
请核对该阶段GitHub commit/tag、spec/implementation任务、实际代码与evidence，检查接口衔接、数据一致性、必要验收和下一阶段依赖。
输出：可确认完成的项目、有证据的问题及位置、需实施Agent修正的任务、是否满足进入下一阶段条件。未运行检查明确说明；不要仅凭对方总结认定通过。
```
