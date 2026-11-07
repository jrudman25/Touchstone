<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useQuery } from "@tanstack/vue-query";
import { useRoute, useRouter } from "vue-router";

import { evalClient, recordsClient } from "../api/clients";
import type { components } from "../api/generated/records";
import { canWrite, roleIn, useMeQuery } from "../composables/useMe";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => {
  const value = Number(route.params.projectId);
  return Number.isInteger(value) && value > 0 ? value : null;
});

const meQuery = useMeQuery();
const projectQuery = useQuery({
  queryKey: computed(() => ["records", "project", projectId.value]),
  enabled: computed(() => projectId.value !== null),
  queryFn: async () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    const { data, error } = await recordsClient.GET(
      "/api/records/projects/{id}/",
      { params: { path: { id } } },
    );
    if (error) throw error;
    return data;
  },
});
const writable = computed(() => {
  const org = projectQuery.data.value?.organization;
  return org !== undefined && canWrite(roleIn(meQuery.data.value, org));
});

type Page<T> = { results?: T[] | undefined; next?: string | null | undefined };

async function fetchAll<T>(
  fetchPage: (page: number) => Promise<Page<T>>,
): Promise<T[]> {
  const out: T[] = [];
  let page = 1;
  for (;;) {
    const data = await fetchPage(page);
    out.push(...(data.results ?? []));
    if (!data.next) return out;
    page += 1;
  }
}

const selectedTemplate = ref<number | null>(null);
const selectedVersion = ref<number | null>(null);
const selectedDataset = ref<number | null>(null);
const selectedModels = ref<Set<number>>(new Set());
const selectedScorers = ref<Set<number>>(new Set());
const seed = ref(0);
const submitError = ref<string | null>(null);
const submitting = ref(false);

const templatesQuery = useQuery({
  queryKey: ["records", "templates", projectId.value],
  enabled: computed(() => projectId.value !== null),
  queryFn: () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    return fetchAll<components["schemas"]["PromptTemplate"]>((page) =>
      recordsClient.GET("/api/records/prompt-templates/", {
        params: { query: { project: id, page, page_size: 200 } },
      }).then((r) => (r.data ?? {}) as Page<never>),
    );
  },
});
const versionsQuery = useQuery({
  queryKey: ["records", "versions", () => selectedTemplate.value],
  queryFn: () =>
    fetchAll<components["schemas"]["PromptVersion"]>((page) =>
      recordsClient.GET("/api/records/prompt-versions/", {
        params: { query: { template: selectedTemplate.value!, page, page_size: 200 } },
      }).then((r) => (r.data ?? {}) as Page<never>),
    ),
  enabled: computed(() => selectedTemplate.value !== null),
});
const datasetsQuery = useQuery({
  queryKey: ["records", "datasets", projectId.value],
  enabled: computed(() => projectId.value !== null),
  queryFn: () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    return fetchAll<components["schemas"]["Dataset"]>((page) =>
      recordsClient.GET("/api/records/datasets/", {
        params: { query: { project: id, page, page_size: 200 } },
      }).then((r) => (r.data ?? {}) as Page<never>),
    );
  },
});
const providersQuery = useQuery({
  queryKey: ["records", "providers", () => projectQuery.data.value?.organization],
  queryFn: () =>
    fetchAll<components["schemas"]["ProviderConfig"]>((page) =>
      recordsClient.GET("/api/records/providers/", {
        params: {
          query: { organization: projectQuery.data.value!.organization, page, page_size: 200 },
        },
      }).then((r) => (r.data ?? {}) as Page<never>),
    ),
  enabled: computed(() => projectQuery.data.value?.organization !== undefined),
});
const modelsQuery = useQuery({
  queryKey: ["records", "models", providersQuery.data],
  queryFn: async () => {
    const providers = providersQuery.data.value ?? [];
    const all: components["schemas"]["ModelConfig"][][] = [];
    for (const provider of providers) {
      all.push(
        await fetchAll<components["schemas"]["ModelConfig"]>((page) =>
          recordsClient.GET("/api/records/models/", {
            params: { query: { provider: provider.id, page, page_size: 200 } },
          }).then((r) => (r.data ?? {}) as Page<never>),
        ),
      );
    }
    return { providers, models: all.flat() };
  },
  enabled: computed(() => providersQuery.data.value !== undefined),
});
const scorersQuery = useQuery({
  queryKey: ["records", "scorers", projectId.value],
  enabled: computed(() => projectId.value !== null),
  queryFn: () => {
    const id = projectId.value;
    if (id === null) {
      throw new Error("Project not found.");
    }
    return fetchAll<components["schemas"]["ScorerConfig"]>((page) =>
      recordsClient.GET("/api/records/scorers/", {
        params: { query: { project: id, page, page_size: 200 } },
      }).then((r) => (r.data ?? {}) as Page<never>),
    );
  },
});


