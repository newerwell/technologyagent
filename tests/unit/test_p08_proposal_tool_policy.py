from backend.app.agent.specialists.policy import load_specialists
from mcp_server.tools.specs import ALL_TOOL_SPECS, MUTATION_PREPARE_SPEC, P08_TOOL_BY_NAME


def test_graph_roles_can_prepare_proposals_but_cannot_execute_raw_business_writes():
    specialists = load_specialists()
    assert "mutation_prepare" in specialists["analyst"].tools
    assert "mutation_prepare" in specialists["order"].tools
    for role in ("analyst", "order"):
        assert not (specialists[role].tools & {"supplier_create", "part_create", "inventory_inbound",
                                               "inventory_outbound", "order_update", "order_update_status"})
    all_names = {spec.name for spec in ALL_TOOL_SPECS}
    assert "mutation_prepare" in all_names
    assert "supplier_create" in P08_TOOL_BY_NAME
    assert MUTATION_PREPARE_SPEC.effect == "write"


def test_order_specialist_discovers_required_order_statistics_and_supplier_parts_reads():
    specialists = load_specialists()
    assert {"order_statistics", "part_by_supplier"} <= specialists["order"].tools
    assert {"order_statistics", "part_by_supplier"}.isdisjoint(specialists["analyst"].tools)


def test_specialist_prompt_distinguishes_preparing_a_proposal_from_business_write():
    from backend.app.agent.graph import build_specialist_system_prompt
    from backend.app.contracts.agent import ExecutorInput
    from backend.app.contracts.common import RequestContext

    request = ExecutorInput(run_id="prompt-p09", thread_id="thread-p09", message="停用供应商 S01",
        ctx=RequestContext("local-owner", "prompt-p09", run_id="prompt-p09", actor="order"), graph_version="v2")
    prompt = build_specialist_system_prompt(request)
    assert "mutation_prepare" in prompt
    assert "等待人工批准" in prompt
    assert "不得直接调用业务写工具" in prompt
