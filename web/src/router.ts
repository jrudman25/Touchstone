import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from "vue-router";

import { useAuthStore } from "./stores/auth";
import DatasetView from "./views/DatasetView.vue";
import NewRunView from "./views/NewRunView.vue";
import HomeView from "./views/HomeView.vue";
import LoginView from "./views/LoginView.vue";
import ProjectView from "./views/ProjectView.vue";
import RunView from "./views/RunView.vue";

declare module "vue-router" {
  interface RouteMeta {
    public?: boolean;
  }
}

/** Same-origin redirect targets only: absolute path, never protocol-relative. */
export function safeRedirect(target: unknown): string | null {
  if (typeof target !== "string") {
    return null;
  }
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) {
    return null;
  }
  return target;
}

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: LoginView,
    meta: { public: true },
  },
  { path: "/", name: "home", component: HomeView },
  { path: "/projects/:projectId", name: "project", component: ProjectView },
  {
    path: "/projects/:projectId/runs/new",
    name: "run-new",
    component: NewRunView,
  },
  {
    path: "/projects/:projectId/runs/:runId",
    name: "run",
    component: RunView,
  },
  {
    path: "/projects/:projectId/datasets/:datasetId",
    name: "dataset",
    component: DatasetView,
  },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  const router = createRouter({ history, routes });

  router.beforeEach(async (to) => {
    const auth = useAuthStore();
    await auth.restore();
    if (to.meta.public !== true && !auth.isAuthenticated) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (to.name === "login" && auth.isAuthenticated) {
      return safeRedirect(to.query.redirect) ?? { name: "home" };
    }
    return true;
  });

  return router;
}
