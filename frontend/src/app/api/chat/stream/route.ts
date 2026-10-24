import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const apiPort = process.env.API_PORT ?? "8030";
  const body = await request.text();
  const upstream = await fetch("http://127.0.0.1:" + apiPort + "/api/chat/stream", {
    method: "POST",
    headers: {
      "content-type": request.headers.get("content-type") ?? "application/json",
      cookie: request.headers.get("cookie") ?? "",
      origin: request.headers.get("origin") ?? "http://127.0.0.1:" + (process.env.FRONTEND_PORT ?? "3030"),
    },
    body,
    cache: "no-store",
  });
  if (!upstream.ok || upstream.body === null) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
