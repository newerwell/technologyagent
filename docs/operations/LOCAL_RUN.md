# 本地运行

从仓库根目录执行 `./start.ps1`，启动 MongoDB、副本集 API 与前端；`.runtime/logs/` 保存本次启动日志，`.runtime/processes.json` 记录由该项目启动并校验身份的进程。`./stop.ps1` 只停止登记的应用进程，MongoDB 保持运行。

首次安装使用锁文件：`uv sync --frozen --group dev`、`npm --prefix frontend ci`。复制 `.env.example` 为 `.env`，填写 `MODEL_MODE=live`、模型名和本机密钥；密钥只保存在本机。模型调用验收还需在当前终端显式设置 `RUN_LIVE_MODEL=1`。默认 `MODEL_MODE=fake` 仅供确定性离线与浏览器测试。

启动后访问 `http://127.0.0.1:3030`；`/health` 只报告进程存活，`/ready` 单独报告 Mongo 事务、MCP、模型和Docker状态。浏览器地址只绑定本机，当前版本不提供生产身份、远程登录或公网部署保证。
