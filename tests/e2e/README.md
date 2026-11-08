# tests/e2e 浏览器验收

## 职责

P02 `chat-flow.spec.ts` 覆盖聊天恢复和竞态场景。P04 `order-flow.spec.ts` 覆盖缺仓库补充、服务端计算55件/660元、编辑为60件/720元、服务进程重启后刷新恢复同版本并批准；浏览器结束后从订单列表核对数据库结果。

## 运行

先启动本机应用（3030/8030 与测试库），再：

```powershell
npm --prefix frontend run test:e2e
```

或 `uv run python -m scripts.verify_stage P02 --mode browser`（同样要求服务已启动）。

P04 使用隔离库 `technologyagent_test_p04_browser`，须在该库和本机服务下运行：

```powershell
uv run python -m scripts.verify_stage P04 --mode browser
```

P04 manifest 会顺序运行 E2E；订单流程通过 `stop.ps1`/`start.ps1` 重启项目登记服务，需在 PowerShell 7（pwsh）环境执行。

## 说明

- Playwright 配置使用本机 Chrome channel；CI 不运行 browser 模式。
- 测试文件位于仓库根，但按 frontend workspace 安装的 @playwright/test 相对路径导入。
- 测试使用唯一消息前缀和 serial 模式，避免动态会话列表互相干扰。
- FakeAgent 全量 browser 用例验证UI、Mongo检查点和API事务；P04真实模型验收另运行订单流程：`MODEL_MODE=live` 启动服务、`P04_EXPECT_LIVE=1`、`P04_RESTART_BACKEND=1`，并只选择 `tests/e2e/order-flow.spec.ts`。真实模型验收不代表ERP验收。
- P04 fake/browser 只验 UI、Mongo 检查点和 API 事务；真实模型浏览器验收需 `MODEL_MODE=live` 启动服务并设置 `P04_EXPECT_LIVE=1`，不能把默认 fake 通过计为 live。
- `artifacts.spec.ts`覆盖artifact_ready与同会话历史卡片展示；链接/预览卡片断言本身不证明文件下载内容，真实API下载内容由 `tests/integration/test_artifacts.py` 和 `test_analysis_artifact_flow.py`回读验证。报告/图表人工打开另记，不以Playwright fixture代替。
- P09 `p09-responsive.spec.ts` 在 1440×900 桌面和 390×844 手机视口检查聊天/历史、订单输入与主体溢出；完整入口与15项E2E报告见 `evidence/P09.md`。本轮截图留在 `evidence/P09/`；截图和DOM断言不代替全部图表/报告格式的人工打开验收。
- P09 R8 的 `order-flow.spec.ts` 使用 1440×900 与 390×844 两种 viewport、`--workers=1`，在隔离 `technologyagent_test_p09_browser` + fake/local_seed 中逐个生成并授权下载 MD/CSV/JSON，再完成 55→60 套订单、服务重启恢复、批准和决定幂等重放。每种格式均核对登记字节数、SHA、正文范围与来源；文件实际在记事本打开的记录见 `evidence/P09-R8.md`。测试对每个 viewport 重新 seed 受限测试库，避免浏览器重跑受旧订单和库存影响；不会重置开发库。
- R8 重启进程继承当前 `API_PORT`、`FRONTEND_PORT`、`MCP_PORT`，Playwright baseURL由同一 `FRONTEND_PORT` 派生；若设置 `P09_BROWSER_BASE_URL`，必须与前端端口一致。缺少变量时采用项目启动默认值 8030/3030/9030。测试在reset前验证隔离 Mongo URI、test数据库、local_seed与fake配置。默认端口和专用端口均需运行完整双尺寸流程，workers固定为1；本轮截图文件名、SHA、关联artifact/run见`evidence/P09-R8.md`。
