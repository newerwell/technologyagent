import os
import pytest
import docker

from backend.app.contracts.artifacts import SandboxJob
from backend.app.contracts.common import RequestContext
from backend.app.sandbox.runner import DockerSandbox


@pytest.mark.asyncio
async def test_docker_sandbox_rejects_outputs_outside_allowlist_and_cleans_up():
    available, reason = await DockerSandbox().available()
    if not available:
        if os.environ.get("P06_REQUIRED") == "1":
            pytest.fail(f"P06 requires the built Docker sandbox image and a running daemon: {reason}")
        pytest.skip(f"sandbox image unavailable: {reason}")
    sandbox = DockerSandbox()
    ctx = RequestContext(owner_id="test", request_id="test", run_id="run_test")
    result = await sandbox.execute(SandboxJob(
        code="from pathlib import Path\nPath('/out/report.csv').write_text('名称,金额(分)\\n刹车片,66000', encoding='utf-8')",
        output_allowlist=["report.csv"], timeout_seconds=10), ctx)
    assert result.exit_code == 0 and not result.timed_out, result.diagnostics
    assert result.outputs, result.diagnostics
    assert result.outputs[0].content.decode("utf-8").startswith("名称,金额(分)")
    assert "container inspect passed" in result.diagnostics
    assert not docker.from_env().containers.list(all=True, filters={"label": "technologyagent.run_id=run_test"})


@pytest.mark.asyncio
async def test_docker_sandbox_times_out_instead_of_falling_back_to_host():
    available, reason = await DockerSandbox().available()
    if not available:
        if os.environ.get("P06_REQUIRED") == "1":
            pytest.fail(f"P06 requires the built Docker sandbox image and a running daemon: {reason}")
        pytest.skip(f"sandbox image unavailable: {reason}")
    result = await DockerSandbox().execute(SandboxJob(
        code="while True: pass", output_allowlist=["out.csv"], timeout_seconds=2),
        RequestContext(owner_id="test", request_id="test", run_id="run_test"))
    assert result.timed_out and result.exit_code == 124 and result.outputs == []
    assert not docker.from_env().containers.list(all=True, filters={"label": "technologyagent.run_id=run_test"})


@pytest.mark.asyncio
async def test_docker_sandbox_has_no_network_and_rejects_extra_or_oversized_outputs():
    available, reason = await DockerSandbox().available()
    if not available:
        if os.environ.get("P06_REQUIRED") == "1":
            pytest.fail(f"P06 requires the built Docker sandbox image and a running daemon: {reason}")
        pytest.skip(f"sandbox image unavailable: {reason}")
    ctx = RequestContext(owner_id="test", request_id="test", run_id="run_test")
    no_network = await DockerSandbox().execute(SandboxJob(
        code="import socket\ntry:\n socket.create_connection(('1.1.1.1',80),timeout=1); state='connected'\nexcept OSError: state='blocked'\nopen('/out/status.csv','w').write(state)",
        output_allowlist=["status.csv"], timeout_seconds=5), ctx)
    assert no_network.exit_code == 0 and no_network.outputs[0].content == b"blocked"
    extra_file = await DockerSandbox().execute(SandboxJob(
        code="from pathlib import Path\nPath('/out/allowed.csv').write_text('ok')\nPath('/out/extra.csv').write_text('unexpected')",
        output_allowlist=["allowed.csv"], timeout_seconds=5), ctx)
    assert extra_file.exit_code != 0 and extra_file.outputs == []
    too_large = await DockerSandbox().execute(SandboxJob(
        code="open('/out/large.csv','wb').write(b'x'*(21*1024*1024))",
        output_allowlist=["large.csv"], timeout_seconds=10), ctx)
    assert too_large.exit_code != 0 and too_large.outputs == []
