# 本地采购技能

## 职责与格式

三个技能为静态、版本化的任务指引，不是向量检索或可执行代码：

- `inventory-replenishment/`：库存、在途、目标缺口与服务端补货预览。
- `supplier-comparison/`：供应商状态、有效报价、交期和同范围比较。
- `procurement-report/`：按来源、scope与观察时间形成采购报告。

每个技能的`SKILL.md`包含frontmatter `id`/`version`、适用边界、输入/输出、业务规则引用及信息缺失时的处理；`examples/`有固定案例。`skill_loader.select_skills(task_type, actor)`只按任务加载需要的集合，内容和例子的SHA-256随run保存。

## 调用示例

```python
from backend.app.agent.skill_loader import select_skills

skills = select_skills("inventory", "analyst")
# LoadedSkill(id, version, content_hash, instructions, examples)
```

## 错误与限制

只从仓库`skills/`固定目录读取，拒绝路径穿越；frontmatter id/version缺失会失败。内容hash变化可以识别技能版本内容变化。技能不替代domain/service计算、权限、审批或事实来源；当前不支持联网安装、自动推断偏好或把全部技能注入每次提示。

## 验证

`uv run pytest tests/unit/test_p07_specialists_skills.py -q`
