<script setup lang="ts">
import { computed, ref } from "vue";
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { RouterLink, useRoute } from "vue-router";

import { recordsClient } from "../api/clients";
import type { components } from "../api/generated/records";
import { canWrite, roleIn, useMeQuery } from "../composables/useMe";

const route = useRoute();
const queryClient = useQueryClient();

const projectId = computed(() => {
  const value = Number(route.params.projectId);
  return Number.isInteger(value) && value > 0 ? value : null;
});

const meQuery = useMeQuery();

const projectQuery = useQuery({
  queryKey: computed(() => ["records", "projects", projectId.value]),
  enabled: computed(() => projectId.value !== null),
  queryFn: async () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    const { data, error, response } = await recordsClient.GET(
      "/api/records/projects/{id}/",
      { params: { path: { id } } },
    );
    if (response.status === 404) {
      throw new Error("Project not found.");
    }
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load the project.");
    }
    return data;
  },
});

const datasetsQuery = useQuery({
  queryKey: computed(() => ["records", "datasets", "project", projectId.value]),
  enabled: computed(() => projectId.value !== null),
  queryFn: async () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    const { data, error } = await recordsClient.GET("/api/records/datasets/", {
      params: { query: { project: id, page_size: 200 } },
    });
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load datasets.");
    }
    return data;
  },
});

const canCreate = computed(() => {
  const organization = projectQuery.data.value?.organization;
  return (
    organization !== undefined && canWrite(roleIn(meQuery.data.value, organization))
  );
});

const newName = ref("");
const createError = ref<string | null>(null);

function fieldErrors(error: unknown): string {
  if (error !== null && typeof error === "object") {
    const parts = Object.entries(error).flatMap(([field, messages]) =>
      Array.isArray(messages) ? messages.map((m) => `${field}: ${String(m)}`) : [],
    );
    if (parts.length > 0) {
      return parts.join(" ");
    }
  }
  return "The dataset could not be created.";
}

const createMutation = useMutation({
  mutationFn: async (name: string) => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    const { data, error, response } = await recordsClient.POST(
      "/api/records/datasets/",
      // The generated Dataset type carries read-only fields; the API ignores them.
      { body: { project: id, name } as components["schemas"]["Dataset"] },
    );
    if (response.status === 400) {
      throw new Error(fieldErrors(error));
    }
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to create the dataset.");
    }
    return data;
  },
  onSuccess: async () => {
    newName.value = "";
    createError.value = null;
    await queryClient.invalidateQueries({
      queryKey: ["records", "datasets", "project", projectId.value],
    });
  },
  onError: (error) => {
    createError.value = error.message;
  },
});

function submitCreate() {
  const name = newName.value.trim();
  if (name === "" || createMutation.isPending.value) {
    return;
  }
  createError.value = null;
  createMutation.mutate(name);
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>{{ projectQuery.data.value?.name ?? "Project" }}</h1>
    </header>
    <p>
      <RouterLink
        :to="{ name: 'home' }"
        class="muted"
      >
        Back to projects
      </RouterLink>
    </p>

    <p
      v-if="projectId === null"
      role="alert"
      class="error"
    >
      Project not found.
    </p>
    <template v-else>
      <p v-if="projectQuery.isPending.value">
        Loading project...
      </p>
      <p
        v-else-if="projectQuery.isError.value"
        role="alert"
        class="error"
      >
        {{ projectQuery.error.value?.message ?? "Failed to load the project." }}
      </p>
      <template v-else-if="projectQuery.data.value">
        <section>
          <h2>Datasets</h2>
          <p v-if="datasetsQuery.isPending.value">
            Loading datasets...
          </p>
          <p
            v-else-if="datasetsQuery.isError.value"
            role="alert"
            class="error"
          >
            {{ datasetsQuery.error.value?.message ?? "Failed to load datasets." }}
          </p>
          <p
            v-else-if="!datasetsQuery.data.value?.results.length"
            class="muted"
          >
            No datasets yet.
          </p>
          <ul v-else>
            <li
              v-for="dataset in datasetsQuery.data.value.results"
              :key="dataset.id"
            >
              <RouterLink
                :to="{
                  name: 'dataset',
                  params: { projectId, datasetId: dataset.id },
                }"
              >
                {{ dataset.name }}
              </RouterLink>
              <span class="muted">
                ({{ dataset.row_count === null ? "No rows uploaded" : `${dataset.row_count} rows` }})
              </span>
            </li>
          </ul>
        </section>

        <section v-if="canCreate">
          <h2>New dataset</h2>
          <form @submit.prevent="submitCreate">
            <div class="field">
              <label for="dataset-name">Dataset name</label>
              <input
                id="dataset-name"
                v-model="newName"
                name="dataset-name"
                type="text"
                required
              >
            </div>
            <p
              v-if="createError"
              role="alert"
              class="error"
            >
              {{ createError }}
            </p>
            <button
              type="submit"
              :disabled="createMutation.isPending.value || newName.trim() === ''"
            >
              Create dataset
            </button>
          </form>
        </section>
      </template>
    </template>
  </div>
</template>
