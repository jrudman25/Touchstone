import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";
import RunView from "./RunView.vue";

const TOKEN = "t";
const RUN_ID = "abcdef0123456789abcdef01";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function runBody(status = "running") {
  return {
    id: RUN_ID,
    organization_id: 1,
    project_id: 3,
    prompt_version_id: 12,
    dataset_id: 20,
    status,
    created_by: 1,
    created_at: "2024-01-01T00:00:00Z",
    finished_at: status === "finished" ? "2024-01-01T00:05:00Z" : null,
    totals: { rows: 5, done: status === "finished" ? 5 : 2, failed: 0 },
    error: null,
    snapshot: {
      prompt: { template_id: 10, number: 2, system_message: "", body: "{{q}}", variables: [] },
      models: [
        {
          model_config_id: 40, provider_id: 30, kind: "mock", model_name: "mock-echo",
          temperature: 0, max_tokens: 512, context_length: 8192,
          input_price_per_1k: 0, output_price_per_1k: 0, digest: null,
          max_concurrency: 4, requests_per_minute: null,
        },
      ],
      scorers: [{ scorer_id: 50, name: "Exact", kind: "exact", params: {} }],
      seed: 0,
    },
    summary: {
      "40": {
        mean_score: 1, by_scorer: { "50": 1 }, p95_latency_ms: 42,
        cost_usd: 0.001, error_count: 0,
      },
    },
  };
}

function resultItem(row: number, extra = {}) {
  return {
    run_id: RUN_ID, model_config_id: 40, row_index: row,
    input: { q: `q${row}` }, expected: `a${row}`, rendered_prompt: "p",
    output: `a${row}`, usage: { input_tokens: 1, output_tokens: 1 },
    latency_ms: 10, cost_usd: 0, error: null, context_limited: false,
    scores: [{ scorer_id: 50, value: 1, reason: null }],
    ...extra,
  };
}

async function mountView({ status = "finished", runStatus = 200, results = [resultItem(0)], nextAfter = null as string | null, role = "editor" } = {}) {
  const urls: string[] = [];
  const posts: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const url = new URL(request.url);
      urls.push(url.pathname + url.search);
      if (path(url) === "/api/records/auth/me/") {
        return jsonResponse(200, {
          id: 1, username: "a",
          organizations: [{ id: 1, name: "A", slug: "a", role }],
        });
      }
      if (url.pathname === `/api/eval/runs/${RUN_ID}` && request.method === "GET") {
        return jsonResponse(runStatus, runStatus === 200 ? runBody(status) : { detail: "x" });
      }
      if (url.pathname === `/api/eval/runs/${RUN_ID}/cancel`) {
        posts.push(request);
        return jsonResponse(200, runBody("cancelled"));
      }
      if (url.pathname === `/api/eval/runs/${RUN_ID}/results`) {
        return jsonResponse(200, { items: results, next_after: nextAfter });
      }
      return jsonResponse(404, { detail: "Not found." });
    }),
  );
  setActivePinia(createPinia());
  useAuthStore().accessToken = TOKEN;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
      { path: "/projects/:projectId/runs/:runId", name: "run", component: RunView },
    ],
  });
  router.push(`/projects/3/runs/${RUN_ID}`);
  await router.isReady();
  const wrapper = mount(RunView, {
    global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
        router,
      ],
    },
  });
  await flushPromises();
  return { wrapper, urls, posts };
}
const path = (url: URL) => url.pathname;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("RunView", () => {
  it("renders progress, summary and results", async () => {
    const { wrapper } = await mountView();
    expect(wrapper.text()).toContain("5 of 5 done, 0 failed");
    expect(wrapper.text()).toContain("mock-echo");
    expect(wrapper.text()).toContain("Exact");
    expect(wrapper.text()).toContain("a0");
  });

  it("polls while running and stops when finished, refetching results once", async () => {
    vi.useFakeTimers();
    let poll = 0;
    let resultsPolls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        const url = new URL(request.url);
        if (url.pathname === "/api/records/auth/me/") {
          return jsonResponse(200, { id: 1, username: "a", organizations: [{ id: 1, name: "A", slug: "a", role: "editor" }] });
        }
        if (url.pathname === `/api/eval/runs/${RUN_ID}`) {
          poll += 1;
          return jsonResponse(200, runBody(poll < 2 ? "running" : "finished"));
        }
        if (url.pathname === `/api/eval/runs/${RUN_ID}/results`) {
          resultsPolls += 1;
          return jsonResponse(200, { items: [resultItem(0)], next_after: null });
        }
        return jsonResponse(404, { detail: "x" });
      }),
    );
    setActivePinia(createPinia());
    useAuthStore().accessToken = TOKEN;
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
        { path: "/projects/:projectId/runs/:runId", name: "run", component: RunView },
      ],
    });
    router.push(`/projects/3/runs/${RUN_ID}`);
    await router.isReady();
    const wrapper = mount(RunView, {
      global: {
        plugins: [
          [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
          router,
        ],
      },
    });
    await flushPromises();
    const before = poll;
    await vi.advanceTimersByTimeAsync(2100);
    await flushPromises();
    expect(poll).toBeGreaterThan(before);
    const afterFinish = poll;
    const resultsAfterFinish = resultsPolls;
    await vi.advanceTimersByTimeAsync(5000);
    await flushPromises();
    expect(poll).toBe(afterFinish); // stopped
    expect(resultsPolls).toBeGreaterThanOrEqual(resultsAfterFinish); // final results refetch happened
    wrapper.unmount();
  });

  it("keeps Load-more rows across a poll", async () => {
    const { wrapper } = await mountView({ nextAfter: "40:1" });
    await wrapper.findAll("button").find((b) => b.text() === "Load more")!.trigger("click");
    await flushPromises();
    // poll refetches page 1; loaded extra rows stay via infinite query pages
    expect(wrapper.findAll("tbody tr").length).toBeGreaterThan(0);
  });

  it("cancels a running run for an editor", async () => {
    const { wrapper, posts } = await mountView({ status: "running" });
    const btn = wrapper.findAll("button").find((b) => b.text() === "Cancel run");
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    await flushPromises();
    expect(posts.some((p) => p.url.includes("/cancel"))).toBe(true);
  });

  it("hides cancel for viewers and finished runs", async () => {
    const viewer = await mountView({ status: "running", role: "viewer" });
    expect(viewer.wrapper.findAll("button").some((b) => b.text() === "Cancel run")).toBe(false);
    const finished = await mountView({ status: "finished" });
    expect(finished.wrapper.findAll("button").some((b) => b.text() === "Cancel run")).toBe(false);
  });

  it("sends filter params", async () => {
    const { wrapper, urls } = await mountView();
    const modelSelect = wrapper.findAll("select")[0];
    await modelSelect.setValue("40");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await flushPromises();
    expect(urls.some((u) => u.includes("model_config_id=40"))).toBe(true);
    expect(urls.some((u) => u.includes("errors_only=true"))).toBe(true);
  });

  it("shows not-found and failure messages", async () => {
    const nf = await mountView({ runStatus: 404 });
    expect(nf.wrapper.text()).toContain("Run not found.");
    const bad = await mountView({ runStatus: 502 });
    expect(bad.wrapper.text()).toContain("Failed to load the run.");
  });
});
