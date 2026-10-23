# P01 补修 Implementation Plan

> **For agentic workers:** 其他实施Agent只执行本补修。规划者不改产品代码。不要开始P02；不要移动既有阶段标签。

**Goal:** 让初始化数据可持续使用、库存可对账、界面结果与当前输入一致，并能从首次连接失败恢复。
**Architecture:** 保持既有ports/domain/services/API结构，种子管理与业务状态分离；前端用明确的请求代次和会话重试状态。
**Tech Stack:** 现有锁定环境；不用升级依赖解决这些逻辑问题。
**Spec:** [P01审查报告](../reviews/2026-10-23-P01-review.md)、P01原spec/implementation和CONTRACTS。

**执行状态（2026-10-23）：** F01–F05 已实现、推送并通过 GitHub Actions；原 phase-p00/phase-p00-fix1/phase-p01 保持不动，phase-p01-fix1 在最终记录提交后核对。复核通过后再进入 P02。

## Global Constraints

保持P001的15/25/55、60500/66000；保持原6/3/8/8/2历史订单规模；不接模型/聊天/订单写API；不因修复清空开发库；P00回归不能倒退。

## Review Focus

种子覆盖已变化记录→F01；错误在途/预警被manifest固化→F02；旧请求的成功/失败/finally覆盖新输入→F03；首次会话失败后刷新无效→F04；只测happy path或重写标签→F05。

### P01-F01：默认初始化保留已有状态

**Files:** Modify backend/app/services/seeding.py、必要seed CLI/说明；Test tests/integration/test_seed.py。
**Interfaces:** seed默认只插缺失合成ID，不替换已存在记录；显式reset仍仅允许technologyagent_test_*。建议用$setOnInsert+upsert，不用replace_one默认覆盖。

- [x] 先写失败测试：seed后修改I001 inbound65/version2、O001 shipped/version2；新增一张合法的P001/W01未收55件订单及相应草稿；再seed，所有修改和新记录保持不变。新增记录的DTO必须合法，不再用items空/status=draft的非法PurchaseOrder当唯一保护用例。
- [x] 增加已有物料/供应商/报价/草稿字段变化的保留检查，以及缺一条合成记录时只补缺失项；普通seed不能把业务version回退。
- [x] 默认插入与reset行为明确区分。输出说明counts是种子输入数量还是当前DB数量，不能用manifest计数代替实际保护断言。
- [x] 真Mongo跑test_seed，复现中原65/version2必须仍65/version2；测试库清理保持前缀校验。

### P01-F02：种子对账与固定预警集合

**Files:** Modify fixtures/v1/inventories.json、manifest.json、services/seeding.py的validate_bundle、受影响tests/unit和integration断言；必要时新增显式fixture修正工具。
**Interfaces:** 验证全量未关闭订单剩余量与每个库存inbound一致；只有I001/I005预警；P002/W02保持预计量=安全库存15。P001结果不变。

- [x] 增加独立断言：完成/取消订单不产生inbound，未收量必须非负，每个未收订单行对应已知库存；汇总后与所有库存的inbound逐项相等。fixture不满足先拒绝写库，不等报告生成后掩盖。
- [x] 一种确定的修正：I004 on_hand15/inbound0（其余不变）；I006 on_hand12（预计10=阈值10）；I007 on_hand5/inbound0（预计5=阈值5）。其他字段、P001和两张历史单保持原契约；不得凭空新增第三张历史单支撑错误inbound。
- [x] 更新manifest/哈希/仓库汇总与精确预警集合断言；不能仅把warning_count固定为当前生成值。重新核对P001两种报价、P002阈值、P003无报价、8条分页。
- [x] 处理已初始化本地库：默认seed改为保留后不会自动修正旧错误。若提供修正命令，必须默认dry-run，仅对明确的旧fixture ID且完整内容/hash/version匹配旧基线时迁移；用事务、先输出备份/变更列表，遇到已有业务修改或相关新增订单即拒绝自动覆盖并报告。不要对开发库开放reset，也不要在API启动时悄悄迁移。
- [x] 在空测试库、旧基线测试库、已有业务修改测试库验证新seed/迁移，分别应正确初始化、有限修正、拒绝覆盖业务变化。修改README说明用户当前演示库是否仍需显式修正。

### P01-F03：预览和选择保持一致

