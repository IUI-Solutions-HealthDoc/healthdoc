// Typed fetch client for the HealthDoc API response envelope.
// All backend responses: { success, data, error, meta } (see backend/app/common/envelope.py)
//
// SECURITY: the access token is held **in memory only**. It is deliberately NOT in
// localStorage/sessionStorage — those are readable by any injected script, and a stolen
// clinician token means full patient-record access. The token is re-obtained from
// Keycloak on reload (silent SSO) and refreshed by lib/auth.ts.
// Never add a storage write here without Tech Lead sign-off.

import { apiErrorCode, userFacingApiError } from "./api-error-policy.mjs";
import { sessionExpiredPath } from "./session-policy.mjs";
import { clearAuthToken } from "./auth";
export { userFacingApiError } from "./api-error-policy.mjs";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

let accessToken: string | null = null;

/** Called by lib/auth.ts after login / silent refresh. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: { code: number | string; message: unknown } | null;
  meta: { request_id?: string };
}

export function getUserFacingError(error: unknown, fallback = "The request could not be completed."): string {
  if (error instanceof ApiError) return error.message;
  return fallback;
}

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public requestId?: string,
    public payload?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
  /** 409 module_disabled — render "not offered at this facility", not an error page. */
  get isModuleDisabled(): boolean {
    return this.code === 409 && apiErrorCode(this.payload) === "module_disabled";
  }
  /** 409 stale_write — someone else saved first; show a diff, never silently overwrite. */
  get isStaleWrite(): boolean {
    return this.code === 409 && apiErrorCode(this.payload) === "stale_write";
  }
}

export interface ApiOptions extends RequestInit {
  /**
   * Required on creating POSTs (schema §4A.1) — a retry must not create a
   * duplicate.
   *
   * Pass `null` for a POST that creates nothing (a search, for instance, which
   * is a POST only so identifiers stay out of the URL). That is a deliberate
   * "no key needed" and is not warned about; omitting it entirely still is.
   */
  idempotencyKey?: string | null;
  /** row_version for optimistic concurrency on PATCH (schema §4A.2). */
  ifMatch?: string | number;
}

export async function api<T>(path: string, init: ApiOptions = {}): Promise<T> {
  const { idempotencyKey, ifMatch, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();

  if (method === "POST" && idempotencyKey === undefined) {
    // Fail loudly in dev so it is caught before a duplicate payment reaches
    // production. `null` is an explicit opt-out and stays quiet — a warning
    // that fires on every search is a warning nobody reads.
    console.warn(`[api] POST ${path} without an Idempotency-Key (schema §4A.1)`);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      ...(ifMatch !== undefined ? { "If-Match": String(ifMatch) } : {}),
      ...rest.headers,
    },
  });

  let body: Envelope<T>;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    if (res.status === 401) handleExpiredSession();
    throw new ApiError(
      res.status,
      userFacingApiError(res.status),
      res.headers.get("x-request-id") ?? undefined,
    );
  }

  if (!body.success || body.error) {
    const statusCode =
      typeof body.error?.code === "number" ? body.error.code : res.status;
    const payload =
      typeof body.error?.code === "string"
        ? { code: body.error.code, message: body.error.message }
        : (body.error?.message ?? body.error);
    if (statusCode === 401) handleExpiredSession();
    throw new ApiError(
      statusCode,
      userFacingApiError(statusCode, payload),
      body.meta?.request_id,
      payload,
    );
  }
  return body.data as T;
}

/**
 * A 401 means the session is gone, so send the user to sign in again.
 *
 * The message "Your session has expired. Sign in again." already existed and
 * nothing acted on it — so an expired session surfaced as a red error on
 * whatever screen made the call, telling the clinician to do something the
 * page gave them no way to do. Worst on a consultation: the note is still on
 * screen, Submit keeps failing, and the instruction is to sign in again with
 * no sign-in to go to.
 *
 * Centralised here rather than per-screen: every screen calls api(), and the
 * ones that would forget are the long-lived clinical ones where it matters.
 *
 * `?reason=session-expired` is what LoginScreen reads to explain why the user
 * is suddenly at sign-in, and sessionExpiredPath preserves where they were.
 */
let redirectingToLogin = false;

function handleExpiredSession(): void {
  if (typeof window === "undefined") return;
  // The login page itself makes calls; redirecting from there would loop.
  if (window.location.pathname.startsWith("/login")) return;
  // A screen that fires several requests at once would otherwise queue up
  // several navigations, and the last one wins with a different `redirect`.
  if (redirectingToLogin) return;
  redirectingToLogin = true;

  clearAuthToken();
  setAccessToken(null);
  window.location.replace(
    sessionExpiredPath(window.location.pathname, window.location.search),
  );
}

/** Money always arrives as a string ("50.00"). Never parseFloat it — paise get lost. */
export function formatMoney(amount: string, currency = "INR"): string {
  const [rupees, paise = "00"] = amount.split(".");
  const grouped = Number(rupees).toLocaleString("en-IN");
  return `${currency === "INR" ? "₹" : currency + " "}${grouped}.${paise.padEnd(2, "0")}`;
}

/** Timestamps are ISO-8601 UTC; display in the facility's timezone (IST default). */
export function formatDateTime(iso: string, timeZone = "Asia/Kolkata"): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(iso));
}

/** Generate once when a form opens — stable across retries of the same user action. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
