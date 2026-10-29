<script setup lang="ts">
import { computed } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRouter } from "vue-router";

import { evalClient, recordsClient } from "../api/clients";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();

const meQuery = useQuery({
  queryKey: ["records", "me"],
  queryFn: async () => {
    const { data, error } = await recordsClient.GET("/api/records/auth/me/");
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load your profile.");
    }
    return data;
  },
});

const projectsQuery = useQuery({
  queryKey: ["records", "projects"],
  queryFn: async () => {
    const { data, error } = await recordsClient.GET("/api/records/projects/");
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load projects.");
    }
    return data;
  },
});

const evalQuery = useQuery({
  queryKey: ["eval", "me"],
  queryFn: async () => {
    const { data, error } = await evalClient.GET("/api/eval/me");
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to reach the eval API.");
    }
    return data;
  },
});

const evalOrgCount = computed(() =>
  evalQuery.data.value === undefined ? 0 : Object.keys(evalQuery.data.value.orgs).length,
);

async function signOut() {
  await auth.logout();
  await router.push({ name: "login" });
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>Touchstone</h1>
      <div class="header-user">
        <span
          v-if="meQuery.data.value?.username"
          class="muted"
        >
          {{ meQuery.data.value.username }}
        </span>
        <button
          type="button"
          @click="signOut"
        >
          Sign out
        </button>
      </div>
    </header>

    <section>
      <h2>Organizations</h2>
      <p v-if="meQuery.isPending.value">
        Loading organizations...
      </p>
      <p
        v-else-if="meQuery.isError.value"
        role="alert"
        class="error"
      >
        {{ meQuery.error.value?.message ?? "Failed to load organizations." }}
      </p>
      <p
        v-else-if="!meQuery.data.value?.organizations.length"
        class="muted"
      >
        You are not a member of any organization.
      </p>
      <ul v-else>
        <li
          v-for="org in meQuery.data.value.organizations"
          :key="org.id"
        >
          {{ org.name }} ({{ org.slug }}), role: {{ org.role }}
        </li>
      </ul>
    </section>

    <section>
      <h2>Projects</h2>
      <p v-if="projectsQuery.isPending.value">
        Loading projects...
      </p>
      <p
        v-else-if="projectsQuery.isError.value"
        role="alert"
        class="error"
      >
        {{ projectsQuery.error.value?.message ?? "Failed to load projects." }}
      </p>
      <p
        v-else-if="!projectsQuery.data.value?.results.length"
        class="muted"
      >
        No projects yet.
      </p>
      <template v-else>
        <p class="muted">
          {{ projectsQuery.data.value.count }} total
        </p>
        <ul>
          <li
            v-for="project in projectsQuery.data.value.results"
            :key="project.id"
          >
            {{ project.name }}
          </li>
        </ul>
      </template>
    </section>

    <section>
      <h2>Eval API</h2>
      <p v-if="evalQuery.isPending.value">
        Checking the eval API...
      </p>
      <p
        v-else-if="evalQuery.isError.value"
        role="alert"
        class="error"
      >
        {{ evalQuery.error.value?.message ?? "Failed to reach the eval API." }}
      </p>
      <p v-else-if="evalQuery.data.value">
        Authenticated as user {{ evalQuery.data.value.user_id }} with access to
        {{ evalOrgCount }} {{ evalOrgCount === 1 ? "organization" : "organizations" }}
      </p>
    </section>
  </div>
</template>
