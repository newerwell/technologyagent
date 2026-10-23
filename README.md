# TechnologyAgent

从零实现的采购 Agent 项目。业务目标是查询库存和供应商、生成补货建议、确认后执行订单，并逐步支持流程评审、图表报告、专家委派、技能记忆与 ERP 接入。

仓库：[newerwell/technologyagent](https://github.com/newerwell/technologyagent)。参考项目只提供需求和效果参考；本仓库独立编写实现、测试与文档。

## 当前状态

工程蓝图、P00–P09阶段规格及供其他Agent使用的详细实施手册已建立。**尚未实现应用代码，P00未开始。** 当前仓库不能启动采购应用。规划文档提交不代表任何功能阶段验收通过。

## 阅读顺序

1. [整体文件布局](./docs/architecture/PROJECT_LAYOUT.md)：目录、模块责任、每个文件的创建阶段。
2. [扩展设计](./docs/architecture/EXTENSION_GUIDE.md)：依赖方向、稳定接口、未来功能接入方式。
3. [阶段总览](./docs/specs/README.md)与[共享契约](./docs/specs/CONTRACTS.md)：产品行为、数据和接口标准。
4. [阶段Git交付规则](./docs/delivery/GIT_WORKFLOW.md)：每阶段验收、提交、推送与远程核对。
5. [交付状态](./docs/delivery/STATUS.md)：当前阶段与实际验证范围。
6. [其他Agent实施入口](./docs/implementation/README.md)：10份详细实施计划、统一接口、检查命令与可复制启动提示词。

本聊天负责规划；用户选用的其他Agent负责代码实施。可直接复制[Agent启动提示词](./docs/implementation/AGENT-PROMPTS.md)开始P00，每阶段验收并上传后停止，再交接下一阶段。

P04验收后形成采购核心MVP，P09本地验收后具备与参考项目相近的完整本地演示能力。真实ERP联调单独记录。
