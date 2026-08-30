/**
 * Canonical implementation is src/lib/auth/ (Next src/ layout).
 * Re-export so older imports keep resolving here, mirroring lib/api.ts.
 *
 * This file previously declared its own `getSessionUser()` that threw
 * "Not implemented — F1-W1-03". It is implemented now (Keycloak OIDC, PKCE,
 * silent SSO, in-memory bearer) — see src/lib/auth/keycloak.ts.
 */
export {
  SESSION_PRESENCE_COOKIE,
  SESSION_ROLE_HINT_COOKIE,
  clearAuthToken,
  clearSessionPresence,
  getAuthRole,
  getAuthToken,
  getRoleHint,
  hasSessionPresence,
  setAuthSession,
  setAuthToken,
  setSessionPresence,
} from "../src/lib/auth";
export type { AuthUser } from "../src/lib/auth";

export {
  getKeycloakSessionUser,
  initKeycloak,
  isKeycloakConfigured,
  loginWithKeycloak,
  logoutFromKeycloak,
  mapKeycloakRolesToAppRole,
} from "../src/lib/auth/keycloak";
export type { SessionUser } from "../src/lib/auth/keycloak";
