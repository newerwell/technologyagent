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
