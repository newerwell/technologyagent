# P06 图表、报告与执行沙箱

本模块负责固定图表/报告格式、Docker隔离任务和容器输出安全收集。业务服务只传入已授权的最小数据；容器每次单独创建并销毁。

- `build_chart_spec(kind, data, source_refs)` 验证 bar/line/pie 输入；`render_chart_in_sandbox(spec, sandbox, ctx)` 在含 `Noto Sans CJK JP` 的固定镜像中生成PNG。金额以整数分输入并按元显示；line要求至少两个有序真实日期；pie拒绝负数和全零。
- `build_report_spec(format, analysis)` 从同一 `AnalysisResult` 生成md/html/csv/json；CSV含UTF-8 BOM并防公式注入，HTML转义，JSON保留整数分。
- `DockerSandbox.execute(SandboxJob, ctx)` 执行最多30秒；Docker镜像为 `technologyagent-sandbox:0.1.0`。基础镜像digest、Matplotlib及其Python依赖、Noto CJK字体包均固定。启动：`docker build -t technologyagent-sandbox:0.1.0 -f backend/app/sandbox/Dockerfile backend/app/sandbox`。
- 容器：无网络、无宿主挂载、只读根、非root、cap_drop ALL、no-new-privileges、512MiB/1CPU/pids64；/work与/out为限额tmpfs。inspect不符合策略时拒绝启动；Docker失败不回退本机shell。
- `collect_archive` 只接受平面白名单的常规文件，拒绝链接、路径穿越、重复、超额和不支持格式；不会调用 `extractall`。
- `analysis_execute`仅传入当前run授权数据和白名单输出；模型Key、MCP令牌、`.env`和仓库不会进入容器。
- 验证：`uv run pytest tests/unit/test_chart_specs.py tests/unit/test_report_rendering.py tests/unit/test_sandbox_collectors.py -q` 和 `uv run pytest tests/integration/test_sandbox.py -q`；集成测试要求Docker可用并先构建镜像。
