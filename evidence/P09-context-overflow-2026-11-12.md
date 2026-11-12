# 2026-11-12 实际页面 HTTP 400 修复

状态：本次故障已修复并通过实际页面回归；不是 P09 最终验收，不创建阶段标签。完整 offline/browser/固定排程 live/干净检出仍须按剩余计划执行。

## 现场与根因

主仓库基线为 `6e8576c12fb126c40f10ccdb53c671aed6b62758`。实际占用 8030/3030/9030 的服务从旁边的 `technologyagent-deepseek-cache` 目录启动，该目录基线为 `db805eacf7eb38b60e2a2243ba30502b2e08d935`，分支 `codex/deepseek-cache`。两个目录分别保留共同修复，不将缓存功能整体合入 main。

原问题“哪些零件要补货”经实际 MCP 复现，模型明确返回：最大上下文 1,048,576 tokens，请求消息达 1,202,189 tokens。原因是每条派生事实重复携带整页来源列表，工具消息又发送这些内部事实；工具原始业务结果约 30KB，模型工具消息却达 2,569,566 字节。修复工具序列化后，语义评审的同类重复仍产生 3,101,380 字节的用户消息，需要同时修复两处。

## 修改边界

1. 新增 `tool_messages.serialize_tool_result`，供主图及独立 v1/v2 图使用；保留完整业务 data、error、分页、来源、快照和 dataset 元数据，只不向模型再次发送派生的 `meta.evidence_refs`。原 ToolResult、state、持久评审快照和硬校验不变。
2. 语义评审把相同来源列表存到 `source_ref_groups`，每条事实引用组键；测试逐条还原并比较原始事实/来源，保留单位和物料、仓库、报价、供应商范围。
3. 快照缺失目标等字段时，提示完成分页并说明未知，不能补 0；无有效输出仍失败。缓存分支提示词版本改为 `ta-v2-base-2` / `ta-semantic-review-2`；main 仅更新原系统提示，不引入缓存模块。
4. 修正明确具名查询的记录数识别，例如 `inventory_warning total=0`、“返回的记录条数为0（单位：条预警记录）”；物料数量与金额不能借用记录数通过。无范围或错误记录数仍失败。

## 反例和回归

- 修复前：72 行合成数据的工具消息 3,107,395 字节，原 data 18,932 字节；三个图入口的反例均失败。语义评审合成请求 2,971,087 字节，体积断言失败。
- 记录数第一组反例 3 failed / 5 passed；后续实际措辞及错误物料数量反例 2 failed / 9 passed。最终 11 项记录数正反例通过。
- 修复后：实际工具消息约 22KB；成功语义评审消息约 187KB。未截断业务记录，未删除服务器事实，未放宽审批、单位、预算或来源检查。
- 缓存运行目录：`python -m pytest -p no:cacheprovider --basetemp .runtime/pytest-context-complete-unit-20261112 tests/unit -q -rs`，**567 passed，exit 0**。Python 3.13.14。
- Mongo 定向集成分别 **31 passed、15 passed、5 passed**，均 exit 0；三批文件有重叠，不累计为唯一用例总数。最后 5 项为最终计数识别修复后的 harness / snapshot routes 回归。
- 主仓库共同修复：工具消息、记录数、快照回答、语义评审、模型观测、版本隔离、事实与来源等 9 个定向单测文件，**77 passed，exit 0**。包含用户已有未提交事实处理改动；共同代码同时在没有这些改动的缓存分支通过完整单测。
- 集成仅用 `127.0.0.1:27028` 的隔离 `ta-rs`，fake，`technologyagent_test_*` 数据库。没有重置日常库或调用真实 ERP。
- 启动过程前端 production build 与 TypeScript 检查通过。

Python `0xc0000142` 在本轮受限执行环境中出现；同一虚拟环境以正常权限执行测试和启动成功，因此没有重装 Python、修改系统安全配置或删除现有环境。此结论不替代 Windows 全局 DLL 诊断。

## 实际浏览器验收

在实际 `http://127.0.0.1:3030/chat` 用浏览器输入原问题，无业务响应 mock：

- HTTP 200，run `run_cb08dbe044664054ac9e128df5ec5c33`。
- SSE 终态和持久 run 均 `completed`，`review_passed=true`，页面评审 **9/9**，无 provider error。
- `inventory_page` 两页读取全部 72 行；回答明确缺失字段未知，不能计算目标补货清单。安全预警不能证明目标库存充足。
- 旧失败会话保持历史原状，未伪造 completed；新建会话重新提问即可使用修复。

私有验收文件位于运行目录 `.runtime`，含用户数据，不提交。文件与 SHA256：

| 文件 | SHA256 |
|---|---|
| chat-fix-browser-2026-11-12T07-46-53-453Z.json | 12ce48df0726d22c910fb66f80f2580f0e0e6925ea302a9b0f6069404158fba6 |
| chat-fix-browser-2026-11-12T07-46-53-453Z.png | 25e4513198c8d935638e982fc7c5b7f26560dc7198ebfa2b348e5352cd921a2a |

原始库存 SHA256 `dd2e208d2144fabed9372f20d8df57dbf530a239a20811e0c308b2df3b093248`；metadata SHA256 `fe6467f7d533cb50eed810188b7bcdb1fe28321f9a850c7db19a37d4b84f1ea5`，修复前后相同。业务集合 parts、suppliers、quotes、inventories、drafts、orders、operations、approvals、receipts、inventory_movements 的完整 BSON 规范化哈希前后相同；当前 dev 中这些集合原本均为 0 条，库存来自文件，未通过 reset 取得此结果。仅新增测试对话与运行事件。

## 当前启动与交付边界

运行目录不含 `.env` 或库存副本，启动时从主仓库本机配置加载，库存路径指向主仓库 `data/inventory_snapshot.json` 的绝对路径。不能在运行目录直接假定存在 `.env`：

```powershell
# 在 technologyagent-deepseek-cache 目录，用 PowerShell 7
. .\scripts\import_dotenv.ps1
Import-DotEnv -Path '..\technologyagent\.env'
$env:MODEL_MODE='live'
$env:MONGODB_DATABASE='technologyagent_dev'
$env:MONGODB_URI='mongodb://127.0.0.1:27027/?replicaSet=ta-rs&directConnection=true'
$env:API_PORT='8030'
$env:FRONTEND_PORT='3030'
$env:MCP_PORT='9030'
$env:INVENTORY_DATA_SOURCE='local_snapshot'
$env:PARTS_DATA_SOURCE='local_snapshot'
$env:INVENTORY_SNAPSHOT_PATH=(Resolve-Path '..\technologyagent\data\inventory_snapshot.json').Path
.\stop.ps1
.\start.ps1
```

此为本机现有目录的启动记录，不是可移植部署说明。其他来源沿用原本配置，不复制或提交密钥。主仓库已有未提交 fact_checks / implementation README 改动及无关文件保留，采用显式路径与局部暂存共同修复。真实 ERP 未验证；本轮没有验证缓存收益，也没有执行 P09 固定 13 条 live 总门禁，不据此宣布 P09 完成。
