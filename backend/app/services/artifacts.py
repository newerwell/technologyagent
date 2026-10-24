"""按可信 owner/run 保存和授权读取产物；用户输入永远不能成为存储路径。"""
from __future__ import annotations

import os
import re
import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from backend.app.contracts.artifacts import Artifact, CollectedOutput
from backend.app.contracts.common import AppError, Clock, ErrorCodes, RequestContext
from backend.app.repositories.artifacts import ArtifactRepository

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
ALLOWED = {".png", ".csv", ".md", ".html", ".json"}
EXPECTED_MIME = {".png": "image/png", ".csv": "text/csv", ".md": "text/markdown",
                 ".html": "text/html", ".json": "application/json"}


class ArtifactService:
    def __init__(self, repository: ArtifactRepository, storage_root: Path, clock: Clock) -> None:
        self._repo, self._root, self._clock = repository, storage_root.resolve(), clock

    @staticmethod
    def _filename(name: str) -> str:
        cleaned = Path(name.replace("\\", "/")).name
        if not cleaned or cleaned in {".", ".."} or len(cleaned) > 128:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "invalid artifact filename", http_status=422)
        return cleaned

    async def register(self, output: CollectedOutput, ctx: RequestContext) -> Artifact:
        filename = self._filename(output.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED or len(output.content) == 0 or len(output.content) > MAX_ARTIFACT_BYTES:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "artifact type or size is invalid", http_status=422)
        expected = EXPECTED_MIME[suffix]
        if output.mime != expected or output.kind != suffix[1:]:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "artifact MIME does not match filename", http_status=422)
        if suffix == ".png":
            try:
                with Image.open(BytesIO(output.content)) as image:
                    if image.format != "PNG" or image.width < 1 or image.height < 1 or image.width * image.height > 40_000_000:
                        raise ValueError("PNG dimensions or format are invalid")
                    image.verify()
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "PNG content is invalid", http_status=422) from exc
        if suffix in {".csv", ".md", ".html", ".json"}:
            try:
                output.content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "text artifact is not UTF-8", http_status=422) from exc
        if suffix == ".json":
            try:
                json.loads(output.content)
            except ValueError as exc:
                raise AppError(ErrorCodes.VALIDATION_ERROR, "JSON artifact is malformed", http_status=422) from exc
        if not ctx.run_id:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "run context is required", http_status=422)
        artifact_id = "art_" + uuid4().hex
        owner_dir = re.sub(r"[^A-Za-z0-9_-]", "_", ctx.owner_id)
        run_dir = re.sub(r"[^A-Za-z0-9_-]", "_", ctx.run_id)
        storage_key = f"{owner_dir}/{run_dir}/{artifact_id}{suffix}"
        target = (self._root / storage_key).resolve()
        if self._root not in target.parents:
            raise AppError(ErrorCodes.VALIDATION_ERROR, "artifact storage path rejected", http_status=422)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(output.content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        record = Artifact(
            id=artifact_id, owner_id=ctx.owner_id, run_id=ctx.run_id, kind=output.kind,
            mime=output.mime, filename=filename, storage_key=storage_key,
            source_refs=output.source_refs, created_at=self._clock.now(), size_bytes=len(output.content),
        )
        try:
            await self._repo.insert({"_id": artifact_id, **record.model_dump()})
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return record

    async def open(self, artifact_id: str, ctx: RequestContext) -> tuple[Artifact, bytes]:
        if not re.fullmatch(r"art_[a-f0-9]{32}", artifact_id or ""):
            raise AppError(ErrorCodes.NOT_FOUND, "artifact not found", http_status=404)
        doc = await self._repo.get(artifact_id, ctx.owner_id)
        if doc is None:
            raise AppError(ErrorCodes.NOT_FOUND, "artifact not found", http_status=404)
        if doc.get("status") != "ready":
            raise AppError(ErrorCodes.DEPENDENCY_UNAVAILABLE, "artifact is not ready", http_status=409, retryable=True)
        artifact_data = {key: value for key, value in doc.items() if key != "_id"}
        artifact_data["id"] = doc["_id"]
        artifact = Artifact.model_validate(artifact_data)
        unresolved = self._root / artifact.storage_key
        current = self._root
        has_symlink = False
        for segment in Path(artifact.storage_key).parts:
            current = current / segment
            if current.is_symlink():
                has_symlink = True
                break
        if has_symlink:
            raise AppError(ErrorCodes.NOT_FOUND, "artifact content is unavailable", http_status=404)
        path = unresolved.resolve()
        if self._root not in path.parents or not path.is_file():
            raise AppError(ErrorCodes.NOT_FOUND, "artifact content is unavailable", http_status=404)
        content = path.read_bytes()
        if len(content) != artifact.size_bytes:
            raise AppError(ErrorCodes.NOT_FOUND, "artifact content is incomplete", http_status=404)
        return artifact, content
