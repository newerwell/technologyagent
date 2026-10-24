# tests/e2e 浏览器验收

## 职责

P02 `chat-flow.spec.ts` 覆盖：发送→工具卡→完成→刷新去重；运行中刷新恢复；停止→cancelled；切换会话历史。

## 运行

先启动本机应用（3030/8030 与测试库），再：

```powershell
npm --prefix frontend run test:e2e
```

或 `uv run python -m scripts.verify_stage P02 --mode browser`（同样要求服务已启动）。

## 说明

- Playwright 配置使用本机 Chrome channel；CI 不运行 browser 模式。
- 测试文件位于仓库根，但按 frontend workspace 安装的 @playwright/test 相对路径导入。
- 测试使用唯一消息前缀和 serial 模式，避免动态会话列表互相干扰。
- 不是真实模型/ERP 验收；页面明确 FakeAgent。
