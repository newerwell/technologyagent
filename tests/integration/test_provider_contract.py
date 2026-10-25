"""P08 contract checks for local providers and an HTTP-shaped ERP simulator."""

import httpx
import pytest

from backend.app.integrations.erp.client import ErpClient
from backend.app.integrations.erp_provider import ErpProvider
from backend.app.integrations.local_provider import LocalProvider
from backend.app.integrations.business_provider import ProviderUnavailable, UnsupportedProviderOperation


class FakeReader:
    async def supplier_page(self, **params):
        return {"records": [{"id": "S01", "name": "本地"}], "total": 1}


@pytest.mark.asyncio
async def test_provider_contract_local_snapshot_and_http_simulator():
    local = LocalProvider({"catalog": FakeReader()}, snapshot=True)
    local_result = await local.query("supplier_page", page=1, page_size=20)
    assert local_result["records"][0]["id"] == "S01"
    with pytest.raises(UnsupportedProviderOperation):
        await local.mutate("supplier_create", {"code": "X"}, approved=True)

    seen = []
    def handler(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"records": [{"supplier_id": 8, "supplier_name": "ERP"}], "total": 1})
    erp = ErpProvider(ErpClient("https://simulator.test", transport=httpx.MockTransport(handler)),
                      read_actions=frozenset({"supplier_page"}))
    remote_result = await erp.query("supplier_page", page=1, page_size=20)
    assert remote_result["records"][0]["supplier_id"] == 8
    assert seen == [("GET", "/supplier_page")]
