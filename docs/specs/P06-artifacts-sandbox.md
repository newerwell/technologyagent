# P06：图表、报告、文件下载与执行沙箱

状态：2026-10-25 P06-fix2代码、Windows offline/browser与P03真实3×3通过；具体实现及证据见[P06-fix2计划](../implementation/P06-fix2-implementation.md)和[evidence/P06-fix2.md](../../evidence/P06-fix2.md)。用户已确认指定HTML显示正常。正式后端浏览器授权下载、其他报告格式人工打开与Linux CI仍待核对；严格验收未关闭，不创建P06完成标签、不开始P07。历史独立审查和fix1证据保留：[P06审查](../reviews/2026-10-24-P06-review.md)、[P06-fix1](../../evidence/P06-fix1.md)。

2026-10-25 P06-fix2：共用金额字段/实体校验、P03约束/范围和独立live oracle已补修；P03-A06新固定3×3为9/9，前置历史失败轨迹未覆盖。P06 formal download、其他格式视觉检查、Linux CI仍独立待验，不能用HTML用户确认或夹具路由E2E替代。

## 任务

- [x] **P06-T01 产物服务。** `services/artifacts.py`、`repositories/artifacts.py` 创建文件元数据，按owner/run隔离存储；流式下载使用artifact_id；对文件不存在、未完成、跨用户访问返回明确错误；完成后发 artifact_ready。
- [ ] **P06-T02 固定绘图工具。** `sandbox/charts.py` 支持 bar/line/pie，输入 series/labels/title/source_refs；bar用于供应商金额，line仅接受实际时间序列，pie拒绝负数和全0；请求不支持类型明确拒绝，不静默回退柱状图。
- [ ] **P06-T03 报告生成。** `sandbox/reports.py` 支持 Markdown、HTML、CSV、JSON；固定输出数据范围、来源时间、明细、结论、建议、缺失项；CSV使用UTF-8 BOM和公式单元格转义，HTML转义外部文本，JSON金额仍用分。
- [ ] **P06-T04 容器任务后端。** `sandbox/runner.py`、`sandbox/Dockerfile` 实现 create/upload/execute/collect/destroy；构建时装依赖，运行时禁网；采用共享资源和文件限制，不把整个参考仓库或.env上传容器。
- [ ] **P06-T05 受限分析代码执行。** 注册 `analysis_execute`，本阶段主Agent可用；主进程提供当前已授权数据文件，代码只能在每run容器临时目录执行；超时/资源耗尽返回工具错误，不回退本机shell。通过Docker API回收输出并登记产物。
- [ ] **P06-T06 UI与文件质量检查。** 本轮offline与browser自动检查通过；图表PNG三类已实际打开核对。报告核心内容/数值/source/scope由解析与整链测试核验，Codex面板打开请求处于queued且未确认面板状态；2026-10-25用户确认本地quote-comparison.html显示正常，该文件人工视觉检查通过；其他格式的人工打开和真实后端浏览器下载不能据此视为已验，严格验收未关闭。

原勾选记录与本轮复核分开：T02/T03模块和样例存在但正式Agent链未接入固定核验；T04跨平台及取消时限、T05普通查询降级/来源仍需补修。T01的授权下载基础已实现，不表示所有历史和内容要求通过。

## 验收

| ID | 操作 | 通过条件 |
|---|---|---|
| P06-A01 | 比较S01/S02购买55件的金额并生成图 | bar为660.00/605.00元，来源与工具一致，不含失效S03 |
| P06-A02 | 合成3天历史订单时间序列；库存分类占比 | 实际生成line和pie，图例/中文/数值可读，非同一图换标题 |
| P06-A03 | 导出同一分析四种格式 | 四个文件均可打开/解析，核心明细、总额、scope一致 |
| P06-A04 | 用户B下载A产物；传入伪造路径 | 404或422，不读取任意磁盘文件 |
| P06-A05 | 执行无限循环、超额输出和联网代码 | 分别超时/限额/无网络；无宿主机执行；容器被回收 |
| P06-A06 | Docker不可用或生成失败 | 能继续普通业务查询；文件工具明确失败，无假下载链接 |
| P06-A07 | 分析代码读取授权数据、输出一份CSV | 代码只在容器执行，文件登记到当前owner/run且内容正确 |

## 本阶段结束后

形成“查询→分析→图表→报告→下载”的完整体验。先用每run临时容器，不要求预热池、Go/Node运行时和任意远程技能安装；这些不影响采购演示主线。

## 阶段 Git 交付

- [ ] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [ ] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [ ] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p06` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [ ] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。
