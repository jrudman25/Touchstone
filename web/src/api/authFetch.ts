import { useAuthStore } from "../stores/auth";

const AUTH_TOKEN_PATH = "/api/records/auth/token";

function withBearer(base: Request, token: string): Request {
  const headers = new Headers(base.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return new Request(base, { headers });
}

/**
 * fetch wrapper for authenticated API calls.
 *
 * Sends the in-memory access token as a bearer header. On a 401 (except the
 * auth-token endpoints themselves) it tries exactly one token refresh and one
 * retry; if a concurrent call already refreshed, it just retries with the
 * newer token. Never retries more than once.
 */
export async function authFetch(request: Request): Promise<Response> {
  const auth = useAuthStore();
  const usedToken = auth.accessToken;
  const retry = request.clone();

  const response = await globalThis.fetch(
    usedToken === null ? request : withBearer(request, usedToken),
  );

  if (
    response.status !== 401 ||
    new URL(request.url).pathname.startsWith(AUTH_TOKEN_PATH)
  ) {
    return response;
  }

  const currentToken = auth.accessToken;
  if (currentToken !== null && currentToken !== usedToken) {
    // Another in-flight call already refreshed the token.
    return globalThis.fetch(withBearer(retry, currentToken));
  }

  const refreshed = await auth.refresh();
  const newToken = auth.accessToken;
  if (!refreshed || newToken === null) {
    // Refresh failed and cleared the session; hand back the original 401.
    return response;
  }
  return globalThis.fetch(withBearer(retry, newToken));
}
