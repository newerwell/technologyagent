# P09 补修工作区基线

## 基线核对

- 仓库：`C:\Users\xiaomi\Desktop\新建文件夹 (2)\technologyagent`
- 分支：`main`
- 基线 HEAD：`0dd835cb1ac5c520277f3263249bea2aeaefad1b`
- 开始时 `origin/main`：`0dd835cb1ac5c520277f3263249bea2aeaefad1b`
- `.env`、库存 JSON 与 metadata 均被忽略；没有读取或暂存 `.env`。
- 用户库存副本仅在本机读取结构计数以核对未受测试修改：72 条记录、72 个物料、6 个仓位；报告缺失字段仍为未知。本文件不保存私有文件哈希。

## 变更归类

任务 0 基线提交纳入本机库存快照适配及其配置、API/MCP/本地工具/UI调用、范围与事实处理、模块文档和对应回归；并纳入用户提供的本补修实施手册。提交不包含 `.env`、原始库存 JSON、metadata、数据库或运行目录。

以下既有未跟踪内容保留在工作区，不纳入基线提交：`.dsh-meow/`、`frontend/AGENTS.md`、`docs/reviews/` 下的复审文件、`evidence/screenshots/`。这些文件未被覆盖或删除。

## 实际检查

| 检查 | 命令/结果 | 状态 |
|---|---|---|
| 快照适配单元 | `uv run python -m pytest --basetemp .runtime/pytest-task0-snapshot-unit tests/unit/test_inventory_snapshot.py -q -rs`；3 passed，exit 0 | passed |
| 后端单元 | `uv run python -m pytest --basetemp .runtime/pytest-task0-backend-unit tests/unit -q -rs`；263 passed，exit 0 | passed |
| 前端单元 | `npm --prefix frontend test -- --run`；10 files、39 tests passed，exit 0 | passed |
| 前端类型 | `npm --prefix frontend run typecheck`；exit 0 | passed |
| 快照 HTTP/MCP 集成 | `tests/integration/test_inventory_snapshot_routes.py` 未能启动；默认连接发现端口 Mongo 是 standalone，改用 directConnection 后端口拒绝连接。Docker daemon 未运行，故不能执行副本集集成验证 | blocked by local environment; not passed |

数据库集成失败属于当前本机服务不可用，不是产品断言失败。不得将其记录为通过。后续需要在不重置 `technologyagent_dev` 的前提下启动仓库要求的 Mongo replica set，再运行完整 offline/browser 门禁。

## Git 状态

本证据用于任务 0 的已有功能基线，不代表 P09 完成，不创建或移动阶段标签。任务 1 从停用物料预览反例开始。
