import asyncio
import threading
from types import SimpleNamespace

import pytest

from backend.app.contracts.artifacts import SandboxJob
from backend.app.contracts.common import RequestContext
from backend.app.sandbox.runner import DockerSandbox


class _Stream:
    def __init__(self):
        self.closed = False

    def write(self, payload):
        return len(payload)

    def close(self):
        self.closed = True


class _API:
    def __init__(self):
        self.started = threading.Event()

    def exec_create(self, _container_id, command, **_kwargs):
        return {"Id": "upload" if command[1] == "-c" else "analysis"}

    def exec_start(self, _exec_id, **kwargs):
        if kwargs.get("socket"):
            return _Stream()
        if kwargs.get("detach"):
            self.started.set()
        return None

    def exec_inspect(self, exec_id):
        if exec_id == "upload":
            return {"Running": False, "ExitCode": 0}
        return {"Running": True, "ExitCode": None}


class _Container:
    id = "container-lifecycle"
    attrs = {
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Binds": [], "Mounts": [],
                       "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                       "Memory": 512 * 1024 * 1024, "NanoCpus": 1_000_000_000, "PidsLimit": 64,
                       "Tmpfs": {"/work": "rw", "/out": "rw", "/tmp": "rw"}},
        "Config": {"User": "65532:65532"}, "Mounts": [],
    }

    def __init__(self):
        self.killed = False
        self.removed = False

    def start(self):
        pass

    def reload(self):
        pass

    def kill(self):
        self.killed = True

    def remove(self, force=False):
        self.removed = True


class _DockerClient:
    def __init__(self):
        self.api = _API()
        self.container = _Container()
        self.containers = SimpleNamespace(create=lambda *args, **kwargs: self.container,
                                          get=lambda _id: self.container)


@pytest.mark.asyncio
async def test_cancelling_graph_await_kills_and_reaps_only_its_sandbox_job():
    docker = _DockerClient()
    sandbox = DockerSandbox(docker_client=docker)
    ctx = RequestContext(owner_id="owner", request_id="req", run_id="run-cancel")
    job = SandboxJob(code="while True: pass", output_allowlist=["out.csv"], timeout_seconds=5)

    task = asyncio.create_task(sandbox.execute(job, ctx))
    assert await asyncio.to_thread(docker.api.started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert docker.container.killed
    assert docker.container.removed
