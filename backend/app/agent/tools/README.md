# Agent本地扩展工具

本目录包含主Agent运行时的受控本地工具。P06 `analysis_execute`只使用当前run成功读取的工具结果或同owner/run授权的数据集；其输入在当前registry实例内临时缓存，最多20MiB。代码只提交到隔离Docker容器，输出经校验后由ArtifactService登记并写入artifact_ready事件。

成功的只读业务结果会在当前owner/run registry内缓存为授权数据集，并保留原始 `call_id`、参数、scope、as_of 与记录级source_refs。`artifact_report`只接受数据集ID和格式，报告正文/金额/来源由服务端事实派生；`artifact_chart`只接受数据集ID及bar/line/pie类型，图表经受控Docker渲染后才登记并发布 `artifact_ready`。模型不能提交自造行或金额。

Docker不可用时能力探测会从可用工具列表隐藏 `analysis_execute` 和 `artifact_chart`；陈旧调用明确返回 `SANDBOX_UNAVAILABLE`，不会回退宿主进程；普通只读工具和受控固定报告不依赖Docker。输入/运行/产物失败均作为具体工具错误返回。授权缓存总量与单数据集均有上限，registry关闭时释放底层连接。

验证：`uv run pytest tests/integration/test_sandbox.py tests/integration/test_artifacts.py -q`。
