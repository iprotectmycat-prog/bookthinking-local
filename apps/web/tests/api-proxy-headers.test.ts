import { expect, it } from "vitest";

import { proxyHeaders } from "../lib/api-proxy-headers";

it("removes caller supplied trust headers before forwarding a remote request", () => {
  const headers = proxyHeaders(
    new Headers({ host: "book.example", "x-bookthinking-client-scope": "trusted_loopback", "x-bookthinking-proxy-secret": "forged", cookie: "session=abc" }),
    "book.example",
    "server-secret",
  );

  expect(headers.get("host")).toBeNull();
  expect(headers.get("x-bookthinking-client-scope")).toBe("remote");
  expect(headers.get("x-bookthinking-proxy-secret")).toBe("server-secret");
  expect(headers.get("cookie")).toBe("session=abc");
});

it("marks loopback requests as trusted only when the server has a proxy secret", () => {
  const headers = proxyHeaders(new Headers(), "127.0.0.1", "server-secret");

  expect(headers.get("x-bookthinking-client-scope")).toBe("trusted_loopback");
});
