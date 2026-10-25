import struct

import pytest

from backend.app.sandbox.runner import _upload_files


class _API:
    def __init__(self, stream, exit_code=0):
        self.stream = stream
        self.exit_code = exit_code
        self.inspect_calls = 0

    def exec_create(self, *_args, **_kwargs):
        return {"Id": "exec-test"}

    def exec_start(self, *_args, **_kwargs):
        return self.stream

    def exec_inspect(self, _exec_id):
        self.inspect_calls += 1
        return {"Running": False, "ExitCode": self.exit_code}


class _Client:
    def __init__(self, stream, exit_code=0):
        self.api = _API(stream, exit_code)


class _SocketIO:
    """Docker's file-like socket transport; unlike socket it has no sendall/shutdown."""

    def __init__(self, max_write=3, error_at=None):
        self.max_write = max_write
        self.error_at = error_at
        self.data = bytearray()
        self.closed = False

    def write(self, value):
        if self.error_at is not None and len(self.data) >= self.error_at:
            raise OSError("simulated transport interruption")
        amount = min(self.max_write, len(value))
        self.data.extend(value[:amount])
        return amount

    def close(self):
        self.closed = True


class _Socket:
    def __init__(self):
        self.data = bytearray()
        self.closed = False
        self.shutdown_calls = []

    def sendall(self, value):
        self.data.extend(value)

    def shutdown(self, how):
        self.shutdown_calls.append(how)

    def close(self):
        self.closed = True


def test_upload_supports_socketio_partial_writes_and_sends_eof_by_closing():
    stream = _SocketIO(max_write=2)
    client = _Client(stream)

    _upload_files(client, "container-test", {"code.py": b"print('ok')", "data/one.json": b"{}"})

    expected = (
        struct.pack("!H", 7) + b"code.py" + struct.pack("!Q", 11) + b"print('ok')"
        + struct.pack("!H", 13) + b"data/one.json" + struct.pack("!Q", 2) + b"{}"
        + b"\x00\x00"
    )
    assert bytes(stream.data) == expected
    assert stream.closed
    assert client.api.inspect_calls == 1


def test_upload_closes_transport_after_interrupted_write_and_propagates_error():
    stream = _SocketIO(max_write=4, error_at=8)

    with pytest.raises(OSError, match="simulated transport interruption"):
        _upload_files(_Client(stream), "container-test", {"code.py": b"payload"})

    assert stream.closed


def test_upload_rejects_nonzero_container_transfer_exit_and_closes_transport():
    stream = _SocketIO()

    with pytest.raises(RuntimeError, match="rejected sandbox input transfer"):
        _upload_files(_Client(stream, exit_code=23), "container-test", {"code.py": b"payload"})

    assert stream.closed


def test_upload_retains_native_socket_sendall_compatibility():
    stream = _Socket()

    _upload_files(_Client(stream), "container-test", {"code.py": b"x"})

    assert bytes(stream.data).endswith(b"\x00\x00")
    assert stream.shutdown_calls
    assert stream.closed
