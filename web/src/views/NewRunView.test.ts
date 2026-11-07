import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";
import NewRunView from "./NewRunView.vue";

const TOKEN = "test-access-token";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const page = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
});

const BODIES: Record<string, unknown> = {
  "/api/records/auth/me/": {
    id: 1,
    username: "alice",
    organizations: [{ id: 1, name: "Acme", slug: "acme", role: "editor" }],
  },
  "/api/records/projects/3/": { id: 3, organization: 1, name: "Demo" },
  "/api/records/prompt-templates/": page([{ id: 10, name: "Demo QA" }]),
  "/api/records/prompt-versions/": page([
    { id: 11, number: 1, variables: ["question"] },
    { id: 12, number: 2, variables: ["question"] },
  ]),
  "/api/records/datasets/": page([
    { id: 20, name: "good", row_count: 5 },
    { id: 21, name: "empty", row_count: null },
  ]),
  "/api/records/providers/": page([
    { id: 30, name: "Mock", kind: "mock" },
    { id: 31, name: "Ollama", kind: "ollama" },
  ]),
  "/api/records/models/": page([{ id: 40, model_name: "mock-echo", provider: 30 }]),
  "/api/records/scorers/": page([
    { id: 50, name: "Exact", kind: "exact" },
    { id: 51, name: "Judge", kind: "llm_judge" },
  ]),
};

async function mountNewRun(runResponse: { status: number; body: Record<string, unknown> } = { status: 201, body: { id: "abc" } }) {
  const requests: Request[] = [];
  let runBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      requests.push(request);
      if (path === "/api/eval/runs" && request.method === "POST") {
        runBody = await request.clone().json();
        return jsonResponse(runResponse.status, runResponse.body);
      }
      const body =
        path === "/api/records/models/" &&
        new URL(request.url).searchParams.get("provider") === "31"
          ? page([{ id: 41, model_name: "llama", provider: 31 }])
          : BODIES[path];
      return jsonResponse(body ? 200 : 404, body ?? { detail: "Not found." });
    }),
  );
  setActivePinia(createPinia());
  useAuthStore().accessToken = TOKEN;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
      { path: "/projects/:projectId/runs/new", name: "run-new", component: NewRunView },
      { path: "/projects/:projectId/runs/:runId", name: "run", component: { template: "<div />" } },
    ],
  });
  router.push("/projects/3/runs/new");
  await router.isReady();
  const wrapper = mount(NewRunView, {
    global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
        router,
      ],
    },
  });
  await flushPromises();
  return { wrapper, router, requests, getRunBody: () => runBody };
}

afterEach(() => vi.unstubAllGlobals());

describe("NewRunView", () => {
  it("submits the exact body with the bearer header and navigates", async () => {
    const { wrapper, router, requests, getRunBody } = await mountNewRun();
    await wrapper.find("select").setValue("10"); // template select
    await flushPromises();
    const selects = wrapper.findAll("select");
    await selects[1].setValue("12"); // version
    await selects[2].setValue("20"); // dataset
    const checkboxes = wrapper.findAll('input[type="checkbox"]');
    await checkboxes[0].setValue(true); // mock-echo
    await checkboxes[2].setValue(true); // Exact scorer (order: mock-echo, llama, Exact, Judge)
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(getRunBody()).toEqual({
      project_id: 3,
      prompt_version_id: 12,
      dataset_id: 20,
      model_config_ids: [40],
      scorer_ids: [50],
      seed: 0,
    });
    const post = requests.find((r) => r.method === "POST" && r.url.includes("/api/eval/runs"));
    expect(post?.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(router.currentRoute.value.name).toBe("run");
  });

  it("defaults to the highest version and disables unsupported options", async () => {
    const { wrapper } = await mountNewRun();
    await wrapper.find("select").setValue("10");
    await flushPromises();
    expect((wrapper.findAll("select")[1].element as HTMLSelectElement).value).toBe("12");
    const inputs = wrapper.findAll('input[type="checkbox"]');
    // model list order: mock-echo (40) then llama (41); scorers: Exact (50), Judge (51)
    expect(inputs.find((i) => Number(i.attributes("value")) === 41)?.attributes("disabled")).toBeDefined();
    expect(inputs.find((i) => Number(i.attributes("value")) === 51)?.attributes("disabled")).toBeDefined();
    const datasetSelect = wrapper.findAll("select")[2];
    expect(datasetSelect.find('option[value="21"]').attributes("disabled")).toBeDefined();
  });

  it("shows a 400 detail and keeps selections", async () => {
    const { wrapper } = await mountNewRun({ status: 400, body: { detail: "Dataset has no rows" } });
    await wrapper.find("select").setValue("10");
    await flushPromises();
    const selects = wrapper.findAll("select");
    await selects[1].setValue("12");
    await selects[2].setValue("20");
    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true);
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Dataset has no rows");
    expect((selects[2].element as HTMLSelectElement).value).toBe("20");
  });

  it("shows the editor-required message to viewers with no form", async () => {
    const { wrapper } = await mountNewRun({ status: 201, body: { id: "x" } });
    // remount with viewer role
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request: Request) => {
        const path = new URL(request.url).pathname;
        if (path === "/api/records/auth/me/") {
          return jsonResponse(200, {
            id: 1, username: "alice",
            organizations: [{ id: 1, name: "Acme", slug: "acme", role: "viewer" }],
          });
        }
        return jsonResponse(BODIES[path] ? 200 : 404, BODIES[path] ?? { detail: "Not found." });
      }),
    );
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
        { path: "/projects/:projectId/runs/new", name: "run-new", component: NewRunView },
      ],
    });
    router.push("/projects/3/runs/new");
    await router.isReady();
    const viewer = mount(NewRunView, {
      global: {
        plugins: [
          [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
          router,
        ],
      },
    });
    await flushPromises();
    expect(viewer.text()).toContain("editor or owner");
    expect(viewer.find("form").exists()).toBe(false);
    wrapper.unmount();
  });
});
