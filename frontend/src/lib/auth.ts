// F1-W1-03 implements this: Keycloak client (keycloak-js), PKCE login,
// silent token refresh, logout, and role helpers used by route guards.
//
// Realm: healthdoc · Client: healthdoc-frontend (public, PKCE S256)
// Issuer (via nginx): https://localhost/auth/realms/healthdoc

export interface SessionUser {
  sub: string;
  username: string;
  roles: string[];
}

export function getSessionUser(): SessionUser | null {
  throw new Error("Not implemented — F1-W1-03");
}
