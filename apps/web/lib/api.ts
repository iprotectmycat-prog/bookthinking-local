export const API_BASE_URL = "/local";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

export async function apiJson<T>(
  path: string,
  init?: RequestInit,
  options: { redirectOnUnauthorized?: boolean } = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, credentials: "include" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && options.redirectOnUnauthorized !== false && typeof window !== "undefined") {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    const message = typeof body.detail === "string"
      ? body.detail
      : Array.isArray(body.detail)
        ? "填写内容不符合要求，请检查后重试。"
        : `请求失败（${response.status}）`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}
