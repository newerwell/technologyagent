import type { EventEnvelope } from "./events";

export class IncompleteSSEFrameError extends Error {
  constructor() {
    super("SSE stream ended with an incomplete frame; recovery query is required");
    this.name = "IncompleteSSEFrameError";
  }
}

export class UnsupportedEventVersionError extends Error {
  readonly version: unknown;
  constructor(version: unknown) {
    super("unsupported event schema_version: " + String(version));
    this.name = "UnsupportedEventVersionError";
    this.version = version;
  }
}

function normalizeCrc(buffer: string): string {
  return buffer.replace(/\r\n/g, "\n");
}

function parseFrame(frame: string): EventEnvelope | null {
  const data: string[] = [];
  let eventName: string | null = null;
  for (const line of frame.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    if (line.startsWith("data:")) {
      data.push(line.slice(5).replace(/^ /, ""));
    } else if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    }
  }
  if (data.length === 0) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(data.join("\n"));
  } catch {
    throw new IncompleteSSEFrameError();
  }
  if (typeof raw !== "object" || raw === null) {
    throw new IncompleteSSEFrameError();
  }
  const candidate = raw as Record<string, unknown>;
  if (candidate.schema_version !== 1) {
    throw new UnsupportedEventVersionError(candidate.schema_version);
  }
  if (
    typeof candidate.type !== "string" ||
    typeof candidate.event_id !== "string" ||
    typeof candidate.thread_id !== "string" ||
    typeof candidate.run_id !== "string" ||
    typeof candidate.at !== "string" ||
    typeof candidate.payload !== "object" ||
    candidate.payload === null ||
    typeof candidate.seq !== "number" ||
    candidate.seq < 1
  ) {
    throw new IncompleteSSEFrameError();
  }
  if (eventName !== null && eventName !== candidate.type) {
    throw new IncompleteSSEFrameError();
  }
  return candidate as unknown as EventEnvelope;
}

export class SSEParser {
  private decoder = new TextDecoder("utf-8");
  private buffer = "";

  push(chunk: Uint8Array): EventEnvelope[] {
    this.buffer = normalizeCrc(this.buffer + this.decoder.decode(chunk, { stream: true }));
    const events: EventEnvelope[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const event = parseFrame(frame);
      if (event !== null) events.push(event);
      boundary = this.buffer.indexOf("\n\n");
    }
    return events;
  }

  finish(): void {
    this.buffer = normalizeCrc(this.buffer + this.decoder.decode());
    if (this.buffer.trim() !== "") {
      throw new IncompleteSSEFrameError();
    }
  }
}
