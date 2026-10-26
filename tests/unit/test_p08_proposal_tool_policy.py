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
