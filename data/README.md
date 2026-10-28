# 本机库存快照

用户指定的 `inventory_snapshot.json` 与 `inventory_snapshot.meta.json` 原样复制到此目录；原始数据不纳入Git。配置只指向本项目副本，不依赖 ERP-AGENT 的目录，也不请求来源服务器。

本机 `.env` 配置：

```dotenv
INVENTORY_DATA_SOURCE=local_snapshot
PARTS_DATA_SOURCE=local_snapshot
INVENTORY_SNAPSHOT_PATH=data/inventory_snapshot.json
```

API、MCP、本地工具共用 `backend/app/integrations/inventory_snapshot.py`。副本读取失败时明确失败，不回退为演示库或远端。源文件报告total/pages=0而实际含72条，按保存记录重新分页；来源元数据中的采集时间与完整性unknown保留。

库存ID、物料ID、仓位名称与业务单位保持来源值；零件从partDetail投影。currentQuantity是现存量，safetyStock是安全阈值，安全预警按现存量低于该阈值判断。未提供预留、在途、目标库存和版本，它们及可用量、预计量、目标缺口返回null/显示未知；不能拿采购参考价当有效供应商报价。快照不支持目标补货预览或库存写入。

修改配置后使用PowerShell7重新运行stop.ps1和start.ps1。普通合成数据验收保持原local_seed配置及隔离测试库；不要将这份用户数据放入合成fixtures。
