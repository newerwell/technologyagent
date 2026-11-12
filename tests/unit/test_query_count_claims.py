"""Query row counts stay bound to their tool, including parenthetical labels."""

import pytest

from backend.app.agent.evidence import collect_evidence, validate_business_claims
from backend.app.ports.tools import ToolResult


def _facts():
    result = []
    for name, total in (("inventory_page", 72), ("inventory_warning", 0)):
        result.extend(collect_evidence(name, ToolResult(
            ok=True, call_id=name, meta={"data_source": "local_snapshot"},
            data={"records": [], "total": total,
                  "source_refs": [{"entity": "inventory_snapshot", "id": "snapshot"}]}), call_id=name))
    return result


@pytest.mark.parametrize("answer,field", [
    ("安全库存预警查询（全快照，不分页）返回0条记录。", "warning_count"),
    ("库存快照分页查询（inventory_page）的total字段为72条库存记录。", "inventory_count"),
    ("inventory_warning返回records=[]、total=0。", "warning_count"),
    ("inventory_warning全仓查询返回的记录条数为0（单位：条预警记录，非金额）。", "warning_count"),
])
def test_explicit_query_count_keeps_its_metric(answer, field):
    checked = validate_business_claims(answer, _facts())
    assert checked.passed, checked.violations
    assert any(fact.get("field") == field for fact in checked.cited_facts)


@pytest.mark.parametrize("answer", [
    "inventory_page total=0。", "库存预警共72条。", "inventory_page总额72分。",
    "返回0条记录。", "inventory_warning为0元。", "inventory_page单价72条库存记录。",
    "inventory_warning物料数量为0套。",
])
def test_wrong_or_unscoped_query_count_is_not_authorized_by_another_tool(answer):
    assert not validate_business_claims(answer, _facts()).passed
