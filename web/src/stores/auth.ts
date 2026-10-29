import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { publicRecordsClient } from "../api/clients";

export const useAuthStore = defineStore("auth", () => {
  // In memory only: the refresh cookie restores the session on reload.
  const accessToken = ref<string | null>(null);
  const isAuthenticated = computed(() => accessToken.value !== null);

  let refreshPromise: Promise<boolean> | null = null;
  let restorePromise: Promise<void> | null = null;

  function clear(): void {
    accessToken.value = null;
  }

  async function login(username: string, password: string): Promise<void> {
    let result;
    try {
      result = await publicRecordsClient.POST("/api/records/auth/token/", {
        body: { username, password },
        credentials: "same-origin",
      });
    } catch {
      throw new Error("Sign in failed. Try again.");
    }
    if (result.data) {
      accessToken.value = result.data.access;
      return;
    }
    if (result.response.status === 401) {
      throw new Error("Invalid username or password.");
    }
    throw new Error("Sign in failed. Try again.");
  }

  function refresh(): Promise<boolean> {
    refreshPromise ??= doRefresh().finally(() => {
      refreshPromise = null;
    });
    return refreshPromise;
  }

  async function doRefresh(): Promise<boolean> {
    try {
      const { data, response } = await publicRecordsClient.POST(
        "/api/records/auth/token/refresh/",
        { headers: { "X-Auth-Refresh": "1" }, credentials: "same-origin" },
      );
      if (response.ok && data) {
        accessToken.value = data.access;
        return true;
      }
    } catch {
      // Network failures take the same path as a rejected refresh.
    }
    clear();
    return false;
  }

  /** Runs refresh() once per app load; used by the router guard. */
  function restore(): Promise<void> {
    restorePromise ??= refresh().then(() => undefined);
    return restorePromise;
  }

  async function logout(): Promise<void> {
    try {
      await publicRecordsClient.POST("/api/records/auth/logout/", {
        credentials: "same-origin",
      });
    } catch {
      // The session is cleared locally even if the request fails.
    }
    clear();
  }

  return { accessToken, isAuthenticated, login, refresh, restore, logout, clear };
});
