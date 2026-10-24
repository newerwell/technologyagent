# Agent本地扩展工具

本目录包含主Agent运行时的受控本地工具。P06 `analysis_execute`只使用当前run成功读取的工具结果或同owner/run授权的数据集；其输入在当前registry实例内临时缓存，最多20MiB。代码只提交到隔离Docker容器，输出经校验后由ArtifactService登记并写入artifact_ready事件。

Docker不可用时能力探测会从可用工具列表隐藏 `analysis_execute`；已有/陈旧调用仍返回 `SANDBOX_UNAVAILABLE`，不会回退宿主进程；普通只读工具不依赖Docker。输入/运行/产物失败均作为具体工具错误返回。

验证：`uv run pytest tests/integration/test_sandbox.py tests/integration/test_artifacts.py -q`。
