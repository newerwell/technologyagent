# P06 图表、报告与执行沙箱

本模块负责固定图表/报告格式、Docker隔离任务和容器输出安全收集。业务服务只传入已授权的最小数据；容器每次单独创建并销毁。

- `build_chart_spec(kind, data, source_refs)` 验证 bar/line/pie 输入；`render_chart_in_sandbox(spec, sandbox, ctx)` 在含 `Noto Sans CJK JP` 的固定镜像中生成PNG。金额以整数分输入并按元显示；line要求至少两个有序真实日期；pie拒绝负数和全零。
- `build_report_spec(format, analysis)` 从同一 `AnalysisResult` 生成md/html/csv/json；CSV含UTF-8 BOM并防公式注入，HTML转义，JSON保留整数分。
- `DockerSandbox.execute(SandboxJob, ctx)` 执行最多30秒；Docker镜像为 `technologyagent-sandbox:0.1.0`。基础镜像digest、Matplotlib及其Python依赖、Noto CJK字体包均固定。启动：`docker build -t technologyagent-sandbox:0.1.0 -f backend/app/sandbox/Dockerfile backend/app/sandbox`。
- 容器：无网络、无宿主挂载、只读根、非root、cap_drop ALL、no-new-privileges、512MiB/1CPU/pids64；/work与/out为限额tmpfs。inspect不符合策略时拒绝启动；Docker失败不回退本机shell。
- `collect_archive` 只接受平面白名单的常规文件，拒绝链接、路径穿越、重复、超额和不支持格式；不会调用 `extractall`。
- `analysis_execute`仅传入当前run授权数据和白名单输出；模型Key、MCP令牌、`.env`和仓库不会进入容器。
- 验证：`uv run pytest tests/unit/test_chart_specs.py tests/unit/test_report_rendering.py tests/unit/test_sandbox_collectors.py -q` 和 `uv run pytest tests/integration/test_sandbox.py -q`；集成测试要求Docker可用并先构建镜像。
- Docker `exec_start(socket=True)` 的SocketIO/file-like与原生socket共用完整写入适配；部分写入、传输异常和EOF有针对性测试。每个run/job有独立容器句柄；工具取消或run/沙箱时限结束时按job终止并回收，不扫描或杀其他任务容器。
- Graph对sandbox_execute使用最多30秒工具窗口，同时受run剩余活跃预算约束；Docker可选探测另行设0.25秒上限并短期缓存，不会阻塞库存等基础只读工具。Docker不可用时固定报告仍可用，图表与代码执行明确不可用。
- `artifact_chart`从当前run授权只读数据构造ChartSpec，只有容器成功输出有效PNG、登记成功后才发布事件；`artifact_report`的明细、金额、范围与来源由结构化事实构造，模型不能直接提供数据行。
