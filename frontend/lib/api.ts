export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export type ApiResult = Record<string, unknown>;

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

export async function apiGet(path: string): Promise<ApiResult> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
    return parseResponse(response);
  } catch (error) {
    return {
      ok: false,
      error: "Backend unreachable. Confirm FastAPI is running and NEXT_PUBLIC_API_BASE_URL is correct.",
      error_detail: error instanceof Error ? error.message : String(error),
      api_base_url: API_BASE_URL
    };
  }
}

export async function apiPost(path: string, body: Record<string, unknown> = {}): Promise<ApiResult> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return parseResponse(response);
  } catch (error) {
    return {
      ok: false,
      error: "Backend unreachable. Confirm FastAPI is running and NEXT_PUBLIC_API_BASE_URL is correct.",
      error_detail: error instanceof Error ? error.message : String(error),
      api_base_url: API_BASE_URL
    };
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
