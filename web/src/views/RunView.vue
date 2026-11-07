<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { useRoute } from "vue-router";

import { evalClient } from "../api/clients";
import type { components } from "../api/generated/eval";
import { canWrite, roleIn, useMeQuery } from "../composables/useMe";

type Run = components["schemas"]["Run"];
type Result = components["schemas"]["Result"];

const route = useRoute();
const queryClient = useQueryClient();
const projectId = computed(() => {
  const value = Number(route.params.projectId);
  return Number.isInteger(value) && value > 0 ? value : null;
});
const runId = computed(() => String(route.params.runId ?? ""));
const validId = computed(() => /^[0-9a-f]{24}$/i.test(runId.value));

const meQuery = useMeQuery();

const runQuery = useQuery({
  queryKey: ["eval", "run", runId],
  queryFn: async () => {
    const { data, error, response } = await evalClient.GET(
      "/api/eval/runs/{run_id}",
      { params: { path: { run_id: runId.value } } },
    );
    if (response.status === 404) return null;
    if (error) throw error;
    return data;
  },
  enabled: () => validId.value,
  refetchInterval: (query) =>
    ["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false,
});

const run = computed<Run | null>(() => runQuery.data.value ?? null);

const modelFilter = ref<number | null>(null);
const errorsOnly = ref(false);

const resultsQuery = useInfiniteQuery({
  queryKey: computed(() => [
    "eval",
    "results",
    runId.value,
    modelFilter.value,
    errorsOnly.value,
  ]),
  initialPageParam: null as string | null,
  getNextPageParam: (last: { next_after: string | null }) => last.next_after,
  queryFn: async ({ pageParam }) => {
    const { data, error } = await evalClient.GET(
      "/api/eval/runs/{run_id}/results",
      {
        params: {
          path: { run_id: runId.value },
          query: {
            limit: 50,
            ...(pageParam ? { after: pageParam } : {}),
            ...(modelFilter.value !== null
              ? { model_config_id: modelFilter.value }
              : {}),
            errors_only: errorsOnly.value,
          },
        },
      },
    );
    if (error) throw error;
    return data;
  },
  enabled: computed(() => validId.value && run.value !== null),
  refetchInterval: () =>
    ["queued", "running"].includes(run.value?.status ?? "") ? 2000 : false,
});

const pages = computed<Result[]>(
  () => resultsQuery.data.value?.pages.flatMap((page) => page.items) ?? [],
);

// one final fetch so results written after the last poll still appear
watch(
  () => run.value?.status,
  (status, previous) => {
    if (
      status &&
      !["queued", "running"].includes(status) &&
      ["queued", "running"].includes(previous ?? "")
    ) {
      queryClient.invalidateQueries({
        queryKey: ["eval", "results", runId.value],
      });
    }
  },
);

const scorerNames = computed(() => {
  const map = new Map<number, string>();
  for (const scorer of run.value?.snapshot.scorers ?? []) {
    map.set(scorer.scorer_id, scorer.name);
  }
  return map;
});

const progressPercent = computed(() => {
  const totals = run.value?.totals;
  if (!totals || totals.rows === 0) return 0;
  return Math.round((totals.done / totals.rows) * 100);
});

const writable = computed(() => {
  const org = run.value?.organization_id;
  return org !== undefined && canWrite(roleIn(meQuery.data.value, org));
});

const cancelMutation = useMutation({
  mutationFn: async () => {
    const { data, error } = await evalClient.POST(
      "/api/eval/runs/{run_id}/cancel",
      { params: { path: { run_id: runId.value } } },
    );
    if (error) throw error;
    return data;
  },
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["eval", "run", runId] });
  },
});

const cancelError = computed(() => {
  const error = cancelMutation.error.value as { detail?: string } | null;
  return error?.detail ?? (cancelMutation.isError.value ? "Cancel failed." : null);
});

function fmtScore(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : value.toFixed(2);
}
function fmtTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}
</script>

