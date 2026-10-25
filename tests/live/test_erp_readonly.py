"""Opt-in real ERP read-only smoke; an absent authorized test endpoint is skipped/not_run."""

import os

import pytest

from backend.app.config import load_settings
from backend.app.integrations.erp.client import ErpClient


@pytest.mark.asyncio
async def test_erp_readonly_explicit_test_scope():
    settings = load_settings()
    operation = os.environ.get("ERP_TEST_READ_OPERATION")
    if settings.erp_environment != "test" or not settings.erp_base_url or not settings.erp_api_key or not operation:
        pytest.skip("ERP live read not_run: no explicit ERP test endpoint/operation/key")
    client = ErpClient(settings.erp_base_url, token=settings.erp_api_key.get_secret_value(),
                       timeout_seconds=settings.erp_timeout_seconds)
    result = await client.read(operation, {})
    assert isinstance(result, dict)
