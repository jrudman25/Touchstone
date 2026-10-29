import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";

import { createAppRouter, safeRedirect } from "./router";

const TOKEN = "test-access-token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubRefresh(status: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn<() => Promise<Response>>(() => Promise.resolve(jsonResponse(status, status === 200 ? { access: TOKEN } : {}))),
  );
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("router guard", () => {
  it("redirects signed-out users to login with a redirect query", async () => {
    stubRefresh(401);
    const router = createAppRouter(createMemoryHistory());

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/");
  });

  it("lets signed-in users stay on home", async () => {
    stubRefresh(200);
    const router = createAppRouter(createMemoryHistory());

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("home");
  });

  it("falls back to home for unsafe redirect targets", async () => {
    stubRefresh(200);
    const router = createAppRouter(createMemoryHistory());

    await router.push({ name: "login", query: { redirect: "//evil.example" } });

    expect(router.currentRoute.value.name).toBe("home");
  });
});

describe("safeRedirect", () => {
  it("accepts same-origin paths and rejects the rest", () => {
    expect(safeRedirect("/projects")).toBe("/projects");
    expect(safeRedirect("//evil.example")).toBeNull();
    expect(safeRedirect("/\\evil.example")).toBeNull();
    expect(safeRedirect("https://evil.example")).toBeNull();
    expect(safeRedirect("projects")).toBeNull();
    expect(safeRedirect(undefined)).toBeNull();
    expect(safeRedirect(42)).toBeNull();
  });
});
