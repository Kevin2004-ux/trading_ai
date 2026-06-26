export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export type ApiResult = Record<string, unknown>;

export interface ApiRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function parseResponse(response: Response): Promise<ApiResult> {
  const text = await response.text();
  let payload: ApiResult;
  try {
    payload = text ? (JSON.parse(text) as ApiResult) : {};
  } catch (error) {
    return {
      ok: false,
      error: `Backend returned non-JSON response (${response.status}).`,
      error_detail: error instanceof Error ? error.message : String(error),
      status: response.status,
      raw_response: text.slice(0, 500)
    };
  }
  if (!response.ok && typeof payload === "object") {
    return { ok: false, status: response.status, ...payload };
  }
  return payload;
}

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function withTimeout<T>(fn: (signal: AbortSignal) => Promise<T>, options: ApiRequestOptions = {}): Promise<T> {
  const timeoutMs = options.timeoutMs ?? 60000;
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fn(controller.signal);
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

function apiError(error: unknown): ApiResult {
  const isAbort = error instanceof DOMException && error.name === "AbortError";
  return {
    ok: false,
    error: isAbort
      ? "Backend request timed out or was cancelled."
      : "Backend unreachable. Confirm FastAPI is running and NEXT_PUBLIC_API_BASE_URL is correct.",
    error_detail: error instanceof Error ? error.message : String(error),
    api_base_url: API_BASE_URL
  };
}

export async function apiGet<T extends ApiResult = ApiResult>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  try {
    const payload = await withTimeout(async (signal) => {
      const response = await fetch(buildUrl(path), { cache: "no-store", signal });
      return parseResponse(response);
    }, options);
    return payload as T;
  } catch (error) {
    return apiError(error) as T;
  }
}

export async function apiPost<T extends ApiResult = ApiResult>(
  path: string,
  body: Record<string, unknown> = {},
  options: ApiRequestOptions = {}
): Promise<T> {
  try {
    const payload = await withTimeout(async (signal) => {
      const response = await fetch(buildUrl(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal
      });
      return parseResponse(response);
    }, options);
    return payload as T;
  } catch (error) {
    return apiError(error) as T;
  }
}

export function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value.filter((item) => item && typeof item === "object") as Record<string, unknown>[]) : [];
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function pickNested(root: unknown, path: string): unknown {
  return path.split(".").reduce((current: unknown, key) => asRecord(current)[key], root);
}
