import { ApiError, createApiClient, NetworkError, unwrap, type TokenResponse, type TokenStore } from "@audiobook/api-client";

const BASE = "http://api.test";

function tokens(access: string, refresh: string): TokenResponse {
  return {
    token_type: "bearer",
    access_token: access,
    access_token_expires_at: "2030-01-01T00:00:00Z",
    refresh_token: refresh,
    refresh_token_expires_at: "2030-01-01T00:00:00Z",
    user: { id: "00000000-0000-0000-0000-000000000001", email: "a@example.com", display_name: null, created_at: "2026-01-01T00:00:00Z" },
  };
}

function memoryTokenStore(access: string | null, refresh: string | null) {
  const state = { access, refresh, cleared: 0 };
  const store: TokenStore = {
    getAccessToken: () => state.access,
    getRefreshToken: async () => state.refresh,
    setTokens: async (t) => {
      state.access = t.access_token;
      state.refresh = t.refresh_token;
    },
    clearTokens: async () => {
      state.access = null;
      state.refresh = null;
      state.cleared += 1;
    },
  };
  return { store, state };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const me = tokens("x", "y").user;

describe("api client auth handling", () => {
  it("sends the bearer token and never sends it to auth endpoints", async () => {
    const seen: { url: string; auth: string | null }[] = [];
    const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      seen.push({ url: request.url, auth: request.headers.get("authorization") });
      return request.url.endsWith("/v1/users/me") ? json(200, me) : json(200, tokens("a2", "r2"));
    });
    const { store } = memoryTokenStore("access-1", "refresh-1");
    const { client } = createApiClient({ baseUrl: BASE, tokenStore: store, fetchImpl: fetchImpl as typeof fetch });

    await client.GET("/v1/users/me");
    await client.POST("/v1/auth/login", { body: { email: "a@example.com", password: "pw" } });

    expect(seen[0]).toEqual({ url: `${BASE}/v1/users/me`, auth: "Bearer access-1" });
    expect(seen[1]).toEqual({ url: `${BASE}/v1/auth/login`, auth: null });
  });

  it("refreshes once for concurrent 401s and retries each request with the new token", async () => {
    let refreshCalls = 0;
    const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      if (request.url.endsWith("/v1/auth/refresh")) {
        refreshCalls += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return json(200, tokens("access-2", "refresh-2"));
      }
      return request.headers.get("authorization") === "Bearer access-2"
        ? json(200, me)
        : json(401, { error: { code: "invalid_token", message: "expired" } });
    });
    const { store, state } = memoryTokenStore("access-1", "refresh-1");
    const { client } = createApiClient({ baseUrl: BASE, tokenStore: store, fetchImpl: fetchImpl as typeof fetch });

    const results = await Promise.all([client.GET("/v1/users/me"), client.GET("/v1/users/me"), client.GET("/v1/users/me")]);

    expect(refreshCalls).toBe(1);
    expect(results.map((r) => r.response.status)).toEqual([200, 200, 200]);
    expect(state.refresh).toBe("refresh-2");
  });

  it("clears the session when the refresh token is rejected", async () => {
    const onSessionExpired = jest.fn();
    const fetchImpl = jest.fn(async () => json(401, { error: { code: "refresh_token_reused", message: "reused" } }));
    const { store, state } = memoryTokenStore("access-1", "refresh-1");
    const { client } = createApiClient({ baseUrl: BASE, tokenStore: store, onSessionExpired, fetchImpl: fetchImpl as typeof fetch });

    const result = await client.GET("/v1/users/me");

    expect(result.response.status).toBe(401);
    expect(state.cleared).toBe(1);
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
    expect(() => unwrap(result)).toThrow(ApiError);
  });

  it("keeps the session when refresh fails for a transient reason", async () => {
    const fetchImpl = jest.fn(async (input: RequestInfo | URL) =>
      (input as Request).url.endsWith("/v1/auth/refresh")
        ? json(503, { error: { code: "service_unavailable", message: "down" } })
        : json(401, { error: { code: "invalid_token", message: "expired" } }),
    );
    const { store, state } = memoryTokenStore("access-1", "refresh-1");
    const { client } = createApiClient({ baseUrl: BASE, tokenStore: store, fetchImpl: fetchImpl as typeof fetch });

    await client.GET("/v1/users/me");
    expect(state.refresh).toBe("refresh-1");
    expect(state.cleared).toBe(0);
  });

  it("maps the error envelope and network failures to typed errors", async () => {
    const failing = createApiClient({
      baseUrl: BASE,
      tokenStore: memoryTokenStore(null, null).store,
      fetchImpl: (async () => json(429, { error: { code: "rate_limited", message: "slow down", request_id: "rid" } })) as typeof fetch,
    });
    const limited = await failing.client.POST("/v1/auth/login", { body: { email: "a@example.com", password: "pw" } });
    let caught: unknown;
    try {
      unwrap(limited);
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught).toMatchObject({ status: 429, code: "rate_limited", requestId: "rid" });

    const offline = createApiClient({
      baseUrl: BASE,
      tokenStore: memoryTokenStore(null, null).store,
      fetchImpl: (async () => {
        throw new TypeError("Network request failed");
      }) as typeof fetch,
    });
    await expect(offline.client.GET("/v1/users/me")).rejects.toBeInstanceOf(NetworkError);
  });
});
