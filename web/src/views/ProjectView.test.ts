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

async function mountView(role: string) {
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
