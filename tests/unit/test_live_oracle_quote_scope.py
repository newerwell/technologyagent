import pytest

from scripts.live_acceptance import _invalid_quote_conclusion_issues


@pytest.fixture
def quote_facts():
    return [
        (
            {"name": "quote_list", "args_summary": {"part_id": "P003"}},
            {"records": [
                {"part_id": "P003", "supplier_id": "S03", "is_valid": False},
            ]},
        ),
        (
            {"name": "quote_list", "args_summary": {"part_id": "P002"}},
            {"records": [
                {"part_id": "P002", "supplier_id": "S03", "is_valid": True},
            ]},
        ),
    ]


@pytest.mark.parametrize(
    ("answer", "expected_violation"),
    [
        ("P003没有有效报价；S03单价7元但停用且过期，不可用于采购建议。", False),
        ("P003没有有效报价。建议先获取P003有效报价后再比价。", False),
        ("P003没有有效报价。P002推荐S03。", False),
        ("P003暂无有效报价。推荐先向供应商询价。", False),
        ("P003暂无有效报价。S03报价已失效，但仍建议采购。", True),
        ("P003无有效报价。仍推荐S03作为P003的供应商。", True),
        ("P003暂无有效报价。S03可用于采购。", True),
        ("P003暂无有效报价。P002推荐S03。P003也可按S03报价下单。", True),
    ],
)
def test_quote_claim_is_bound_to_part_supplier_and_polarity(answer, expected_violation, quote_facts):
    issues = _invalid_quote_conclusion_issues(answer, quote_facts)
    assert bool(issues) is expected_violation, (answer, issues)


def test_explanatory_readonly_paragraph_does_not_inherit_invalid_supplier():
    answer = (
        "P003目前没有有效报价。\n"
        "- 唯一报价来自S03，报价已失效且供应商已停用，因此不满足有效报价条件。\n\n"
        "如需采购P003，需要先取得有效报价；当前只读版本也不会代为下单。"
    )

    assert _invalid_quote_conclusion_issues(answer, [
        ({"name": "quote_list", "args_summary": {"part_id": "P003"}}, {"records": [
            {"part_id": "P003", "supplier_id": "S03", "is_valid": False},
        ]}),
    ]) == []
