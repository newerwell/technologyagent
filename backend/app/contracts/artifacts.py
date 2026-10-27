"""P06 产物与沙箱结构化契约。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Artifact(_Strict):
    id: str
    owner_id: str
    run_id: str
    kind: str
    mime: str
    filename: str
    storage_key: str
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime
    status: Literal["ready"] = "ready"
    size_bytes: int = Field(ge=0)


class ArtifactListItem(_Strict):
    """安全的历史展示DTO；从不包含宿主存储路径。"""

    artifact_id: str
    run_id: str
    kind: str
    mime: str
    filename: str
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime
    size_bytes: int = Field(ge=0)
    download_url: str
    preview_url: str | None = None


class CollectedOutput(_Strict):
    filename: str
    content: bytes
    mime: str
    kind: str
    source_refs: list[dict[str, str]] = Field(default_factory=list)


class AuthorizedDataset(_Strict):
    """当前run内由成功只读调用产生的数据及其可信来源元信息。"""

    dataset_id: str
    owner_id: str
    run_id: str
    call_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    data_source: str
    scope: str
    as_of: str | None = None
    snapshot_id: str | None = None
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    data: object


class SandboxInput(_Strict):
    filename: str
    content: bytes


class SandboxJob(_Strict):
    code: str = Field(min_length=1, max_length=100_000)
    input_files: list[SandboxInput] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=30)
    output_allowlist: list[str] = Field(min_length=1, max_length=10)

    @field_validator("output_allowlist")
    @classmethod
    def _flat_allowlist(cls, value: list[str]) -> list[str]:
        supported = {"png", "csv", "md", "html", "json"}
        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name)
            or "." not in name or name.rsplit(".", 1)[-1].lower() not in supported
            for name in value
        ):
            raise ValueError("output allowlist must contain unique flat supported filenames")
        return value


class SandboxResult(_Strict):
    exit_code: int
    timed_out: bool = False
    outputs: list[CollectedOutput] = Field(default_factory=list)
    diagnostics: str = ""


class ChartSeries(_Strict):
    name: str
    values: list[int | float] = Field(min_length=1)
    values_cents: list[int] | None = None


class ChartSpec(_Strict):
    kind: Literal["bar", "line", "pie"]
    labels: list[str] = Field(min_length=1)
    series: list[ChartSeries] = Field(min_length=1)
    title: str
    source_refs: list[dict[str, str]] = Field(default_factory=list)


class ReportSpec(_Strict):
    format: Literal["md", "html", "csv", "json"]
    content: bytes
    mime: str
