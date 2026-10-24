"""安全解析Docker归档；从不解压至宿主文件系统。"""
from __future__ import annotations

import io
import posixpath
import tarfile
from backend.app.contracts.artifacts import CollectedOutput

MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MIMES = {".png": "image/png", ".csv": "text/csv", ".md": "text/markdown", ".html": "text/html", ".json": "application/json"}


def collect_archive(archive: bytes, allowlist: set[str]) -> list[CollectedOutput]:
    outputs: list[CollectedOutput] = []
    total = 0
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
        for member in tf.getmembers():
            if member.isdir():
                continue
            if member.issym() or member.islnk() or not member.isfile():
                raise ValueError("link or special output is rejected")
            name = member.name.replace("\\", "/")
            if name.startswith("out/"):
                name = name[4:]
            if name.startswith("/") or posixpath.normpath(name) != name or name in {"", ".", ".."} or "/" in name:
                raise ValueError("absolute or traversal output path is rejected")
            if name not in allowlist:
                raise ValueError("output is outside allowlist")
            if name in seen:
                raise ValueError("duplicate output filename")
            seen.add(name)
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in MIMES:
                raise ValueError("output file type is not supported")
            handle = tf.extractfile(member)
            content = handle.read(MAX_OUTPUT_BYTES + 1) if handle else b""
            total += len(content)
            if len(content) != member.size or total > MAX_OUTPUT_BYTES:
                raise ValueError("output size limit exceeded or archive truncated")
            outputs.append(CollectedOutput(filename=name, content=content, mime=MIMES[suffix], kind=suffix[1:]))
    return outputs
