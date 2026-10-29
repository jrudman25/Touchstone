import createClient from "openapi-fetch";

import type { paths as EvalPaths } from "./generated/eval";
import type { paths as RecordsPaths } from "./generated/records";
import { authFetch } from "./authFetch";

export const recordsClient = createClient<RecordsPaths>({ fetch: authFetch });

export const evalClient = createClient<EvalPaths>({ fetch: authFetch });

/** Unauthenticated client for the login, refresh, and logout endpoints. */
export const publicRecordsClient = createClient<RecordsPaths>({
  fetch: (request) => globalThis.fetch(request),
});
