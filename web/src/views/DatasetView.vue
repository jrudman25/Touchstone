<script setup lang="ts">
import { computed, ref } from "vue";
import { useQuery, useQueryClient } from "@tanstack/vue-query";
import { RouterLink, useRoute } from "vue-router";

import { evalClient, recordsClient } from "../api/clients";
import type { components } from "../api/generated/eval";
import { canWrite, roleIn, useMeQuery } from "../composables/useMe";

type UploadErrorResponse = components["schemas"]["UploadErrorResponse"];
type ErrorDetail = components["schemas"]["ErrorDetail"];
type UploadLineError = components["schemas"]["UploadLineError"];

const route = useRoute();
const queryClient = useQueryClient();

const datasetId = computed(() => {
  const value = Number(route.params.datasetId);
  return Number.isInteger(value) && value > 0 ? value : null;
});

const meQuery = useMeQuery();

const datasetQuery = useQuery({
  queryKey: computed(() => ["records", "datasets", datasetId.value]),
  enabled: computed(() => datasetId.value !== null),
  queryFn: async () => {
    const id = datasetId.value;
    if (id === null) {
      throw new Error("Dataset not found.");
    }
    const { data, error, response } = await recordsClient.GET(
      "/api/records/datasets/{id}/",
      { params: { path: { id } } },
    );
    if (response.status === 404) {
      throw new Error("Dataset not found.");
    }
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load the dataset.");
    }
    return data;
  },
});

const rowCount = computed(() => datasetQuery.data.value?.row_count ?? null);

const rowsQuery = useQuery({
  queryKey: computed(() => ["eval", "dataset-rows", datasetId.value]),
  enabled: computed(() => rowCount.value !== null),
  queryFn: async () => {
    const id = datasetId.value;
    if (id === null) {
      throw new Error("Dataset not found.");
    }
    const { data, error } = await evalClient.GET(
      "/api/eval/datasets/{dataset_id}/rows",
      { params: { path: { dataset_id: id }, query: { limit: 50 } } },
    );
    if (error !== undefined || data === undefined) {
      throw new Error("Failed to load rows.");
    }
    return data;
  },
});

const canUpload = computed(() => {
  const organization = datasetQuery.data.value?.organization;
  return (
    rowCount.value === null &&
    organization !== undefined &&
    canWrite(roleIn(meQuery.data.value, organization))
  );
});

const fileInput = ref<HTMLInputElement | null>(null);
const selectedFile = ref<File | null>(null);
const uploading = ref(false);
const uploadSuccess = ref<string | null>(null);
const uploadError = ref<string | null>(null);
const uploadLineErrors = ref<UploadLineError[]>([]);

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
  uploadSuccess.value = null;
  uploadError.value = null;
  uploadLineErrors.value = [];
}

async function upload() {
  const file = selectedFile.value;
  const id = datasetId.value;
  if (file === null || id === null || uploading.value) {
    return;
  }
  uploading.value = true;
  uploadSuccess.value = null;
  uploadError.value = null;
  uploadLineErrors.value = [];
  try {
    const text = await file.text();
    const { data, error, response } = await evalClient.POST(
      "/api/eval/datasets/{dataset_id}/rows",
      {
        params: { path: { dataset_id: id } },
        body: text,
        bodySerializer: (body) => body as string,
        headers: { "Content-Type": "application/x-ndjson" },
      },
    );
    if (data !== undefined) {
      uploadSuccess.value = `Uploaded ${data.row_count} rows.`;
      selectedFile.value = null;
      if (fileInput.value !== null) {
        fileInput.value.value = "";
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["records", "datasets", id] }),
        queryClient.invalidateQueries({ queryKey: ["eval", "dataset-rows", id] }),
      ]);
      return;
    }
    if (response.status === 400) {
      const body = error as UploadErrorResponse | undefined;
      uploadError.value = body?.detail ?? "Invalid JSONL upload.";
      uploadLineErrors.value = body?.errors ?? [];
    } else if (response.status === 409) {
      uploadError.value = "This dataset already has rows.";
    } else if (response.status === 403) {
      uploadError.value = "You do not have permission to upload to this dataset.";
    } else {
      uploadError.value =
        (error as ErrorDetail | undefined)?.detail ?? "Upload failed. Try again.";
    }
  } catch {
    uploadError.value = "Upload failed. Try again.";
  } finally {
    uploading.value = false;
  }
}

