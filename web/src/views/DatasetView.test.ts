import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";
import DatasetView from "./DatasetView.vue";

const TOKEN = "test-access-token";
const DATASET_URL = "/api/records/datasets/7/";
const ROWS_URL = "/api/eval/datasets/7/rows";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function meBody(role: string) {
  return {
    id: 1,
    username: "alice",
    organizations: [{ id: 1, name: "Acme", slug: "acme", role }],
  };
}

function datasetBody(rowCount: number | null) {
  return { id: 7, project: 3, organization: 1, name: "ds", row_count: rowCount };
}

interface CapturedRequest {
  request: Request;
  body: string;
}

function stubFetch(
  handlers: (request: Request, path: string) => Response | undefined,
): CapturedRequest[] {
  const captured: CapturedRequest[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      const body = await request.clone().text();
      captured.push({ request, body });
      const handled = handlers(request, path);
      if (handled !== undefined) {
        return handled;
      }
      return jsonResponse(404, { detail: "Not found." });
    }),
  );
  return captured;
}

async function mountView(role = "editor", rowCount: number | null = null) {
  const calls = stubFetch((request, path) => {
    if (path === "/api/records/auth/me/") {
      return jsonResponse(200, meBody(role));
    }
    if (path === DATASET_URL) {
      return jsonResponse(200, datasetBody(rowCount));
    }
    if (path === ROWS_URL && request.method === "POST") {
      return jsonResponse(201, { dataset_id: 7, row_count: 3 });
    }
    if (path === ROWS_URL) {
      return jsonResponse(200, { items: [], next_after: null });
    }
    return undefined;
  });
  const auth = useAuthStore();
  auth.accessToken = TOKEN;
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
      {
        path: "/projects/:projectId/datasets/:datasetId",
        name: "dataset",
        component: DatasetView,
      },
    ],
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  await router.push("/projects/3/datasets/7");
  const wrapper = mount(DatasetView, {
    global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
  });
  await flushPromises();
  return { wrapper, calls };
}

async function pickFileAndUpload(wrapper: Awaited<ReturnType<typeof mountView>>["wrapper"], text: string) {
  const file = new File([text], "rows.jsonl", { type: "application/x-ndjson" });
  const input = wrapper.get('input[type="file"]');
  Object.defineProperty(input.element, "files", {
    value: [file],
    configurable: true,
  });
  await input.trigger("change");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DatasetView upload", () => {
  it("sends the file text as the ndjson body with the bearer header", async () => {
    const { wrapper, calls } = await mountView("editor", null);
    const text = '{"input": {"a": 1}}\n{"input": {"a": 2}}\n';

    await pickFileAndUpload(wrapper, text);

    const posts = calls.filter((c) => c.request.method === "POST");
    expect(posts).toHaveLength(1);
    const post = posts[0];
    expect(new URL(post.request.url).pathname).toBe(ROWS_URL);
    expect(post.request.headers.get("Authorization")).toBe(`Bearer ${TOKEN}`);
    expect(post.request.headers.get("Content-Type")).toBe("application/x-ndjson");
    expect(post.body).toBe(text);
    expect(wrapper.text()).toContain("Uploaded 3 rows.");
  });

  it("renders line errors from a 400 response", async () => {
    const { wrapper } = await mountView("editor", null);
    stubFetch((request, path) => {
      if (path === "/api/records/auth/me/") {
        return jsonResponse(200, meBody("editor"));
      }
      if (path === DATASET_URL) {
        return jsonResponse(200, datasetBody(null));
      }
      if (path === ROWS_URL && request.method === "POST") {
        return jsonResponse(400, {
          detail: "Invalid JSONL upload",
          errors: [
            { line: 2, message: "input: Field required" },
            { line: 4, message: "Blank line" },
          ],
        });
      }
      return undefined;
    });

    await pickFileAndUpload(wrapper, "bad\nlines\n");

    expect(wrapper.text()).toContain("Line 2: input: Field required");
    expect(wrapper.text()).toContain("Line 4: Blank line");
  });

  it("refreshes and retries once with the same body on a 401", async () => {
    const { wrapper } = await mountView("editor", null);
    let posts = 0;
    const calls = stubFetch((request, path) => {
      if (path === "/api/records/auth/me/") {
        return jsonResponse(200, meBody("editor"));
      }
      if (path === "/api/records/auth/token/refresh/") {
        return jsonResponse(200, { access: "tok-2" });
      }
      if (path === DATASET_URL) {
        return jsonResponse(200, datasetBody(null));
      }
      if (path === ROWS_URL && request.method === "POST") {
        posts += 1;
        return posts === 1
          ? jsonResponse(401, { detail: "expired" })
          : jsonResponse(201, { dataset_id: 7, row_count: 3 });
      }
      return undefined;
    });
    const text = '{"input": {"a": 1}}\n';

    await pickFileAndUpload(wrapper, text);

    const postCalls = calls.filter(
      (c) => c.request.method === "POST" && new URL(c.request.url).pathname === ROWS_URL,
    );
    expect(postCalls).toHaveLength(2);
    expect(postCalls[0].body).toBe(text);
    expect(postCalls[1].body).toBe(text);
    expect(postCalls[1].request.headers.get("Authorization")).toBe("Bearer tok-2");
    expect(wrapper.text()).toContain("Uploaded 3 rows.");
  });

  it("shows a 409 message when the dataset already has rows", async () => {
    const { wrapper } = await mountView("editor", null);
    stubFetch((request, path) => {
      if (path === "/api/records/auth/me/") {
        return jsonResponse(200, meBody("editor"));
      }
      if (path === DATASET_URL) {
        return jsonResponse(200, datasetBody(null));
      }
      if (path === ROWS_URL && request.method === "POST") {
        return jsonResponse(409, { detail: "Dataset rows are already uploaded" });
      }
      return undefined;
    });

    await pickFileAndUpload(wrapper, '{"input": {"a": 1}}\n');

    expect(wrapper.text()).toContain("This dataset already has rows.");
  });
});

describe("DatasetView preview", () => {
  it("hides the upload control and renders rows when row_count is set", async () => {
    const items = [
      { dataset_id: 7, row_index: 0, input: { q: "capital?", n: 1 }, expected: "Paris" },
      { dataset_id: 7, row_index: 1, input: { q: "second" }, expected: null },
    ];
    stubFetch((_request, path) => {
      if (path === "/api/records/auth/me/") {
        return jsonResponse(200, meBody("editor"));
      }
      if (path === DATASET_URL) {
        return jsonResponse(200, datasetBody(2));
      }
      if (path === ROWS_URL) {
        return jsonResponse(200, { items, next_after: null });
      }
      return undefined;
    });
    const auth = useAuthStore();
    auth.accessToken = TOKEN;
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: "/projects/:projectId/datasets/:datasetId",
          name: "dataset",
          component: DatasetView,
        },
        { path: "/projects/:projectId", name: "project", component: { template: "<div />" } },
      ],
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await router.push("/projects/3/datasets/7");
    const wrapper = mount(DatasetView, {
      global: { plugins: [router, [VueQueryPlugin, { queryClient }]] },
    });
    await flushPromises();

    expect(wrapper.find('input[type="file"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Rows: 2");
    expect(wrapper.text()).toContain("q: capital?, n: 1");
    expect(wrapper.text()).toContain("Paris");
    expect(wrapper.text()).toContain("none");
  });
});
