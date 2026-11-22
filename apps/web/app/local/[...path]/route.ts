import type { NextRequest } from "next/server";

import { proxyHeaders } from "../../../lib/api-proxy-headers";
import { isCloudDeployment } from "../../../lib/deployment-mode";

const BACKEND_ORIGIN = process.env.BOOKTHINKING_API_ORIGIN ?? "http://127.0.0.1:8000";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (isCloudDeployment() && request.method !== "GET" && request.method !== "HEAD") {
    return Response.json({ detail: "云端仅提供精选书籍阅读" }, { status: 405, headers: { Allow: "GET, HEAD" } });
  }

  const { path } = await context.params;
  const destination = new URL(BACKEND_ORIGIN);
  destination.pathname = `/${path.map(encodeURIComponent).join("/")}`;
  destination.search = request.nextUrl.search;
  const headers = proxyHeaders(
    request.headers,
    request.nextUrl.hostname,
    process.env.BOOKTHINKING_LOCAL_PROXY_SECRET,
  );

  const response = await fetch(destination, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
  });

  return new Response(response.body, {
    status: response.status,
    headers: response.headers,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