**Files:** Modify frontend/src/components/data/ReplenishmentPreview.tsx、DataPage.tsx及必要Props/API取消支持；Test DataPage.test.tsx，可新增ReplenishmentPreview.test.tsx。
**Interfaces:** 预览结果绑定物料/仓库/最大交期/数据刷新代次；只有仍有效的请求可改变preview/meta/error/loading。不在浏览器重算业务结果。

- [x] 用deferred promise写失败用例：W01请求pending→切W02→W01成功，不能展示W01金额；同样测试旧请求reject/finally不能清掉新请求loading或覆盖新错误。
- [x] 任意实际物料/仓库/交期变化，使旧请求失效并清预览；刷新数据、目录失效/加载失败也统一失效。可用generation ref或AbortController+代次校验，不仅在onChange里setPreview(null)。
- [x] 分离目录获取与库存分页：翻页不清掉仍有效的parts/选择；若当前物料实际被筛掉，先清预览再选新物料，不能出现P001选择框配P003结果。
- [x] 补“P003无报价→翻页/刷新”“改变最大交期”“目录失败”“快速连续参数变化”测试；结果未重新计算时界面不得保留旧金额/报价。
- [x] 保留DataPage已有的普通列表过时响应保护；检查通过后用真实浏览器限速或受控延迟验证关键路径，记录当前输入和实际结果。

### P01-F04：会话失败后可主动恢复

**Files:** Modify DataPage.tsx及必要会话hook/lib/api；Test DataPage.test.tsx。
**Interfaces:** 刷新动作统一协调会话与数据；未就绪时先ensureLocalSession，成功再加载，失败仍能再次点刷新。不无限自动重试。

- [x] 用例：首次ensureLocalSession失败→服务恢复→点刷新，调用次数应从1到2，随后业务查询执行且旧错误清除。
- [x] 区分session loading/ready/error和业务loading；重试失败后按钮可用，不卡loading；重复点击避免并发创建多次会话。
- [x] 如处理中途401，只做有界会话恢复并说明失败；403等不应进入无限认证循环。保持P00 Host/Origin/Strict策略不变。
- [x] 单测/typecheck/build以及浏览器“后端临时不可用→恢复→刷新”通过，不要求用户整页重载。

### P01-F05：回归、说明与修复交付

**Files:** Update evidence/P01.md或新增evidence/P01-fix1.md、STATUS、种子/前端模块README及实际变更的schema/类型。
**Interfaces:** 原phase-p01继续指2328263；补修用新annotated phase-p01-fix1，不能重写P00/P01旧标签。

- [x] 执行P01 offline manifest，包含P00所需回归；验证schema/type的--check；F01–F04新增断言都必须实际运行。按实际数量记录，不假定仍是25/49/4。
- [x] 增加浏览器证据：预览参数/结果一致、翻页保留有效选择、临时失败可恢复；记录内存组件探针与真实浏览器的不同证据类型。
- [x] STATUS写清P00原两项已关闭、P01补修实际状态、开发库修正是否执行；不覆盖旧历史报告，不仅改勾选/文字来声称修复。
- [x] 显式暂存源码/测试/必要fixture/说明/证据，commit并push origin/main；推phase-p01-fix1，核对远程解引用SHA。清理本次临时库/进程/生成规则，保留.dsh-meow和无关改动。
- [x] 报告修复结果、实际检查、commit/tag、未验证项并停止；复核通过再做P02。

## 发给实施 Agent

```text
请只做TechnologyAgent的P01补修，不开始P02。先读AGENTS.md、docs/reviews/2026-10-23-P01-review.md和docs/implementation/P01-followup.md。
按F01–F05修复：默认seed保留已有数据/版本；修正无订单依据的在途量和多余预警并增加对账；预览绑定参数和数据代次，防止旧请求回填及翻页选错；首次会话失败后刷新可重试。
关键问题先写可复现的失败测试，再改代码；不要仅改fixture manifest或预期值来抹掉错误。开发库不能reset，旧基线修正须显式且拒绝覆盖业务变化。
完成P01全量及P00相关回归、必要浏览器验证，更新模块README/evidence/STATUS。保留phase-p00、phase-p00-fix1、phase-p01，提交推送并创建phase-p01-fix1，核对远程SHA后报告并停止。
```