# P02：流式对话、历史与运行状态

状态：已实施并推送 7020f55；本地离线 9/9、前端解析/状态机、Chrome E2E 4/4 通过，GitHub Actions run 40056732982 success；等待 phase-p02 标签核对与复核。依赖：P01。目标：用户能发起任务、查看进度、停止任务，并在刷新后恢复状态。本阶段先使用明确标注的 FakeAgent。

## 任务

- [x] **P02-T01 固定事件 schema。** `contracts/events.py` 定义共享事件，导出 schema 并生成 `frontend/src/lib/events.ts`；建立代表性事件 fixtures，协议检查防止手写两端枚举漂移。
- [x] **P02-T02 运行与消息持久化。** `services/runs.py`、`repositories/runs.py` 保存 run、message、event；实现 seq 原子递增、request_id 去重、同 thread 单活跃运行限制、owner 检查。
- [x] **P02-T03 SSE 与假执行器。** `api/chat.py` 实现 POST 流；FakeAgent 仅发示例 token/只读工具事件，不冒充真实查询或模型。任务调度与连接分离，关闭观察流不能直接杀掉后端任务。
- [x] **P02-T04 历史、重放和取消。** 实现 conversation、run 查询、events after_seq、cancel；服务重启后将无检查点的遗留 running 明确标 failed/PROCESS_RESTARTED，不假称可恢复；P04 再升级为检查点恢复。
- [x] **P02-T05 前端交互。** `lib/sse-parser.ts`、`hooks/useChat.ts` 与消息/工具卡片/历史组件；解析跨 chunk、UTF-8 与空行断帧，按 run+seq 去重；刷新按共享恢复策略补齐状态。
- [x] **P02-T06 协议和浏览器检查。** `tests/integration/test_chat_stream.py`、前端解析测试覆盖断帧、重复事件、取消和错误；浏览器执行发送、切会话、刷新、停止，记录 P02 evidence。

## 验收

| ID | 操作 | 通过条件 |
|---|---|---|
| P02-A01 | 发送“测试流式输出” | 持续增量显示，唯一 message_id，流结束明确，页面标注假执行器 |
| P02-A02 | 将同一事件拆成多个字节块，含中文 | 内容完整、事件只解析一次，无乱码 |
| P02-A03 | 中途刷新页面；重复重放同一 seq | 任务结果可补齐，消息和工具卡片不重复 |
| P02-A04 | 连续重复提交相同 request_id | 只生成一次运行；同 thread 不同请求并发返回409 |
| P02-A05 | 取消任务；关闭浏览器连接 | 前者不再调度后续步骤；后者仍可查询实际运行结果 |
| P02-A06 | 测试用户B查询/删除用户A会话、run、events | 返回404，不泄露内容；运行中删除返回409 |

验收结果（2026-10-24，本机 Windows 10）：A01–A06 全部通过；实际命令、退出码、74 integration、17 frontend、4 E2E、截图见 [evidence/P02.md](../../evidence/P02.md)。

本阶段证据明确 **model_mode=fake**，FakeAgent 不调用真实模型、不写业务数据。

## 本阶段结束后

有稳定交互壳，但只有 FakeAgent。证据中必须写 model_mode=fake；下一阶段替换执行器，保留协议、历史与页面。

## 阶段 Git 交付

- [x] 实现和本阶段验收完成；新增/变更模块包含中文README，说明职责、接口、运行例子与限制。
- [x] 更新本阶段evidence、任务勾选、架构图和扩展契约；检查改动及敏感文件，仅暂存本阶段明确路径。
- [x] 提交本阶段源码、测试、文档和证据，推送到 `origin/main`；创建并推送 `phase-p02` 标签；按 `docs/delivery/GIT_WORKFLOW.md` 核对远程SHA。
- [x] 向用户报告结果、实际检查、commit链接及阶段标签。推送未成功则标记“远程未交付”，不宣布阶段完成。