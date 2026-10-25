"""每次独立Docker容器执行；Docker故障明确失败，绝不回退宿主shell。"""
from __future__ import annotations

import asyncio
import io
import json
import socket
import struct
import time
import tarfile
import threading
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from backend.app.contracts.artifacts import SandboxJob, SandboxResult
from backend.app.contracts.common import RequestContext
from backend.app.agent.budget import RunBudget, RunDeadlineExceeded
from backend.app.sandbox.collectors import collect_archive, MAX_OUTPUT_BYTES

IMAGE = "technologyagent-sandbox:0.1.0"


@dataclass
class _JobControl:
    job_id: str
    run_id: str
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    container_id: str | None = None

    def attach(self, container_id: str) -> bool:
        with self.lock:
            self.container_id = container_id
            return not self.cancelled.is_set()

    def current_container(self) -> str | None:
        with self.lock:
            return self.container_id


def _write_all(stream: Any, payload: bytes) -> None:
    """Write all bytes to either a socket or Docker's file-like SocketIO."""
    sendall = getattr(stream, "sendall", None)
    if callable(sendall):
        sendall(payload)
        return
    write = getattr(stream, "write", None)
    if not callable(write):
        raise TypeError("Docker exec stream does not support writes")
    offset = 0
    while offset < len(payload):
        written = write(payload[offset:])
        if not isinstance(written, int) or written <= 0:
            raise OSError("Docker exec stream made no write progress")
        offset += written
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _upload_files(client: Any, container_id: str, files: dict[str, bytes]) -> None:
    bootstrap = (
        "import os,struct,sys\n"
        "def take(n):\n b=bytearray()\n while len(b)<n:\n  p=sys.stdin.buffer.read(n-len(b))\n  if not p: raise EOFError()\n  b.extend(p)\n return bytes(b)\n"
        "while True:\n n=struct.unpack('!H',take(2))[0]\n if n==0: break\n name=take(n).decode('ascii')\n size=struct.unpack('!Q',take(8))[0]\n if name!='code.py' and not name.startswith('data/'): raise ValueError('bad input name')\n path='/work/'+name\n os.makedirs(os.path.dirname(path),exist_ok=True)\n with open(path,'wb') as f: f.write(take(size))\n"
    )
    exec_id = client.api.exec_create(container_id, ["python", "-c", bootstrap], stdin=True, stdout=False, stderr=True)["Id"]
    stream = client.api.exec_start(exec_id, socket=True)
    try:
        for name, content in files.items():
            encoded = name.encode("ascii")
            _write_all(stream, struct.pack("!H", len(encoded)) + encoded + struct.pack("!Q", len(content)) + content)
        _write_all(stream, b"\x00\x00")
        try:
            stream.shutdown(socket.SHUT_WR)
        except (AttributeError, OSError, ValueError):
            pass
    finally:
        stream.close()
    inspect = client.api.exec_inspect(exec_id)
    deadline = time.monotonic() + 3.0
    while inspect.get("Running") and time.monotonic() < deadline:
        time.sleep(0.05)
        inspect = client.api.exec_inspect(exec_id)
    if inspect.get("ExitCode") != 0:
        raise RuntimeError("Docker rejected sandbox input transfer")