// The records API orders by id; within a template, id order matches version number order,
// so index-reversing the list is newest-first without a sort.
const sortedVersions = computed(() => {
  const vs = versionsQuery.data.value ?? [];
  return vs.map((_, i) => vs[vs.length - 1 - i]);
});
const chosenVersion = computed(
  () => sortedVersions.value.find((v) => v.id === selectedVersion.value) ?? null,
);
const versionVariables = computed(
  () => (chosenVersion.value?.variables ?? []) as string[],
);
const modelRows = computed(
  () =>
    (modelsQuery.data.value?.models ?? []) as components["schemas"]["ModelConfig"][],
);
const providerRows = computed(
  () =>
    (modelsQuery.data.value?.providers ?? []) as components["schemas"]["ProviderConfig"][],
);
function providerKind(providerId: number): string | undefined {
  return providerRows.value.find((p) => p.id === providerId)?.kind;
}

function selectTemplate(id: number) {
  selectedTemplate.value = id;
  selectedVersion.value = sortedVersions.value[0]?.id ?? null;
}

// Versions load after the template is picked: default to the newest once they
// arrive or replace a selection that is no longer in the list.
watch(sortedVersions, (versions) => {
  if (versions.length && !versions.some((v) => v.id === selectedVersion.value)) {
    selectedVersion.value = versions[0].id;
  }
});

const canSubmit = computed(
  () =>
    selectedVersion.value !== null &&
    selectedDataset.value !== null &&
    selectedModels.value.size > 0 &&
    !submitting.value,
);

async function submit() {
  const id = projectId.value;
  if (!canSubmit.value || id === null) return;
  submitting.value = true;
  submitError.value = null;
  try {
    const { data, error, response } = await evalClient.POST("/api/eval/runs", {
      body: {
        project_id: id,
        prompt_version_id: selectedVersion.value!,
        dataset_id: selectedDataset.value!,
        model_config_ids: [...selectedModels.value],
        scorer_ids: [...selectedScorers.value],
        seed: seed.value,
      },
    });
    if (error) {
      const detail = (error as { detail?: unknown }).detail;
      submitError.value =
        typeof detail === "string"
          ? detail
          : response.status === 422
            ? "Invalid run request."
            : "Could not create the run.";
      return;
    }
    router.push({ name: "run", params: { projectId: projectId.value, runId: data.id } });
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <main class="page">
    <p>
      <RouterLink :to="{ name: 'project', params: { projectId } }">
        Back to project
      </RouterLink>
    </p>
    <h1>New run</h1>
    <p
      v-if="!writable"
      class="muted"
    >
      An editor or owner role is required to create runs.
    </p>
    <form
      v-else
      @submit.prevent="submit"
    >
      <label>
        Prompt template
        <select
          :value="selectedTemplate ?? ''"
          @change="selectTemplate(Number(($event.target as HTMLSelectElement).value))"
        >
          <option
            value=""
            disabled
          >Choose…</option>
          <option
            v-for="t in templatesQuery.data.value ?? []"
            :key="t.id"
            :value="t.id"
          >
            {{ t.name }}
          </option>
        </select>
      </label>
      <label>
        Version
        <select
          v-model.number="selectedVersion"
          :disabled="!selectedTemplate"
        >
          <option
            v-for="v in sortedVersions"
            :key="v.id"
            :value="v.id"
          >
            v{{ v.number }}
          </option>
        </select>
      </label>
      <p
        v-if="versionVariables.length"
        class="muted"
      >
        Variables: {{ versionVariables.join(", ") }}
      </p>
      <label>
        Dataset
        <select v-model.number="selectedDataset">
          <option
            :value="null"
            disabled
          >Choose…</option>
          <option
            v-for="d in datasetsQuery.data.value ?? []"
            :key="d.id"
            :value="d.id"
            :disabled="d.row_count === null"
          >
            {{ d.name }}{{ d.row_count === null ? " (no rows)" : ` (${d.row_count} rows)` }}
          </option>
        </select>
      </label>
      <fieldset>
        <legend>Models</legend>
        <label
          v-for="m in modelRows"
          :key="m.id"
        >
          <input
            type="checkbox"
            :value="m.id"
            :disabled="providerKind(m.provider) !== 'mock'"
            @change="(e) => (e.target as HTMLInputElement).checked ? selectedModels.add(m.id) : selectedModels.delete(m.id)"
          >
          {{ m.model_name }}
          <span
            v-if="providerKind(m.provider) !== 'mock'"
            class="muted"
          >(not supported yet)</span>
        </label>
      </fieldset>
      <fieldset>
        <legend>Scorers</legend>
        <label
          v-for="s in scorersQuery.data.value ?? []"
          :key="s.id"
        >
          <input
            type="checkbox"
            :value="s.id"
            :disabled="s.kind === 'llm_judge'"
            @change="(e) => (e.target as HTMLInputElement).checked ? selectedScorers.add(s.id) : selectedScorers.delete(s.id)"
          >
          {{ s.name }}
          <span
            v-if="s.kind === 'llm_judge'"
            class="muted"
          >(not supported yet)</span>
        </label>
      </fieldset>
      <label>
        Seed
        <input
          v-model.number="seed"
          type="number"
          min="0"
        >
      </label>
      <p
        v-if="submitError"
        class="error"
        role="alert"
      >
        {{ submitError }}
      </p>
      <button
        type="submit"
        :disabled="!canSubmit"
      >
        Create run
      </button>
    </form>
  </main>
</template>
