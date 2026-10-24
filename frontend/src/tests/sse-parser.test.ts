import { describe, expect, it } from "vitest";

import {
  IncompleteSSEFrameError,
  SSEParser,
  UnsupportedEventVersionError,
} from "../lib/sse-parser";
import type { EventEnvelope } from "../lib/events";

function sse(events: EventEnvelope[], { crlf = false, comment = false } = {}): string {
  const newline = crlf ? "\r\n" : "\n";
  const blocks: string[] = [];
  if (comment) blocks.push(": heartbeat" + newline);
  for (const event of events) {
    blocks.push(
      "id: " + event.event_id + newline +
        "event: " + event.type + newline +
        "data: " + JSON.stringify(event) + newline + newline,
    );
  }
  return blocks.join("");
}

const token: EventEnvelope = {
  schema_version: 1,
  type: "token",
  event_id: "evt-1",
  seq: 1,
  thread_id: "thr-1",
  run_id: "run-1",
  at: "2026-10-24T01:00:00Z",
  payload: { message_id: "msg-1", delta: "你好，世界", actor: "main" },
};

const end: EventEnvelope = {
  schema_version: 1,
  type: "stream_end",
  event_id: "evt-2",
  seq: 2,
  thread_id: "thr-1",
  run_id: "run-1",
  at: "2026-10-24T01:00:01Z",
  payload: { reason: "completed", last_seq: 2 },
};

const encoder = new TextEncoder();

function parseChunks(chunks: Uint8Array[]): EventEnvelope[] {
  const parser = new SSEParser();
  const events: EventEnvelope[] = [];
  for (const chunk of chunks) events.push(...parser.push(chunk));
  parser.finish();
  return events;
}

describe("SSEParser", () => {
  it("parses Chinese across every possible byte split", () => {
    const bytes = encoder.encode(sse([token, end]));
    const expected = parseChunks([bytes]);
    expect(expected.map((event) => event.type)).toEqual(["token", "stream_end"]);
    for (let index = 0; index <= bytes.length; index += 1) {
      const events = parseChunks([bytes.slice(0, index), bytes.slice(index)]);
      expect(events).toEqual(expected);
    }
    const oneByteChunks = Array.from(bytes, (_, index) => bytes.slice(index, index + 1));
    expect(parseChunks(oneByteChunks)).toEqual(expected);
  });

  it("handles CRLF, heartbeat comments and multiline data", () => {
    const crlf = encoder.encode(sse([token], { crlf: true, comment: true }));
    expect(parseChunks([crlf])).toEqual([token]);

    const json = JSON.stringify(token);
    const splitAt = json.indexOf('"thread_id"');
    const multiline = encoder.encode(
      "event: token\ndata: " + json.slice(0, splitAt) + "\ndata: " + json.slice(splitAt) + "\n\n",
    );
    expect(parseChunks([multiline])).toEqual([token]);
  });

  it("rejects an incomplete final frame and unsupported versions", () => {
    const parser = new SSEParser();
    parser.push(encoder.encode("event: token\ndata: {"));
    expect(() => parser.finish()).toThrow(IncompleteSSEFrameError);

    const version2 = { ...token, schema_version: 2 };
    const bad = new SSEParser();
    expect(() => bad.push(encoder.encode(sse([version2 as EventEnvelope])))).toThrow(
      UnsupportedEventVersionError,
    );
  });
});
