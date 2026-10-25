# P06-fix1 及前置补修

日期：2026-10-25。基线 `11673c672ba9c456903ce81967d763ea3891a06e`，原 `phase-p06` 不存在；原 `phase-p05` 不移动。仅实施 P06 与 P03/P04/P05 残留修复，不开始 P07。

## 实施与确定性反例

| 项目 | 修复 | 反例/当前检查 |
|---|---|---|
| F01 Linux SocketIO | Docker exec 上传同时支持 `sendall` 与部分 `write` 循环；关闭输入流产生EOF；超时/异常资源清理。 | 新增SocketIO短写、传输失败、服务端非0退出测试；修复前3失败/1通过，后4通过。远程Linux CI待提交后核验。 |
| F02 可信产物链 | 新增授权数据集和正式 `artifact_report` / `artifact_chart` Agent工具；报告行、金额、范围和来源由成功只读查询派生，图表只能选择类型，不能输入模型数值。检查金额整数分、数量、报价来源和有效期；ready事件在内容校验、登记后发布。 | `tests/integration/test_analysis_artifact_flow.py` 查询P001/W01、Q01/Q02 55件，验证66000/60500分、来源和scope；额外行9999被拒；错误/缺源样例不产ready。 |
| F03 来源与编码 | 授权数据集保留call_id、工具、参数、scope、as_of、source_refs；md/html/csv/json统一写范围、来源和观察时间。CSV转义表头、明细和元信息；数值列拒绝布尔/字符串/非有限值。 | 报告渲染原3个失败用例修复为通过；整链解析CSV回读金额与Q01/Q02来源。 |
| F04 时限/回收 | 图执行器对沙箱工具给最多30秒，仍服从run剩余预算；sandbox作业按run+job标签独立跟踪，超时/取消终止指定容器并等待回收。 | 生命周期反例先观察到取消后容器仍运行，修复后focused lifecycle/transport/report/registry/artifact tests 14 passed。完整真实Docker故障矩阵及Linux CI以manifest与远程结果记录。 |
| F05 降级 | Docker能力探测0.25秒独立超时、2秒缓存；基础只读registry不等待可选依赖；不可用时仅隐藏容器执行/图表。 | 单测慢探测原失败、修复后registry 4 passed；真实Graph慢探测原超过550ms失败，修复后通过。 |
| F06 历史产物 | 新增按owner/thread聚合全部run产物的API，只返回safe DTO，不返回storage_key；前端会话加载/运行结束刷新历史，按artifact_id去重，追问保留同thread产物。 | 初始历史API测试因404失败后修复；artifact API集成3 passed；前端历史合并断言通过。浏览器真实后端下载与视觉打开仍需单独核验。 |
| F07 P03/P05验收与事实 | Markdown表格按header分隔行绑定字段，supplier_id加入事实范围；P003第三题检查“无有效报价”语义，不能被“没有缺口，报价有效”误放；live pytest有skip即失败；P05 live入口调用P03严格事实门槛。 | 修改后live acceptance/evidence/manifest目标测试28 passed。固定P03 3题×3次真实模型和P05 A04 live结果需以本轮trace/DB对照为准。 |
| F08 P04订单残留 | 每轮修订后将正文显式数量、分/元金额同持久订单事实比对；静默模型stream每100ms检查取消/剩余时限；恢复决定从持久resume_request读取幂等键并记录原结果。 | 恢复结果用例先失败（记录调用0次）后修复；新增错数量999/金额9999后再改正的整链测试及静默stream取消测试。订单focused集成检查正在跑。 |

## 实际验证

