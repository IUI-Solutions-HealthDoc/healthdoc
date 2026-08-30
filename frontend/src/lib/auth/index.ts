import type { Role } from "@/config/roles";

/**
 * Auth helpers.
 *
 * Identity = Keycloak OIDC (see keycloak.ts + in-memory Bearer via lib/api).
 * Cookies below are UX-only for Next proxy/middleware navigation — never treat
 * them as proof of identity for API access.
 */

/** Non-secret presence flag for edge redirects (not a bearer token). */
export const SESSION_PRESENCE_COOKIE = "hd_session";
/** UX hint for post-login redirect only — not authorization. */
export const SESSION_ROLE_HINT_COOKIE = "hd_role_hint";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  /**
   * null when the signed-in user holds no realm role this app has a workspace
   * for. Screens must handle it — rendering a default workspace for an
   * unrecognised role is what this type is shaped to prevent.
   */
  role: Role | null;
};

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

function setCookie(name: string, value: string) {
    // `Secure` on anything but plain-HTTP localhost. These carry no token — a
  // presence flag and a role hint — but a cookie without Secure is a scanner
  // finding on its own, and the app is HTTPS everywhere it is not a dev box.
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=86400; SameSite=Lax${secure}`;
}

function deleteCookie(name: string) {
  document.cookie = `${name}=; path=/; max-age=0`;
}

/** True when middleware should treat the browser as "has a session" (UX only). */
export function hasSessionPresence(): boolean {
  return getCookie(SESSION_PRESENCE_COOKIE) === "1";
}

export function setSessionPresence(roleHint?: Role) {
  setCookie(SESSION_PRESENCE_COOKIE, "1");
  if (roleHint) setCookie(SESSION_ROLE_HINT_COOKIE, roleHint);
}

export function clearSessionPresence() {
  deleteCookie(SESSION_PRESENCE_COOKIE);
  deleteCookie(SESSION_ROLE_HINT_COOKIE);
  // Legacy cookies from earlier cookie-identity experiment — clear on logout.
  deleteCookie("auth-token");
  deleteCookie("auth-role");
  deleteCookie("auth-user");
}

export function getRoleHint(): Role | null {
  return (getCookie(SESSION_ROLE_HINT_COOKIE) as Role | null) ?? null;
}

/**
 * @deprecated Cookie identity is retired. Prefer Keycloak + AuthProvider.
 * Kept as thin aliases so existing imports compile during the transition.
 */
export function getAuthToken(): string | null {
  return hasSessionPresence() ? "session" : null;
}

export function getAuthRole(): Role | null {
  return getRoleHint();
}

/**
 * Mark the UX session after a Keycloak login.
 *
 * Presence and role hint only, both non-secret and both forgeable by design —
 * the access token stays in memory and never reaches a cookie or storage. See
 * src/proxy.ts for why forging these buys a rendered shell and nothing else.
 */
export function setAuthSession(user: AuthUser, _token?: string) {
  setSessionPresence(user.role ?? undefined);
}

export function setAuthToken(_token: string) {
  setSessionPresence();
}

export function clearAuthToken() {
  clearSessionPresence();
}
