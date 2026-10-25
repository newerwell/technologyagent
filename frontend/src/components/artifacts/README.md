# 产物卡片

本目录展示服务端持久化的 `artifact_ready` 事件。下载与图表预览只拼接事件中的不透明 `artifact_id`，后端会再次按当前本机会话 owner 授权；页面不接受模型正文中的路径或URL。

会话加载及每轮运行结束会查询 `/api/artifacts?thread_id=...`，恢复该会话各run的历史文件；同会话追问保留已有卡片，按artifact_id去重。产物历史不共用当前run的SSE seq；切换到其他会话会重新加载其owner授权集合。

- `ArtifactCard`：文件名、格式、来源、下载和PNG预览。
- `ChartPreview`：聊天消息流内的产物集合；历史事件重放后仍可恢复。
- 预览：`GET /api/artifacts/{artifact_id}/preview`；下载：`GET /api/artifacts/{artifact_id}`。
- 限制：支持服务端登记的PNG、CSV、Markdown、HTML、JSON；只有PNG以内联图像预览，其余报告走鉴权下载，避免不可信HTML在应用域内内联执行。
- 验证：`npm --prefix frontend run test -- --run`、`npm --prefix frontend run typecheck`、`tests/e2e/artifacts.spec.ts`。