<template>
  <main class="page">
    <p>
      <RouterLink :to="{ name: 'project', params: { projectId } }">
        Back to project
      </RouterLink>
    </p>
    <p
      v-if="!validId"
      class="error"
      role="alert"
    >
      Run not found.
    </p>
    <p
      v-else-if="runQuery.isLoading.value"
      class="muted"
    >
      Loading run...
    </p>
    <p
      v-else-if="runQuery.isError.value"
      class="error"
      role="alert"
    >
      Failed to load the run.
    </p>
    <p
      v-else-if="run === null"
      class="error"
      role="alert"
    >
      Run not found.
    </p>
    <template v-else-if="run">
      <header class="page-header">
        <h1>Run <code>{{ run.id }}</code></h1>
        <span
          class="status-badge"
          :data-status="run.status"
        >{{ run.status }}</span>
      </header>

      <section aria-label="Progress">
        <progress
          :value="progressPercent"
          max="100"
        >
          {{ progressPercent }}%
        </progress>
        <p class="muted">
          {{ run.totals.done }} of {{ run.totals.rows }} done, {{ run.totals.failed }} failed.
          Created {{ fmtTime(run.created_at) }}<template v-if="run.finished_at">
            , finished {{ fmtTime(run.finished_at) }}
          </template>.
        </p>
        <p
          v-if="run.error"
          class="error"
          role="alert"
        >
          {{ run.error }}
        </p>
        <p
          v-if="cancelError"
          class="error"
          role="alert"
        >
          {{ cancelError }}
        </p>
        <button
          v-if="writable && ['queued', 'running'].includes(run.status)"
          type="button"
          :disabled="cancelMutation.isPending.value"
          @click="cancelMutation.mutate()"
        >
          Cancel run
        </button>
      </section>

      <section aria-label="Snapshot">
        <h2>Configuration</h2>
        <dl class="facts">
          <dt>Prompt</dt>
          <dd>template {{ run.snapshot.prompt.template_id }}, version {{ run.snapshot.prompt.number }}</dd>
          <dt>Dataset</dt>
          <dd>{{ run.dataset_id }}</dd>
          <dt>Models</dt>
          <dd>{{ run.snapshot.models.map((m) => m.model_name).join(", ") }}</dd>
          <dt>Scorers</dt>
          <dd>{{ run.snapshot.scorers.map((s) => s.name).join(", ") || "none" }}</dd>
          <dt>Seed</dt>
          <dd>{{ run.snapshot.seed }}</dd>
        </dl>
      </section>

      <section aria-label="Summary">
        <h2>Per-model summary</h2>
        <table>
          <thead>
            <tr>
              <th>Model</th><th>Mean score</th>
              <th
                v-for="[id, name] in scorerNames"
                :key="id"
              >
                {{ name }}
              </th>
              <th>p95 ms</th><th>Cost</th><th>Errors</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="model in run.snapshot.models"
              :key="model.model_config_id"
            >
              <td>{{ model.model_name }}</td>
              <template v-if="run.summary[String(model.model_config_id)]">
                <td>{{ fmtScore(run.summary[String(model.model_config_id)].mean_score) }}</td>
                <td
                  v-for="[id] in scorerNames"
                  :key="id"
                >
                  {{ fmtScore(run.summary[String(model.model_config_id)].by_scorer[String(id)]) }}
                </td>
                <td>{{ run.summary[String(model.model_config_id)].p95_latency_ms ?? "-" }}</td>
                <td>{{ run.summary[String(model.model_config_id)].cost_usd.toFixed(4) }}</td>
                <td>{{ run.summary[String(model.model_config_id)].error_count }}</td>
              </template>
              <td
                v-else
                :colspan="4 + scorerNames.size"
                class="muted"
              >
                no results yet
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section aria-label="Results">
        <h2>Results</h2>
        <div class="filters">
          <label>
            Model
            <select v-model="modelFilter">
              <option :value="null">All</option>
              <option
                v-for="m in run.snapshot.models"
                :key="m.model_config_id"
                :value="m.model_config_id"
              >
                {{ m.model_name }}
              </option>
            </select>
          </label>
          <label><input
            v-model="errorsOnly"
            type="checkbox"
          > Errors only</label>
        </div>
        <p
          v-if="pages.length === 0"
          class="muted"
        >
          No results yet.
        </p>
        <table v-else>
          <thead>
            <tr><th>#</th><th>Model</th><th>Input</th><th>Expected</th><th>Output</th><th>Scores</th><th>ms</th><th>Error</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="r in pages"
              :key="`${r.model_config_id}:${r.row_index}`"
            >
              <td>{{ r.row_index }}</td>
              <td>{{ r.model_config_id }}</td>
              <td><code>{{ JSON.stringify(r.input) }}</code></td>
              <td>{{ r.expected ?? "-" }}</td>
              <td class="output-cell">
                <pre>{{ r.output ?? "-" }}</pre><span
                  v-if="r.context_limited"
                  title="context limited"
                >⚠</span>
              </td>
              <td>
                <template
                  v-for="s in r.scores"
                  :key="s.scorer_id"
                >
                  <span :title="s.reason ?? undefined">{{ scorerNames.get(s.scorer_id) ?? s.scorer_id }}: {{ fmtScore(s.value) }}</span><br>
                </template>
              </td>
              <td>{{ r.latency_ms ?? "-" }}</td>
              <td>{{ r.error ?? "" }}</td>
            </tr>
          </tbody>
        </table>
        <p
          v-if="resultsQuery.isFetchNextPageError.value"
          class="error"
          role="alert"
        >
          Failed to load more results.
        </p>
        <button
          v-if="resultsQuery.hasNextPage.value"
          type="button"
          :disabled="resultsQuery.isFetchingNextPage.value"
          @click="resultsQuery.fetchNextPage()"
        >
          Load more
        </button>
      </section>
    </template>
  </main>
</template>
