import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";
import ProjectView from "./ProjectView.vue";

const TOKEN = "test-access-token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function mountView(role: string, runs: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn((request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/records/auth/me/") {
        return Promise.resolve(
          jsonResponse(200, {
            id: 1,
            username: "alice",
            organizations: [{ id: 1, name: "Acme", slug: "acme", role }],
          }),
        );
      }
      if (path === "/api/records/projects/3/") {
        return Promise.resolve(
          jsonResponse(200, { id: 3, organization: 1, name: "Demo", description: "" }),
        );
      }
      if (path === "/api/eval/runs") {
        return jsonResponse(200, { items: runs, next_before: null });
      }
      if (path === "/api/records/datasets/") {
        return Promise.resolve(
          jsonResponse(200, {
            count: 1,
            next: null,
            previous: null,
            results: [
              { id: 7, project: 3, organization: 1, name: "ds", row_count: null },
            ],
          }),
        );
      }
      return Promise.resolve(jsonResponse(404, { detail: "Not found." }));
    }),
  );
  const auth = useAuthStore();
  auth.accessToken = TOKEN;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", name: "home", component: { template: "<div />" } },
      {
        path: "/projects/:projectId/datasets/:datasetId",
        name: "dataset",
        component: { template: "<div />" },
      },
      { path: "/projects/:projectId", name: "project", component: ProjectView },
      {
        path: "/projects/:projectId/runs/new",
        name: "run-new",
        component: { template: "<div />" },
      },
      {
        path: "/projects/:projectId/runs/:runId",
        name: "run",
        component: { template: "<div />" },
      },
    ],
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await router.push("/projects/3");
  const wrapper = mount(ProjectView, {
    global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProjectView create-dataset form", () => {
  it("shows the form for an editor", async () => {
    const wrapper = await mountView("editor");

    expect(wrapper.find('input[name="dataset-name"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Create dataset");
  });

  it("hides the form for a viewer", async () => {
    const wrapper = await mountView("viewer");

    expect(wrapper.find('input[name="dataset-name"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Create dataset");
    expect(wrapper.text()).toContain("ds");
  });
});

function fakeRun(over: Record<string, unknown> = {}) {
    return {
      id: "abcdef0123456789abcdef01",
      status: "finished",
      created_at: "2024-01-01T00:00:00Z",
      snapshot: {
        prompt: { template_id: 10, number: 2 },
        models: [
          { model_config_id: 40, model_name: "a" },
          { model_config_id: 41, model_name: "b" },
        ],
        scorers: [],
      },
      summary: {
        "40": { mean_score: 1, by_scorer: {}, p95_latency_ms: 40, cost_usd: 0.01, error_count: 0 },
        "41": { mean_score: 0.5, by_scorer: {}, p95_latency_ms: 90, cost_usd: 0.02, error_count: 0 },
      },
      ...over,
    };
}

describe("ProjectView runs section", () => {
  it("links rows to run pages and shows aggregated values", async () => {
    const wrapper = await mountView("editor", [fakeRun()]);
    const link = wrapper
      .findAll("a")
      .find((a) => a.attributes("href")?.includes("abcdef0123456789abcdef01"));
    expect(link).toBeTruthy();
    expect(wrapper.text()).toContain("0.75"); // mean of 1 and 0.5
    expect(wrapper.text()).toContain("90"); // max p95
    expect(wrapper.text()).toContain("0.0300"); // cost sum
  });

  it("shows dashes when summary values are absent", async () => {
    const wrapper = await mountView("editor", [
      fakeRun({ summary: { "40": { mean_score: null, by_scorer: {}, p95_latency_ms: null, cost_usd: 0, error_count: 1 } } }),
    ]);
    expect(wrapper.text()).toContain("-");
  });

  it("hides the New run link for viewers", async () => {
    const editor = await mountView("editor", [fakeRun()]);
    expect(editor.findAll("a").some((a) => a.text() === "New run")).toBe(true);
    const viewer = await mountView("viewer", [fakeRun()]);
    expect(viewer.findAll("a").some((a) => a.text() === "New run")).toBe(false);
  });
});
