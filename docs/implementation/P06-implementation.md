# P06 图表、报告与沙箱 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available; otherwise follow the task checklist directly. Implement only this stage.

**Goal:** 从真实业务数据生成可下载的三类图表与四种报告，并能隔离执行分析代码。
**Architecture:** 宿主协调授权数据和产物，容器执行绘图/分析，产物只按artifact_id提供访问。
**Tech Stack:** Docker SDK、固定Python镜像、Matplotlib；既有UI/API与Mongo。
**Spec:** [P06](../specs/P06-artifacts-sandbox.md)、[接口映射](./INTERFACES.md)第6节。

## Global Constraints

30秒/512MiB/1CPU/pids64/输出20MiB；非root、只读根、禁网、无宿主挂载/socket；Docker失败不回退宿主执行；本阶段主Agent可用analysis_execute，P07再收紧。

## Review Focus

任意路径下载→T01；三类型实际同一图→T02；报告数值/转义→T03；资源耗尽与路径穿越→T04/T05；仅生成不打开文件→T06。

### P06-T01：产物端口、存储与下载

**Files:** Create `contracts/artifacts.py`、`ports/artifacts.py`、`repositories/artifacts.py`、`services/artifacts.py`、`api/artifacts.py`；Test `tests/integration/test_artifacts.py`。
**Interfaces:** ArtifactService.register/open按映射；存储key由服务器产生，用户文件名只是展示。

- [ ] 写ownerB下载A404、未知ID404、未就绪409、路径字符串422测试；接口不接受../或磁盘路径代替ID。
- [ ] 本地存储使用storage/<owner>/<run>/<generated-id>，写临时文件后原子完成；Artifact状态ready后才发artifact_ready。
- [ ] 校验大小/MIME/允许后缀与实际内容；下载Response设置正确Content-Type和Content-Disposition，不直接暴露storage路径。
- [ ] 运行测试并确认文件元数据和实际文件缺失时明确错误，不能返回空200。

### P06-T02：三类真实图表

**Files:** Create `sandbox/charts.py`、`tests/unit/test_chart_specs.py`、`tests/integration/test_chart_output.py`。
**Interfaces:** ChartSpec(kind,labels,series,title,source_refs)；bar/line/pie分别实现明确分支。

- [ ] bar输入S01/S02的55件总额66000/60500分，轴显示元；line必须有>=2个有序时间点；pie非负且总量>0。
- [ ] 未支持类型返回VALIDATION_ERROR，不静默降为bar；空数据返回说明，不画“全零但看似成功”的图。
- [ ] 生成脚本使用预装中文字体和固定字号/画布，检查标签不裁切；加入source摘要但不泄露原始私人数据。
- [ ] 单测输入/字段，集成生成后用图片解码核对文件非空/尺寸；三图人工打开确认类型与标注。

### P06-T03：四种结构化报告

**Files:** Create `sandbox/reports.py`、`tests/unit/test_report_rendering.py`、`tests/integration/test_report_outputs.py`。
**Interfaces:** AnalysisResult(summary,table,source_refs,scope,recommendations,missing_fields)→ReportSpec(format,content)；支持md/html/csv/json。

- [ ] 用同一AnalysisResult渲染四格式；JSON金额分、CSV/表格标单位，核心记录和金额一致。
- [ ] HTML转义用户文本；CSV UTF-8 BOM，并对以=,+,-,@开头的字符串单元格加安全前缀，数值字段正常输出。
- [ ] markdown/html有范围、时间、数据、建议和缺项；CSV逐行数据外附受控元信息，JSON保存结构化source_refs。
- [ ] 测试含中文/逗号/换行/公式文本，用解析器回读并核对值；不把“文件已生成”文本当产物存在。

### P06-T04：容器后端与输出收集

**Files:** Create `ports/sandbox.py`、`sandbox/{runner,collectors}.py`、`sandbox/Dockerfile`、`tests/integration/test_sandbox.py`。
**Interfaces:** SandboxPort.execute(job,ctx)->SandboxResult；创建/上传/执行/收集/销毁全链路。

- [ ] 镜像构建时装依赖及中文字体并固定版本；每run创建独立容器，输入通过归档复制到临时工作区，不挂载宿主文件夹。
- [ ] read_only根文件系统、非root用户、tmpfs工作区、禁网、cap_drop、no_new_privileges及资源上限；用inspect核对实际配置。
- [ ] collect只接收允许文件，拒绝绝对路径、..、符号链接/硬链接及超过20MiB的总量；安全解析归档，不直接extractall到宿主。
- [ ] finally销毁容器；超时、OOM、退出非0按真实结果返回。测试无限循环/联网/文件越界/输出超限及正常CSV，宿主无执行回退。

### P06-T05：受限分析工具接入

**Files:** Create `agent/tools/analysis.py`；Modify registry、ready、bootstrap；Test `tests/integration/test_analysis_execute.py`。
**Interfaces:** analysis_execute输入code/input_dataset_ids/output_allowlist；数据ID先按owner/run授权转换成容器文件。

- [ ] 主Agent从已成功工具结果选择数据，宿主只传授权数据与必要元信息，不传.env/完整仓库/模型Key/MCP令牌。
- [ ] 工具执行前扣预算与检查cancel；Docker阻塞API通过有界线程封装，不堵住事件循环；结果收集后ArtifactService登记并发事件。
- [ ] 本阶段allowed_actors=['main']，P07改分析专家；Docker不可用只禁对应能力，普通查询继续。
- [ ] 正常分析输出CSV可下载；伪造其他run数据ID失败；沙箱无法连宿主业务服务，工具错误保留具体code。

### P06-T06：页面、文件质量与交付

**Files:** Create `frontend/src/components/artifacts/{ArtifactCard,ChartPreview}.tsx`、`tests/e2e/artifacts.spec.ts`、`evidence/P06.md`。
**Interfaces:** 只从artifact_ready/元信息创建卡片，下载仍鉴权；图像文件以服务端可访问路由预览。

- [ ] UI展示文件名/格式/来源、下载失败和图表预览；禁止模型拼接任意路径直接变下载链接。
- [ ] 打开三类图与四格式文件检查中文/数据/裁切；价格比较只含有效S01/S02，55件总价660/605元。
- [ ] P06-A01..A07记录容器inspect、故障结果、产物内容和人工打开步骤；保留小型无敏感示例，运行临时文件清理。
- [ ] 更新模块README、锁定镜像与依赖记录，上传并核对`phase-p06`后停止。