function formatInput(input: Record<string, string | number | boolean>): string {
  return Object.entries(input)
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(", ");
}
</script>

<template>
  <div class="page">
    <header class="page-header">
      <h1>{{ datasetQuery.data.value?.name ?? "Dataset" }}</h1>
    </header>
    <p>
      <RouterLink
        :to="{
          name: 'project',
          params: { projectId: datasetQuery.data.value?.project ?? route.params.projectId },
        }"
        class="muted"
      >
        Back to project
      </RouterLink>
    </p>

    <p
      v-if="datasetId === null"
      role="alert"
      class="error"
    >
      Dataset not found.
    </p>
    <template v-else>
      <p v-if="datasetQuery.isPending.value">
        Loading dataset...
      </p>
      <p
        v-else-if="datasetQuery.isError.value"
        role="alert"
        class="error"
      >
        {{ datasetQuery.error.value?.message ?? "Failed to load the dataset." }}
      </p>
      <template v-else-if="datasetQuery.data.value">
        <section>
          <h2>Rows</h2>
          <p
            v-if="rowCount === null"
            class="muted"
          >
            No rows uploaded yet.
          </p>
          <p v-else>
            Rows: {{ rowCount }}
          </p>
        </section>

        <section v-if="canUpload">
          <h2>Upload rows</h2>
          <form @submit.prevent="upload">
            <div class="field">
              <label for="dataset-file">JSONL file</label>
              <input
                id="dataset-file"
                ref="fileInput"
                name="dataset-file"
                type="file"
                accept=".jsonl,.ndjson,application/x-ndjson,application/jsonl"
                @change="onFileChange"
              >
            </div>
            <button
              type="submit"
              :disabled="selectedFile === null || uploading"
            >
              {{ uploading ? "Uploading..." : "Upload" }}
            </button>
          </form>
          <p
            v-if="uploadSuccess"
            role="status"
            class="success"
          >
            {{ uploadSuccess }}
          </p>
          <div
            v-if="uploadError"
            role="alert"
            class="error"
          >
            <p>{{ uploadError }}</p>
            <ul v-if="uploadLineErrors.length > 0">
              <li
                v-for="lineError in uploadLineErrors"
                :key="lineError.line"
              >
                Line {{ lineError.line }}: {{ lineError.message }}
              </li>
            </ul>
            <p
              v-if="uploadLineErrors.length === 50"
              class="muted"
            >
              Showing the first 50 errors.
            </p>
          </div>
        </section>

        <section v-if="rowCount !== null">
          <h2>Preview (first 50 rows)</h2>
          <p v-if="rowsQuery.isPending.value">
            Loading rows...
          </p>
          <p
            v-else-if="rowsQuery.isError.value"
            role="alert"
            class="error"
          >
            {{ rowsQuery.error.value?.message ?? "Failed to load rows." }}
          </p>
          <p
            v-else-if="!rowsQuery.data.value?.items.length"
            class="muted"
          >
            No rows to preview.
          </p>
          <table v-else>
            <thead>
              <tr>
                <th>#</th>
                <th>Input</th>
                <th>Expected</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rowsQuery.data.value.items"
                :key="row.row_index"
              >
                <td>{{ row.row_index }}</td>
                <td>{{ formatInput(row.input) }}</td>
                <td
                  :class="{ muted: row.expected === null }"
                >
                  {{ row.expected ?? "none" }}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </template>
  </div>
</template>