class DockerSandbox:
    def __init__(self, image: str = IMAGE, docker_client: Any = None) -> None:
        self._image, self._docker = image, docker_client
        self._thread_local = threading.local()
        self._jobs: dict[str, _JobControl] = {}
        self._jobs_lock = threading.Lock()

    def _client(self):
        if self._docker is None:
            import docker
            client = getattr(self._thread_local, "client", None)
            if client is None:
                client = docker.from_env(timeout=35)
                self._thread_local.client = client
            return client
        return self._docker

    async def available(self) -> tuple[bool, str]:
        try:
            client = await asyncio.to_thread(self._client)
            await asyncio.to_thread(client.images.get, self._image)
            await asyncio.to_thread(client.ping)
            return True, "pinned sandbox image and Docker daemon available"
        except Exception as exc:
            return False, f"{type(exc).__name__}: sandbox image or daemon unavailable"

    async def execute(self, job: SandboxJob, ctx: RequestContext, budget: RunBudget | None = None) -> SandboxResult:
        limit = float(job.timeout_seconds)
        if budget is not None:
            await budget.check_cancelled()
            await budget.check_active()
            limit = min(limit, budget.remaining_seconds)
        if limit <= 0:
            raise RunDeadlineExceeded("run active deadline exceeded before sandbox execution")
        job_id = uuid4().hex
        control = _JobControl(job_id=job_id, run_id=ctx.run_id or "")
        with self._jobs_lock:
            self._jobs[job_id] = control
        worker = asyncio.create_task(asyncio.to_thread(self._execute_sync, job, ctx, control))
        try:
            return await asyncio.wait_for(asyncio.shield(worker), timeout=limit)
        except asyncio.TimeoutError:
            control.cancelled.set()
            await self._terminate(control)
            await self._drain_worker(worker)
            if budget is not None:
                await budget.check_active()
            return SandboxResult(exit_code=124, timed_out=True, diagnostics="sandbox lifecycle deadline exceeded; job terminated")
        except asyncio.CancelledError:
            control.cancelled.set()
            await asyncio.shield(self._terminate(control))
            await asyncio.shield(self._drain_worker(worker))
            raise
        finally:
            with self._jobs_lock:
                self._jobs.pop(job_id, None)

    async def _terminate(self, control: _JobControl) -> None:
        container_id = control.current_container()
        if not container_id:
            return
        try:
            await asyncio.to_thread(self._terminate_sync, container_id)
        except Exception:
            pass

    async def _drain_worker(self, worker: asyncio.Task) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(worker), timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            # The job container has been killed; a slow Docker transport must not
            # keep the caller's run alive beyond its deadline.
            pass

    def _terminate_sync(self, container_id: str) -> None:
        client = self._client()
        try:
            container = client.containers.get(container_id)
        except Exception:
            return
        try:
            container.kill()
        except Exception:
            pass
        try:
            container.remove(force=True)
        except Exception:
            pass

    def _execute_sync(self, job: SandboxJob, ctx: RequestContext, control: _JobControl) -> SandboxResult:
        client = self._client()
        container = None
        inputs: dict[str, bytes] = {"code.py": job.code.encode("utf-8")}
        input_total = len(inputs["code.py"])
        for item in job.input_files:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts or len(item.content) > 5 * 1024 * 1024:
                raise ValueError("sandbox input path or size rejected")
            inputs["data/" + path.name] = item.content
            input_total += len(item.content)
        if input_total > 20 * 1024 * 1024:
            raise ValueError("sandbox input size limit exceeded")
        try:
            container = client.containers.create(
                self._image, command=["sh", "-c", "while :; do sleep 3600; done"], detach=True,
                network_mode="none", read_only=True, user="65532:65532",
                mem_limit="512m", nano_cpus=1_000_000_000, pids_limit=64,
                cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
                tmpfs={"/work": "rw,noexec,nosuid,nodev,size=64m,uid=65532,gid=65532",
                       "/out": "rw,noexec,nosuid,nodev,size=20m,uid=65532,gid=65532",
                       "/tmp": "rw,nosuid,nodev,size=32m,mode=1777"},
                working_dir="/work", environment={"HOME": "/tmp", "OUT_DIR": "/out", "DATA_DIR": "/work/data"},
                volumes={}, labels={"technologyagent.run_id": ctx.run_id or "unknown",
                                    "technologyagent.job_id": control.job_id},
            )
            if not control.attach(container.id):
                container.remove(force=True)
                return SandboxResult(exit_code=125, diagnostics="sandbox job cancelled before start")
            container.start()
            container.reload()
            self._validate_inspect(container.attrs)
            if control.cancelled.is_set():
                container.kill()
                return SandboxResult(exit_code=125, diagnostics="sandbox job cancelled during setup")
            _upload_files(client, container.id, inputs)
            if control.cancelled.is_set():
                container.kill()
                return SandboxResult(exit_code=125, diagnostics="sandbox job cancelled during upload")
            timed_out = False
            exec_id = client.api.exec_create(container.id, ["python", "/work/code.py"], stdout=True, stderr=True)["Id"]
            client.api.exec_start(exec_id, detach=True)
            deadline = time.monotonic() + job.timeout_seconds
            try:
                execution = client.api.exec_inspect(exec_id)
                while execution.get("Running") and time.monotonic() < deadline:
                    if control.cancelled.is_set():
                        container.kill()
                        return SandboxResult(exit_code=125, diagnostics="sandbox job cancelled")
                    time.sleep(0.05)
                    execution = client.api.exec_inspect(exec_id)
                if execution.get("Running"):
                    timed_out = True
                    container.kill()
                    exit_code = 124
                else:
                    exit_code = int(execution.get("ExitCode", 1))
            except Exception:
                try:
                    execution = client.api.exec_inspect(exec_id)
                    exit_code = int(execution.get("ExitCode", 1))
                except Exception:
                    exit_code = 1
            outputs = []
            diagnostic = ""
            if not timed_out and exit_code == 0:
                try:
                    names_json = json.dumps(job.output_allowlist)
                    exporter = (
                        "import io,json,os,sys,tarfile\n"
                        "names=json.loads(sys.argv[1]); found=os.listdir('/out'); total=0; stream=io.BytesIO()\n"
                        "if set(found)-set(names): raise SystemExit(65)\n"
                        "with tarfile.open(fileobj=stream,mode='w') as archive:\n"
                        " for name in names:\n"
                        "  p='/out/'+name\n"
                        "  if not os.path.lexists(p): continue\n"
                        "  if os.path.islink(p) or not os.path.isfile(p): raise SystemExit(65)\n"
                        "  with open(p,'rb') as f: data=f.read(" + str(MAX_OUTPUT_BYTES + 1) + ")\n"
                        "  total+=len(data)\n"
                        "  if len(data)>" + str(MAX_OUTPUT_BYTES) + " or total>" + str(MAX_OUTPUT_BYTES) + ": raise SystemExit(65)\n"
                        "  info=tarfile.TarInfo(name); info.size=len(data); info.mode=0o600; archive.addfile(info,io.BytesIO(data))\n"
                        "sys.stdout.buffer.write(stream.getvalue())\n"
                    )
                    exported = container.exec_run(["python", "-c", exporter, names_json], demux=True)
                    if exported.exit_code != 0:
                        raise ValueError("output limit, symlink, or allowlist violation")
                    stdout = exported.output[0] if isinstance(exported.output, tuple) else exported.output
                    outputs = collect_archive(stdout or b"", set(job.output_allowlist))
                    if not outputs:
                        diagnostic = "container completed without allowlisted output files"
                except Exception as exc:
                    diagnostic = f"output collection failed: {type(exc).__name__}: {exc}"
                    exit_code = 65
            if not diagnostic:
                diagnostic = "container inspect passed: network=none, read-only root, no mounts, non-root, capped resources"
            return SandboxResult(exit_code=exit_code, timed_out=timed_out, outputs=outputs, diagnostics=diagnostic)
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    @staticmethod
    def _validate_inspect(attrs: dict[str, Any]) -> None:
        host = attrs.get("HostConfig") or {}
        config = attrs.get("Config") or {}
        tmpfs = host.get("Tmpfs") or {}
        if (host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True
                or attrs.get("Mounts") or host.get("Binds") or host.get("Mounts")
                or host.get("CapDrop") != ["ALL"]
                or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
                or host.get("Memory") != 512 * 1024 * 1024
                or host.get("NanoCpus") != 1_000_000_000
                or host.get("PidsLimit") != 64
                or config.get("User") != "65532:65532"
                or "/work" not in tmpfs or "/out" not in tmpfs or "/tmp" not in tmpfs):
            raise RuntimeError("container isolation inspection did not match the P06 policy")
