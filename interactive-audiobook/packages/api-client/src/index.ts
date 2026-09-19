import createClient from "openapi-fetch";
import type { paths, TokenResponse } from "@audiobook/shared-types";

export type { TokenResponse };

/** Where tokens live. Implemented by the app (memory for access token, secure storage for refresh token). */
export interface TokenStore {
  getAccessToken(): string | null;
  getRefreshToken(): Promise<string | null>;
  setTokens(tokens: TokenResponse): Promise<void>;
  clearTokens(): Promise<void>;
}

export interface ApiClientOptions {
  baseUrl: string;
  tokenStore: TokenStore;
  /** Called once when the refresh token is rejected; the app should return to the sign-in screen. */
  onSessionExpired?: () => void;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "NetworkError";
  }
}

/** Endpoints that must never carry an access token or trigger a refresh-and-retry loop. */
const UNAUTHENTICATED_PATHS = ["/v1/auth/login", "/v1/auth/register", "/v1/auth/refresh", "/v1/auth/oauth/"];

const DEFAULT_TIMEOUT_MS = 15_000;

export function toApiError(status: number, body: unknown): ApiError {
  const envelope = (body as { error?: Partial<ApiErrorBody> } | undefined)?.error;
  return new ApiError(
    status,
    envelope?.code ?? "http_error",
    envelope?.message ?? `Request failed with status ${status}`,
    envelope?.request_id ?? null,
  );
}

export function createApiClient(options: ApiClientOptions) {
  const { baseUrl, tokenStore, onSessionExpired } = options;
  // Resolve global fetch per call: polyfills and network inspectors may replace it after this module loads.
  const baseFetch: typeof fetch = options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  async function fetchWithTimeout(request: Request): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await baseFetch(new Request(request, { signal: controller.signal }));
    } catch (error) {
      throw new NetworkError(controller.signal.aborted ? "Request timed out" : "Network request failed", error);
    } finally {
      clearTimeout(timer);
    }
  }

  let refreshInFlight: Promise<boolean> | null = null;

  /** Single-flight: concurrent 401s share one refresh call (a second call would look like token reuse). */
  function refreshTokens(): Promise<boolean> {
    refreshInFlight ??= (async () => {
      const refreshToken = await tokenStore.getRefreshToken();
      if (!refreshToken) return false;
      const response = await fetchWithTimeout(
        new Request(`${baseUrl}/v1/auth/refresh`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        }),
      );
      if (response.ok) {
        await tokenStore.setTokens((await response.json()) as TokenResponse);
        return true;
      }
      if (response.status === 401) {
        await tokenStore.clearTokens();
        onSessionExpired?.();
        return false;
      }
      // 429/5xx: keep the session; the caller sees the original 401 and can retry later.
      return false;
    })().finally(() => {
      refreshInFlight = null;
    });
    return refreshInFlight;
  }

  function withAuth(request: Request): Request {
    const token = tokenStore.getAccessToken();
    if (!token) return request;
    const authorized = new Request(request);
    authorized.headers.set("authorization", `Bearer ${token}`);
    return authorized;
  }

  async function authFetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (UNAUTHENTICATED_PATHS.some((p) => path.startsWith(p))) {
      return fetchWithTimeout(request);
    }
    const retryCopy = request.clone();
    const response = await fetchWithTimeout(withAuth(request));
    if (response.status !== 401) return response;
    if (!(await refreshTokens())) return response;
    return fetchWithTimeout(withAuth(retryCopy));
  }

  const client = createClient<paths>({ baseUrl, fetch: authFetch });
  return { client, refreshTokens };
}

export type ApiClient = ReturnType<typeof createApiClient>["client"];

/** Unwraps an openapi-fetch result: returns data or throws ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok && result.data !== undefined) return result.data;
  if (result.response.ok && result.response.status === 204) return undefined as T;
  throw toApiError(result.response.status, result.error);
}
