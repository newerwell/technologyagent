from mcp_server.tools.specs import P08_REFERENCE_TOOL_NAMES


def test_p08_declares_exactly_the_reference_tool_set():
    assert len(P08_REFERENCE_TOOL_NAMES) == 23
    assert len(set(P08_REFERENCE_TOOL_NAMES)) == 23
