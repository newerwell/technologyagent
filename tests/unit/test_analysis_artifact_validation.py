import pytest

from backend.app.contracts.artifacts import AuthorizedDataset
from backend.app.services.analysis_artifacts import build_analysis_result


def dataset(*, warehouse_id: str = "W01", line_warehouse: str = "W01", quantity: int = 55,
            quote_quantity: int = 55) -> AuthorizedDataset:
    return AuthorizedDataset(
        dataset_id="ds-test", owner_id="owner", run_id="run", call_id="call-1",
        tool_name="replenishment_preview",
        arguments={"part_ids": ["P001"], "warehouse_id": warehouse_id, "max_lead_days": 7},
        data_source="local_seed", scope="warehouse:" + warehouse_id, as_of="2026-10-24T10:00:00+00:00",
        source_refs=[
            {"entity": "inventory", "id": "I001", "call_id": "call-1"},
            {"entity": "quote", "id": "Q01", "call_id": "call-1"},
        ],
        data={"lines": [{"part_id": "P001", "warehouse_id": line_warehouse, "quantity": quantity,
                         "candidate_quotes": [{"quote_id": "Q01", "supplier_id": "S01",
                                               "supplier_name": "供应商一", "unit_price_cents": 1200,
                                               "suggested_quantity": quote_quantity,
                                               "line_total_cents": quote_quantity * 1200,
                                               "lead_days": 5, "valid_until": "2026-11-01T00:00:00+00:00"}]}]},
    )


def test_formal_report_rejects_result_outside_requested_warehouse():
    with pytest.raises(ValueError, match="warehouse"):
        build_analysis_result(dataset(line_warehouse="W02"))


def test_formal_report_rejects_quote_quantity_different_from_preview_quantity():
    with pytest.raises(ValueError, match="quantity"):
        build_analysis_result(dataset(quote_quantity=54))
