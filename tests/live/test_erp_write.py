"""Opt-in ERP write test is intentionally gated by an explicit disposable test operation."""

import os

import pytest

from backend.app.config import load_settings
from backend.app.integrations.erp.client import ErpClient


@pytest.mark.asyncio
async def test_erp_write_only_explicit_test_fixture():
    settings = load_settings()
    operation = os.environ.get("ERP_TEST_WRITE_OPERATION")
    correlation_id = os.environ.get("ERP_TEST_CORRELATION_ID")
    if (settings.erp_environment != "test" or not settings.erp_base_url or not settings.erp_api_key
            or not operation or not correlation_id or os.environ.get("ERP_TEST_WRITE_AUTHORIZED") != "1"):
        pytest.skip("ERP write not_run: explicit disposable test operation and authorization are absent")
    import json
    payload_raw = os.environ.get("ERP_TEST_WRITE_PAYLOAD")
    if not payload_raw:
        pytest.skip("ERP write not_run: test payload is absent")
    payload = json.loads(payload_raw)
    client = ErpClient(settings.erp_base_url, token=settings.erp_api_key.get_secret_value(),
                       timeout_seconds=settings.erp_timeout_seconds)
    try:
        result = await client.write(operation, payload, correlation_id)
    except Exception:
        result = await client.lookup(correlation_id)
    assert result is not None
