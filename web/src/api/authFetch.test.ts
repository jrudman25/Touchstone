import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { recordsClient } from "./clients";
import { useAuthStore } from "../stores/auth";

const REFRESH_PATH = "/api/records/auth/token/refresh/";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function pathOf(request: Request): string {
  return new URL(request.url).pathname;
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("authFetch", () => {
  it("refreshes once and retries once with the new bearer on 401", async () => {
    const calls: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<(request: Request) => Promise<Response>>((request: Request) => {
        calls.push(request);
        if (pathOf(request) === REFRESH_PATH) {
          return Promise.resolve(jsonResponse(200, { access: "new-token" }));
        }
        if (request.headers.get("Authorization") === "Bearer new-token") {
          return Promise.resolve(jsonResponse(200, { count: 0, results: [] }));
        }
        return Promise.resolve(jsonResponse(401, {}));
      }),
    );
    const auth = useAuthStore();
    auth.accessToken = "old-token";

    const { data, error } = await recordsClient.GET("/api/records/projects/");

    expect(error).toBeUndefined();
    expect(data).toEqual({ count: 0, results: [] });
    const refreshCalls = calls.filter((r) => pathOf(r) === REFRESH_PATH);
    expect(refreshCalls).toHaveLength(1);
    const last = calls[calls.length - 1];
    expect(pathOf(last)).toBe("/api/records/projects/");
    expect(last.headers.get("Authorization")).toBe("Bearer new-token");
  });

  it("shares a single refresh across concurrent 401s and retries both", async () => {
    const calls: Request[] = [];
    let resolveRefresh!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn<(request: Request) => Promise<Response>>((request: Request) => {
        calls.push(request);
        if (pathOf(request) === REFRESH_PATH) {
          return new Promise<Response>((resolve) => {
            resolveRefresh = resolve;
          });
        }
        if (request.headers.get("Authorization") === "Bearer tok-2") {
          return Promise.resolve(jsonResponse(200, { count: 0, results: [] }));
        }
        return Promise.resolve(jsonResponse(401, {}));
      }),
    );
    const auth = useAuthStore();
    auth.accessToken = "tok-1";

    const first = recordsClient.GET("/api/records/projects/");
    const second = recordsClient.GET("/api/records/organizations/");
    await vi.waitFor(() =>
      expect(calls.filter((r) => pathOf(r) === REFRESH_PATH)).toHaveLength(1),
    );
    resolveRefresh(jsonResponse(200, { access: "tok-2" }));
    const [r1, r2] = await Promise.all([first, second]);

    expect(r1.error).toBeUndefined();
    expect(r2.error).toBeUndefined();
    expect(calls.filter((r) => pathOf(r) === REFRESH_PATH)).toHaveLength(1);
    const retries = calls.filter(
      (r) => r.headers.get("Authorization") === "Bearer tok-2",
    );
    expect(retries).toHaveLength(2);
  });

  it("clears the session and returns the 401 when refresh fails", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn<(request: Request) => Promise<Response>>((request: Request) => {
        calls.push(pathOf(request));
        return Promise.resolve(jsonResponse(401, {}));
      }),
    );
    const auth = useAuthStore();
    auth.accessToken = "tok-1";

    const { response, error } = await recordsClient.GET("/api/records/projects/");

    expect(response.status).toBe(401);
    expect(error).toBeDefined();
    expect(auth.isAuthenticated).toBe(false);
    expect(calls).toEqual(["/api/records/projects/", REFRESH_PATH]);
  });
});
