const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

export function proxyHeaders(
  requestHeaders: Headers,
  hostname: string,
  proxySecret: string | undefined,
): Headers {
  const headers = new Headers(requestHeaders);
  headers.delete("host");
  headers.delete("x-bookthinking-client-scope");
  headers.delete("x-bookthinking-proxy-secret");
  if (proxySecret) {
    headers.set("X-BookThinking-Proxy-Secret", proxySecret);
    headers.set(
      "X-BookThinking-Client-Scope",
      LOOPBACK_HOSTS.has(hostname) ? "trusted_loopback" : "remote",
    );
  }
  return headers;
}
