"""导出 P01/P02 JSON Schema 与前端 TypeScript 类型（稳定排序）。

默认写入：
  backend/app/contracts/domain-schema.v1.json
  backend/app/contracts/events-schema.v1.json
  frontend/src/lib/domain-types.ts
  frontend/src/lib/events.ts

--check 只检测差异，CI/verify_stage 使用，不静默改写文件。
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

from backend.app.contracts.events import (
    ArtifactReadyPayload,
    ChatRequest,
    ConversationView,
    DeleteResult,
    ErrorPayload,
    EventEnvelope,
    EventType,
    InterruptPayload,
    MessageView,
    PhasePayload,
    PlanPayload,
    ReviewPayload,
    RunFinishedPayload,
    RunStartedPayload,
    RunView,
    StreamEndPayload,
    ThreadView,
    TokenPayload,
    ToolFinishedPayload,
    ToolStartedPayload,
)
from backend.app.contracts.domain import (
    CandidateQuote,
    Inventory,
    InventoryQuery,
    InventorySummary,
    InventoryView,
    OrderDraft,
    OrderItem,
    Part,
    PreviewLine,
    PreviewResult,
    PurchaseOrder,
    PurchaseOrderItem,
    Quote,
    QuoteView,
    ReplenishmentRequest,
    SourceRef,
    Supplier,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "backend" / "app" / "contracts" / "domain-schema.v1.json"
EVENTS_SCHEMA_PATH = ROOT / "backend" / "app" / "contracts" / "events-schema.v1.json"
TYPES_PATH = ROOT / "frontend" / "src" / "lib" / "domain-types.ts"
EVENTS_TYPES_PATH = ROOT / "frontend" / "src" / "lib" / "events.ts"

EVENT_MODELS = {
    "ArtifactReadyPayload": ArtifactReadyPayload,
    "ChatRequest": ChatRequest,
    "ConversationView": ConversationView,
    "DeleteResult": DeleteResult,
    "ErrorPayload": ErrorPayload,
    "InterruptPayload": InterruptPayload,
    "MessageView": MessageView,
    "PhasePayload": PhasePayload,
    "PlanPayload": PlanPayload,
    "ReviewPayload": ReviewPayload,
    "RunFinishedPayload": RunFinishedPayload,
    "RunStartedPayload": RunStartedPayload,
    "RunView": RunView,
    "StreamEndPayload": StreamEndPayload,
    "ThreadView": ThreadView,
    "TokenPayload": TokenPayload,
    "ToolFinishedPayload": ToolFinishedPayload,
    "ToolStartedPayload": ToolStartedPayload,
}

EVENT_PAYLOAD_NAMES = {
    "run_started": "RunStartedPayload",
    "token": "TokenPayload",
    "tool_started": "ToolStartedPayload",
    "tool_finished": "ToolFinishedPayload",
    "interrupt": "InterruptPayload",
    "phase": "PhasePayload",
    "plan": "PlanPayload",
    "review": "ReviewPayload",
    "artifact_ready": "ArtifactReadyPayload",
    "error": "ErrorPayload",
    "run_finished": "RunFinishedPayload",
    "stream_end": "StreamEndPayload",
}

MODELS = {
    "CandidateQuote": CandidateQuote,
    "Inventory": Inventory,
    "InventoryQuery": InventoryQuery,
    "InventorySummary": InventorySummary,
    "InventoryView": InventoryView,
    "OrderDraft": OrderDraft,
    "OrderItem": OrderItem,
    "Part": Part,
    "PreviewLine": PreviewLine,
    "PreviewResult": PreviewResult,
    "PurchaseOrder": PurchaseOrder,
    "PurchaseOrderItem": PurchaseOrderItem,
    "Quote": Quote,
    "QuoteView": QuoteView,
    "ReplenishmentRequest": ReplenishmentRequest,
    "SourceRef": SourceRef,
    "Supplier": Supplier,
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def build_schema_export() -> dict[str, object]:
    models: dict[str, object] = {}
    defs: dict[str, object] = {}
    for name in sorted(MODELS):
        schema = MODELS[name].model_json_schema(ref_template="#/$defs/{model}")
        nested = schema.pop("$defs", {})
        defs.update(nested)
        models[name] = schema
    return {
        "schema_version": 1,
        "models": models,
        "$defs": {key: defs[key] for key in sorted(defs)},
    }


def build_event_schema_export() -> dict[str, object]:
    models: dict[str, object] = {}
    defs: dict[str, object] = {}
    for name in sorted(EVENT_MODELS):
        schema = EVENT_MODELS[name].model_json_schema(ref_template="#/$defs/{model}")
        nested = schema.pop("$defs", {})
        defs.update(nested)
        models[name] = schema
    return {
        "schema_version": 1,
        "models": models,
        "$defs": {key: defs[key] for key in sorted(defs)},
    }


def _ts_type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(item, ensure_ascii=False) for item in schema["enum"])
    if "anyOf" in schema:
        parts: list[str] = []
        for item in schema["anyOf"]:
            rendered = _ts_type(item)
            if rendered not in parts:
                parts.append(rendered)
        if "null" in parts and len(parts) > 1:
            parts.remove("null")
            parts.append("null")
        return " | ".join(parts)
    if "allOf" in schema:
        return " & ".join(_ts_type(item) for item in schema["allOf"])
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        parts = []
        for item in schema_type:
            if item == "null":
                parts.append("null")
            else:
                parts.append(_ts_type({**schema, "type": item}))
        return " | ".join(parts)
    if schema_type == "array":
        return f"{_ts_type(schema.get('items', {}))}[]"
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties")
        if properties:
            required = set(schema.get("required", []))
            fields = []
            for key in sorted(properties):
                optional = "" if key in required else "?"
                fields.append(f"{key}{optional}: {_ts_type(properties[key])}")
            return "{ " + "; ".join(fields) + " }"
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {_ts_type(additional)}>"
        return "Record<string, unknown>"
    return "unknown"


def _render_interface(name: str, schema: dict) -> str:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for key in sorted(properties):
        optional = "" if key in required else "?"
        lines.append(f"  {key}{optional}: {_ts_type(properties[key])};")
    if schema.get("additionalProperties") is True:
        lines.append("  [key: string]: unknown;")
    lines.append("}")
    return "\n".join(lines)


def build_event_types() -> str:
    export = build_event_schema_export()
    interfaces: dict[str, dict] = {}
    interfaces.update(export["$defs"])  # type: ignore[arg-type]
    interfaces.update(export["models"])  # type: ignore[arg-type]
    event_types = list(EventType.__args__)
    chunks = [
        "// Generated by scripts/export_contracts.py. Do not edit by hand.",
        "// Source: backend/app/contracts/events.py",
        "",
        "export type EventType = " + " | ".join(json.dumps(item, ensure_ascii=False) for item in event_types) + ";",
        "",
        "export interface EventEnvelopeBase {",
        "  schema_version: 1;",
        "  event_id: string;",
        "  seq: number;",
        "  thread_id: string;",
        "  run_id: string;",
        "  at: string;",
        "}",
        "",
    ]
    for name in sorted(interfaces):
        chunks.append(_render_interface(name, interfaces[name]))
        chunks.append("")
    union = []
    for item in event_types:
        payload = EVENT_PAYLOAD_NAMES[item]
        union.append(
            '(EventEnvelopeBase & { type: ' + json.dumps(item, ensure_ascii=False)
            + "; payload: " + payload + "; })"
        )
    chunks.append("export type EventEnvelope = " + "\n  | ".join(union) + ";")
    chunks.append("")
    return "\n".join(chunks)


def build_types() -> str:
    export = build_schema_export()
    interfaces: dict[str, dict] = {}
    interfaces.update(export["$defs"])  # type: ignore[arg-type]
    interfaces.update(export["models"])  # type: ignore[arg-type]
    chunks = [
        "// Generated by scripts/export_contracts.py. Do not edit by hand.",
        "// Source: backend/app/contracts/domain.py",
        "",
        "export interface Page<T> {",
        "  records: T[];",
        "  total: number;",
        "  page: number;",
        "  page_size: number;",
        "  pages: number;",
        "}",
        "",
    ]
    for name in sorted(interfaces):
        chunks.append(_render_interface(name, interfaces[name]))
        chunks.append("")
    return "\n".join(chunks)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _diff(path: Path, expected: str) -> str:
    if not path.is_file():
        return f"{path}: missing"
    actual = path.read_text(encoding="utf-8")
    if actual == expected:
        return ""
    diff = list(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=str(path),
            tofile="generated",
            lineterm="",
        )
    )
    return "\n".join(diff[:80])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export P01/P02 schemas and TypeScript types")
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args(argv)

    schema_text = _json(build_schema_export()) + "\n"
    events_schema_text = _json(build_event_schema_export()) + "\n"
    types_text = build_types()
    event_types_text = build_event_types()

    if args.check:
        problems = [
            text
            for text in (
                _diff(SCHEMA_PATH, schema_text),
                _diff(EVENTS_SCHEMA_PATH, events_schema_text),
                _diff(TYPES_PATH, types_text),
                _diff(EVENTS_TYPES_PATH, event_types_text),
            )
            if text
        ]
        if problems:
            print("\n\n".join(problems))
            return 1
        print("contracts are up to date")
        return 0

    _write(SCHEMA_PATH, schema_text)
    _write(EVENTS_SCHEMA_PATH, events_schema_text)
    _write(TYPES_PATH, types_text)
    _write(EVENTS_TYPES_PATH, event_types_text)
    print(f"wrote {SCHEMA_PATH.relative_to(ROOT)}")
    print(f"wrote {EVENTS_SCHEMA_PATH.relative_to(ROOT)}")
    print(f"wrote {TYPES_PATH.relative_to(ROOT)}")
    print(f"wrote {EVENTS_TYPES_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())