- Windows：`test_sandbox_transport.py` 4 passed；报告渲染、事实产物、registry与lifecycle合计14 passed；慢Docker Graph反例1 passed；产物API 3 passed；前端Vitest 10 files / 38 tests passed，typecheck exit 0。
- P03/P05事实及stage gate针对检查：28 passed。恢复key红测为1 failed，修复后纳入订单回归。
- Windows完整 P06 offline 首轮保留报告 `.runtime/reports/P06-fix1-offline.json`：镜像构建、DB init、129 unit、前端typecheck/38 test/build、contracts通过；integration为152 passed、1 failed、2 errors。失败为既有analysis_execute测试错误地期望用运行期dataset UUID代替来源；已把测试夹具改为记录级I001 source_ref，目标集成重跑6 passed。2个tmp_path错误来自Windows `%TEMP%` ACL；完整复跑使用仓库 `.runtime` 下的pytest basetemp。
- 完整 P06 offline复跑报告 `.runtime/reports/P06-fix1-offline-rerun.json`：exit 0、9/9 checks；129 unit、155 integration（真Docker analysis/隔离测试库）、前端38 tests、typecheck/build和contracts均通过。另将范围/数量结构化边界先测红（2失败），修复后单测及产物整链共4 passed。
- 最终离线复验 `.runtime/reports/P06-fix1-offline-final.json`：2026-10-25 02:01:58Z–02:08:56Z，exit 0、9/9 checks、418.08s；DB init、Docker sandbox镜像构建、隔离测试seed、131 unit、155 integration（含真实Docker执行/隔离/超时/no-network/产物授权）、前端typecheck、38 frontend tests、build、contract check全部通过。首轮同版代码集成153 passed/2 errors，错误均为系统 `%TEMP%\pytest-of-xiaomi` 的WinError 5；用仓库内唯一 `.runtime/pytest/p06-offline-final-20261025` basetemp复跑后155 passed。首次P06 offline的source_ref夹具误期望与temp ACL失败分别保留在旧报告，不覆盖。
- P06 browser最终报告 `.runtime/reports/P06-fix1-browser-final.json`：exit 0、2/2 checks，artifact history E2E 与既有聊天/订单共9/9通过；同一thread保留旧run产物卡片。此浏览器场景以持久化事件/下载href/preview src的受控路由夹具验UI，实际授权下载字节由artifact API集成测试校验，不能将href断言单独视为浏览器下载验收。
- 图表文件实际打开并视觉核对：`bar-valid-quotes.png`显示P001刹车片、55件、华东制动660元与南方汽配605元；`line-three-days.png`显示三天订单趋势与日期；`pie-inventory-categories.png`显示中文分类和占比。三图标签无明显裁切。md/html/csv/json报告内容通过文件读取核对，其中文、scope/as_of、来源引用和金额可读；四份文件的Codex面板打开请求返回queued，未把queued状态冒充为已确认的交互打开。CSV/JSON由报告和整链测试解析核验；HTML实际页面人工浏览器打开仍未确认。
- 真实模型配置已安全检查为live且凭据存在；当前命令仅对隔离库显式启用`RUN_LIVE_MODEL=1`。P03-A06实际执行固定3题×3次，9条完整脱敏轨迹在忽略目录`.runtime/live/p03-readonly.json`，原执行时通过3/9，严格门槛**未通过**。失败包括：首题1次NUMERIC_MATCH硬校验失败；7天供应商题1次数值校验失败、1次执行流失败；P003题1次验收正则未接纳正文“P003（火花塞，铱金）没有有效报价”。已用该真实措辞构造确定性反例，先失败后放宽允许零件描述的匹配窗口，`tests/unit/test_live_acceptance.py` 10 passed。该历史尝试不追认通过、未重跑固定3×3；即使按新校验回看可消除1项误报，严格3×3仍失败。每次订单/操作/已消费审批数及I001库存前后快照一致；不是开发库写入。完整失败原因和证据在报告/轨迹中保留，不把错误统归模型。
- P05-A04实际live单项通过：`.runtime/live/p05-a04-attempts.json`新增一条；真实模型把受控首轮遗漏修订一次，运行completed、revision_count=1。独立`technologyagent_test_p05_live`库内订单2→3、order_create操作10→11、已消费审批10→11，I001 inbound 10→65且on_hand保持20。此结果不替代P03-A06。
- 初始实现提交 `2c646ff252a195905c9d4a332d0df17a85bc98f1` 已推送，远程`main` SHA核对一致；其Linux Actions run [40153408262](https://github.com/newerwell/technologyagent/actions/runs/40153408262) 正在执行（后续校验修复另有提交/CI）。旧标签未移动，P03-A06严格前置门槛未关闭，不创建完成标签；P07不开始。

## 保护项与限制

`.env.example`、`.dsh-meow/`、`frontend/AGENTS.md`是预存更改/未跟踪内容，未纳入本任务暂存范围；未读取或输出密钥，未reset开发数据库。开发测试只使用测试库。\n\n