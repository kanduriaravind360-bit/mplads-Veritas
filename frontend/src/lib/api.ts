/**
 * Thin fetch client for the FastAPI backend: bearer token, timeouts, typed errors.
 * Every number the UI shows comes through here; nothing is hard-coded.
 */

const TOKEN_KEY = "sentinel.token";
export const UNAUTHORIZED_EVENT = "sentinel:unauthorized";
const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get isTimeout(): boolean {
    return this.status === 0;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the session lasts until reload */
  }
}

type Primitive = string | number | boolean;
export type Params = Record<string, Primitive | Primitive[] | null | undefined>;

export function qs(params: Params = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Work and alert ids contain slashes; each segment is encoded, the slashes kept. */
export function idPath(id: string): string {
  return id.split("/").map(encodeURIComponent).join("/");
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function raw(path: string, options: RequestOptions = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("timeout"), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  options.signal?.addEventListener("abort", () => controller.abort(options.signal?.reason));
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  try {
    const response = await fetch(`/api${path}`, {
      method: options.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: controller.signal,
    });
    if (response.status === 401 && token) {
      setToken(null);
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted && controller.signal.reason === "timeout") {
      throw new ApiError(0, "The server took too long to respond. Try again.");
    }
    if (options.signal?.aborted) throw error;
    throw new ApiError(-1, "Cannot reach the Sentinel API. Is the backend running?");
  } finally {
    clearTimeout(timeout);
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
        .join("; ");
    }
  } catch {
    /* not JSON */
  }
  return `${response.status} ${response.statusText}`;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await raw(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Fetch a file with the bearer token and hand it to the browser to save. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await raw(path, { timeoutMs: 120_000 });
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
