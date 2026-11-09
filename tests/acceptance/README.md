# 独立完整备份恢复验收

此目录不属于普通tests/e2e。运行frontend/playwright.clean.config.ts，workers=1、retries=0，仅允许显式P09_CLEAN_ACCEPTANCE=1、全新clean测试库、专用27028与独立storage、fake/local_seed。

clean-restore.spec.ts复用R8浏览器动作：三报告真实下载，订单55→60待审，停止应用后用真实backup/restore脚本备份全库与storage，恢复到全新restored库与目录。启动前对所有集合的完整规范文档SHA和数量、artifact owner/run/storage/内容逐项比较；再恢复同一thread/run/审批版本，批准及重放，只新增一单/一个成功operation。恢复后的下载再次核对相同字节/SHA。

scripts.p09_restore_facts只读取严格命名的专用测试目标，不接入产品流或改变业务事实。归档/数据库/日志/facts只留忽略的.runtime。C06仅证明配置可收集、guard通过；F18仍须C09在从已推送源码创建的新检出实际执行，不把此用例存在当成通过。
