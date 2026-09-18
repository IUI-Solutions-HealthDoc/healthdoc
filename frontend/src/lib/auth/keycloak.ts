import Keycloak from "keycloak-js";
import type { Role } from "@/config/roles";
import { ROLES } from "@/config/roles";
import { setAccessToken } from "@/lib/api";
import { recordLogin } from "@/lib/audit-session";
import { setSessionPresence } from "@/lib/auth";
import { getDefaultRouteForRole } from "@/lib/auth/routes";

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
/**
 * Which workspace someone lands in when their token carries several roles.
 * Lower number wins.
 *
 * Typed as a TOTAL Record<Role, number> on purpose. The previous array form
 * was a hand-maintained list of role names, and adding `billing` to the realm
 * without adding it here made mapKeycloakRolesToAppRole return null: the
 * account authenticated, held every backend permission, and was dropped on "/"
 * with no workspace and no sidebar. A missing entry is now a compile error.
 */
const ROLE_RANK: Record<Role, number> = {
  [ROLES.SUPERADMIN]: 0,
  [ROLES.ADMIN]: 1,
  [ROLES.HOD]: 2,
  [ROLES.SUPERVISOR]: 3,
  [ROLES.AUDITOR]: 4,
  [ROLES.DOCTOR]: 5,
  [ROLES.NURSE]: 6,
  [ROLES.PHARMACIST]: 7,
  [ROLES.LAB_TECH]: 8,
  [ROLES.RADIOLOGY_TECH]: 9,
  [ROLES.EMERGENCY]: 10,
  // Below the clinical roles: somebody who is a pharmacist AND on the billing
  // desk should still open in the pharmacy, where their patients are.
  [ROLES.BILLING]: 11,
  [ROLES.RECEPTIONIST]: 12,
  [ROLES.PATIENT]: 13,
};

const ROLE_PRECEDENCE: readonly Role[] = (Object.keys(ROLE_RANK) as Role[]).sort(
  (a, b) => ROLE_RANK[a] - ROLE_RANK[b],
);

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

function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join(""),
    );
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export type DirectLoginResult = {
  success: boolean;
  error?: string;
  user?: SessionUser;
  landingPath?: string;
};

export async function loginWithCredentials(
  username: string,
  pass: string,
): Promise<DirectLoginResult> {
  const tokenEndpoint = `${url}/realms/${realm}/protocol/openid-connect/token`;
  const body = new URLSearchParams({
    grant_type: "password",
    client_id: clientId,
    username: username.trim(),
    password: pass,
    scope: "openid profile email",
  });

  try {
    const res = await fetch(tokenEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!res.ok) {
      const errData = (await res.json().catch(() => ({}))) as {
        error?: string;
        error_description?: string;
      };
      const message =
        errData.error_description ||
        (errData.error === "invalid_grant"
          ? "Invalid username or password. Please try again."
          : "Authentication failed. Please check your credentials.");
      return { success: false, error: message };
    }

    const data = (await res.json()) as {
      access_token: string;
      refresh_token?: string;
      id_token?: string;
    };

    setAccessToken(data.access_token);

    if (typeof window !== "undefined" && data.refresh_token) {
      sessionStorage.setItem("hd_rt", data.refresh_token);
    }

    const kc = getKeycloak();
    kc.token = data.access_token;
    kc.refreshToken = data.refresh_token;
    kc.idToken = data.id_token;
    kc.authenticated = true;
    kc.tokenParsed = (parseJwtPayload(data.access_token) as typeof kc.tokenParsed) ?? undefined;
    if (data.id_token) {
      kc.idTokenParsed = (parseJwtPayload(data.id_token) as typeof kc.idTokenParsed) ?? undefined;
    }
    kc.subject = kc.tokenParsed?.sub;

    const session = sessionUserFromKeycloak(kc);
    if (!session) {
      return { success: false, error: "Failed to extract user profile from credentials." };
    }

    setSessionPresence(session.role ?? undefined);
    void recordLogin();

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

    return {
      success: true,
      user: session,
      landingPath: session.role ? getDefaultRouteForRole(session.role) : "/",
    };
  } catch (err) {
    console.error("[keycloak] Direct credentials login failed", err);
    return {
      success: false,
      error: "Unable to connect to the authentication server. Please try again.",
    };
  }
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
      .then(async (authenticated) => {
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
          return true;
        }

        // If silent SSO did not find an active iframe session, restore from tab session if available
        const storedRt = typeof window !== "undefined" ? sessionStorage.getItem("hd_rt") : null;
        if (storedRt) {
          try {
            const refreshEndpoint = `${url}/realms/${realm}/protocol/openid-connect/token`;
            const refreshBody = new URLSearchParams({
              grant_type: "refresh_token",
              client_id: clientId,
              refresh_token: storedRt,
            });
            const res = await fetch(refreshEndpoint, {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded" },
              body: refreshBody.toString(),
            });
            if (res.ok) {
              const refreshed = (await res.json()) as {
                access_token: string;
                refresh_token?: string;
                id_token?: string;
              };
              kc.token = refreshed.access_token;
              kc.refreshToken = refreshed.refresh_token;
              kc.idToken = refreshed.id_token;
              kc.authenticated = true;
              kc.tokenParsed = (parseJwtPayload(refreshed.access_token) as typeof kc.tokenParsed) ?? undefined;
              if (refreshed.id_token) {
                kc.idTokenParsed = (parseJwtPayload(refreshed.id_token) as typeof kc.idTokenParsed) ?? undefined;
              }
              kc.subject = kc.tokenParsed?.sub;
              syncAccessToken(kc);
              if (refreshed.refresh_token) {
                sessionStorage.setItem("hd_rt", refreshed.refresh_token);
              }
              kc.onTokenExpired = () => {
                void kc
                  .updateToken(30)
                  .then((ok) => {
                    if (ok) syncAccessToken(kc);
                  })
                  .catch(() => {
                    setAccessToken(null);
                    notifySessionExpired();
                  });
              };
              return true;
            } else {
              sessionStorage.removeItem("hd_rt");
            }
          } catch {
            sessionStorage.removeItem("hd_rt");
          }
        }

        return false;
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
  if (typeof window !== "undefined") {
    sessionStorage.removeItem("hd_rt");
  }
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
