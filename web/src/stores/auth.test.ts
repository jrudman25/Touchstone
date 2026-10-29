import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAuthStore } from "./auth";

const TOKEN = "test-access-token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("auth store", () => {
  it("stores the access token after login and touches no web storage", async () => {
    const fetchMock = vi.fn<() => Promise<Response>>(() => Promise.resolve(jsonResponse(200, { access: TOKEN })));
    vi.stubGlobal("fetch", fetchMock);
    const auth = useAuthStore();

    await auth.login("dev", "secret");

    expect(auth.accessToken).toBe(TOKEN);
    expect(auth.isAuthenticated).toBe(true);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("rejects invalid credentials without storing a token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<() => Promise<Response>>(() => Promise.resolve(jsonResponse(401, { detail: "No active account" }))),
    );
    const auth = useAuthStore();

    await expect(auth.login("dev", "wrong")).rejects.toThrow(
      "Invalid username or password.",
    );
    expect(auth.accessToken).toBeNull();
    expect(auth.isAuthenticated).toBe(false);
  });

  it("stores the new token after refresh and touches no web storage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<() => Promise<Response>>(() => Promise.resolve(jsonResponse(200, { access: TOKEN }))),
    );
    const auth = useAuthStore();

    expect(await auth.refresh()).toBe(true);
    expect(auth.accessToken).toBe(TOKEN);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("sends refresh as a same-origin POST with the X-Auth-Refresh header", async () => {
    const fetchMock = vi.fn<(request: Request) => Promise<Response>>(() =>
      Promise.resolve(jsonResponse(200, { access: TOKEN })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await useAuthStore().refresh();

    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe("/api/records/auth/token/refresh/");
    expect(request.headers.get("X-Auth-Refresh")).toBe("1");
    expect(request.credentials).toBe("same-origin");
  });

  it("clears the session when refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<() => Promise<Response>>(() => Promise.resolve(jsonResponse(401, {}))),
    );
    const auth = useAuthStore();
    auth.accessToken = "old-token";

    expect(await auth.refresh()).toBe(false);
    expect(auth.accessToken).toBeNull();
    expect(auth.isAuthenticated).toBe(false);
  });
});
