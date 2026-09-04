import { api } from "@/lib/api";

/**
 * Tell the backend a session started or ended, so it can write the audit row.
 *
 * Authentication happens in Keycloak, so the backend never observes a login on
 * its own — which is why app/audit/events.py's log_login() sat written and
 * uncalled. These are the client half of that.
 *
 * Both swallow their errors deliberately. A failed audit ping must not block a
 * clinician from reaching their workspace or from signing out; the row is
 * evidence about the session, not a precondition for it. A failure is logged
 * so the gap is visible rather than silent.
 */
export async function recordLogin(): Promise<void> {
  try {
    await api("/audit/session/login", { method: "POST", idempotencyKey: null });
  } catch (reason) {
    console.warn("[audit] login not recorded", reason);
  }
}

export async function recordLogout(): Promise<void> {
  try {
    await api("/audit/session/logout", { method: "POST", idempotencyKey: null });
  } catch (reason) {
    console.warn("[audit] logout not recorded", reason);
  }
}
