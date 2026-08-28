import Keycloak from "keycloak-js";
import type { Role } from "@/config/roles";
import { ROLES } from "@/config/roles";
import { setAccessToken } from "@/lib/api";

/**
 * Keycloak OIDC client (realm healthdoc · public client healthdoc-frontend · PKCE).
 * Access token stays in memory via lib/api — never cookies / localStorage.
 */

const url =
  process.env.NEXT_PUBLIC_KEYCLOAK_URL ??
  process.env.NEXT_PUBLIC_KEYCLOAK_PUBLIC_URL ??
  "";
const realm = process.env.NEXT_PUBLIC_KEYCLOAK_REALM ?? "healthdoc";
const clientId =
  process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "healthdoc-frontend";

let keycloak: Keycloak | null = null;
let initPromise: Promise<boolean> | null = null;
const sessionExpiredListeners = new Set<() => void>();

export function onKeycloakSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

function notifySessionExpired() {
  for (const listener of sessionExpiredListeners) listener();
}

export type SessionUser = {
  id: string;
  name: string;
  email: string;
  /** null when the token carries no role this app has a workspace for. */
  role: Role | null;
  sub: string;
  /** Every role on the token, unmapped — what the backend will actually check. */
  roles: string[];
};

function getKeycloak(): Keycloak {
  if (!keycloak) {
    keycloak = new Keycloak({ url, realm, clientId });
  }
  return keycloak;
}

/**
 * Which workspace to open for a user holding these realm roles.
 *
 * Ordered most-privileged first, because a user can hold several: a HOD who is
 * also a doctor should land in the HOD view, and picking by token order would
 * make the landing page depend on how Keycloak happened to serialise the claim.
 *
 * Returns null for a token carrying no role we recognise. The previous version
 * returned RECEPTIONIST as a catch-all, which meant an auditor, a radiology
 * technician, a HOD or a patient all silently landed in the registration desk —
 * a screen they cannot use and whose API calls would 403 with no explanation.
 * "I don't know where you belong" is information; guessing is not.
 */
const ROLE_PRECEDENCE: readonly Role[] = [
  ROLES.SUPERADMIN,
  ROLES.ADMIN,
  ROLES.HOD,
  ROLES.SUPERVISOR,
  ROLES.AUDITOR,
  ROLES.DOCTOR,
  ROLES.NURSE,
  ROLES.PHARMACIST,
  ROLES.LAB_TECH,
  ROLES.RADIOLOGY_TECH,
  ROLES.EMERGENCY,
  ROLES.RECEPTIONIST,
  ROLES.PATIENT,
];

export function mapKeycloakRolesToAppRole(roles: string[]): Role | null {
  const held = new Set(roles.map((r) => r.toLowerCase()));
  const healthDocRole = ROLE_PRECEDENCE.find((role) => held.has(role));
  if (healthDocRole) return healthDocRole;
  // Keycloak's own realm-management role is only a compatibility fallback.
  // A platform superadmin commonly holds realm-admin too; checking it first
  // downgraded that user into the facility-admin workspace.
  if (held.has("realm-admin")) return ROLES.ADMIN;
  return null;
}

export function sessionUserFromKeycloak(kc: Keycloak): SessionUser | null {
  if (!kc.authenticated || !kc.tokenParsed) return null;
  const parsed = kc.tokenParsed as {
    sub?: string;
    preferred_username?: string;
    name?: string;
    email?: string;
    realm_access?: { roles?: string[] };
    resource_access?: Record<string, { roles?: string[] }>;
  };
  const realmRoles = parsed.realm_access?.roles ?? [];
  const clientRoles = parsed.resource_access?.[clientId]?.roles ?? [];
  const roles = [...realmRoles, ...clientRoles];
  const role = mapKeycloakRolesToAppRole(roles);
  const sub = parsed.sub ?? "";
  return {
    id: sub,
    sub,
    name: parsed.name || parsed.preferred_username || "User",
    email: parsed.email || "",
    role,
    roles,
  };
}

function syncAccessToken(kc: Keycloak) {
  setAccessToken(kc.token ?? null);
}

/**
 * Initialize Keycloak once (silent SSO). Returns whether the user is authenticated.
 */
export async function initKeycloak(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (!initPromise) {
    const kc = getKeycloak();
    initPromise = kc
      .init({
        onLoad: "check-sso",
        pkceMethod: "S256",
        checkLoginIframe: false,
        silentCheckSsoRedirectUri:
          typeof window !== "undefined"
            ? `${window.location.origin}/silent-check-sso.html`
            : undefined,
      })
      .then((authenticated) => {
        if (authenticated) {
          syncAccessToken(kc);
          kc.onTokenExpired = () => {
            void kc
              .updateToken(30)
              .then((refreshed) => {
                if (refreshed) syncAccessToken(kc);
              })
              .catch(() => {
                setAccessToken(null);
                notifySessionExpired();
              });
          };
        }
        return authenticated;
      })
      .catch((err) => {
        console.error("[keycloak] init failed", err);
        initPromise = null;
        return false;
      });
  }
  return initPromise;
}

export async function loginWithKeycloak(redirectUri?: string): Promise<void> {
  const kc = getKeycloak();
  await initKeycloak();
  await kc.login({
    // "/" and not "/dashboard": no such route exists, so a successful login
    // landed on a 404. The role is not known until the token comes back, so
    // the root route is the only honest destination — it redirects on by role.
    redirectUri: redirectUri ?? window.location.origin + "/",
  });
}

/** Whether the current access token proves an OTP/MFA authenticator ran. */
export function hasKeycloakMfaSession(): boolean {
  const parsed = keycloak?.tokenParsed as { amr?: string[] } | undefined;
  const methods = parsed?.amr ?? [];
  return methods.includes("otp") || methods.includes("mfa");
}

/**
 * Force a fresh Keycloak browser authentication before a sensitive action.
 *
 * The application never receives a TOTP code. Keycloak owns credential entry
 * and the backend accepts the resulting request only when the access token's
 * `amr` claim proves that OTP/MFA actually ran.
 */
export async function stepUpWithKeycloak(redirectUri?: string): Promise<void> {
  const kc = getKeycloak();
  const authenticated = await initKeycloak();
  if (!authenticated) {
    throw new Error("Sign in with Keycloak before requesting emergency access.");
  }
  await kc.login({
    redirectUri: redirectUri ?? window.location.href,
    prompt: "login",
    maxAge: 0,
  });
}

export async function logoutFromKeycloak(redirectUri?: string): Promise<void> {
  const kc = getKeycloak();
  setAccessToken(null);
  if (kc.authenticated) {
    await kc.logout({
      redirectUri: redirectUri ?? window.location.origin + "/login",
    });
  }
}

export function getKeycloakSessionUser(): SessionUser | null {
  if (!keycloak) return null;
  return sessionUserFromKeycloak(keycloak);
}

export function isKeycloakConfigured(): boolean {
  return Boolean(url && realm && clientId);
}
