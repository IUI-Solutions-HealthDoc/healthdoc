import { NextResponse, type NextRequest } from "next/server";

import { ROLES, type Role } from "@/config/roles";
import { SESSION_PRESENCE_COOKIE, SESSION_ROLE_HINT_COOKIE } from "@/lib/auth";
import {
  canRoleAccessPath,
  getDefaultRouteForRole,
  isPublicPath,
} from "@/lib/auth/routes";

/**
 * Edge route guard (#149). Called `proxy` because Next 16 renamed
 * `middleware.ts` to `proxy.ts`.
 *
 * WHAT THIS IS NOT
 * ----------------
 * Not authorization, and it should never be described as such. The access
 * token lives in memory in the browser and is deliberately never written to a
 * cookie (src/lib/api.ts) — a clinician's token in a cookie is a stolen record
 * set. So all the edge can read is `hd_session`, a non-secret presence flag,
 * and `hd_role_hint`, a non-secret string the client wrote. Both are trivially
 * forgeable, and forging them yields a rendered page shell and nothing else:
 * every API request carries a Bearer token the backend verifies against
 * Keycloak, and `require_roles(...)` decides what data is returned.
 *
 * WHAT IT IS FOR
 * --------------
 * Not sending the wrong screen in the first place. The presence check was
 * already here; the role check is new — before it, any signed-in user could
 * request /admin/users and receive the admin shell, which then rendered until
 * MainLayout redirected after hydration. It also covers screens that forget to
 * mount inside MainLayout and would otherwise be guarded by nothing.
 *
 * WASA M3 — CSP
 * -------------
 * nginx no longer emits `script-src 'unsafe-inline'` for the app. This proxy
 * issues a per-request nonce and CSP so Next can stamp framework scripts
 * without unsafe-inline.
 */

const KNOWN_ROLES = new Set<string>(Object.values(ROLES));

/**
 * Paths that need no session.
 *
 * `/` is here because the root page decides where to send you once the client
 * knows the real role. `/silent-check-sso.html` must never be redirected —
 * Keycloak loads it in a hidden iframe and a 307 would break silent SSO for
 * every already-authenticated user. The rest come from `isPublicPath`, shared
 * with MainLayout so the edge and the client cannot disagree — notably
 * `/queue-display`, the waiting-room wall screen, which is unauthenticated by
 * design on both sides of the stack.
 */
function needsNoSession(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/silent-check-sso.html" ||
    isPublicPath(pathname)
  );
}

function roleHintFrom(request: NextRequest): Role | null {
  const raw = request.cookies.get(SESSION_ROLE_HINT_COOKIE)?.value;
  // Validated against the realm role list, not trusted: this came from a
  // cookie, and an unknown value must deny rather than be looked up.
  return raw && KNOWN_ROLES.has(raw) ? (raw as Role) : null;
}

function originFromEnv(url: string | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

function buildCsp(nonce: string): string {
  const connect = new Set<string>(["'self'", "wss:", "ws:"]);
  const frames = new Set<string>(["'self'"]);
  for (const origin of [
    originFromEnv(process.env.NEXT_PUBLIC_KEYCLOAK_URL),
    originFromEnv(process.env.NEXT_PUBLIC_API_BASE_URL),
  ]) {
    if (origin) connect.add(origin);
  }
  const keycloakOrigin = originFromEnv(process.env.NEXT_PUBLIC_KEYCLOAK_URL);
  if (keycloakOrigin) frames.add(keycloakOrigin);

  return [
    "default-src 'self'",
    `script-src 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    `connect-src ${[...connect].join(" ")}`,
    `frame-src ${[...frames].join(" ")}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join("; ");
}

function withCsp(request: NextRequest, response: NextResponse): NextResponse {
  const { pathname } = request.nextUrl;

  // Static silent-SSO helper has a fixed inline script; nginx (and this CSP)
  // allow it by sha256 hash. Regenerating the script body requires recomputing
  // the hash in infra/nginx/*/healthdoc.conf as well.
  if (pathname === "/silent-check-sso.html") {
    const ssoCsp =
      "default-src 'none'; script-src 'sha256-NuGEHWbQP7fFayUad46pwOQjhf59O6x6VUaef+Cctms='; frame-ancestors 'self'";
    response.headers.set("Content-Security-Policy", ssoCsp);
    return response;
  }

  const nonce = btoa(crypto.randomUUID());
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const isRedirect = response.status >= 300 && response.status < 400;
  const nextResponse = isRedirect
    ? response
    : NextResponse.next({
        request: { headers: requestHeaders },
      });

  nextResponse.headers.set("Content-Security-Policy", buildCsp(nonce));
  if (!isRedirect) {
    nextResponse.headers.set("x-nonce", nonce);
  }
  return nextResponse;
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (needsNoSession(pathname)) {
    return withCsp(request, NextResponse.next());
  }

  if (request.cookies.get(SESSION_PRESENCE_COOKIE)?.value !== "1") {
    const login = new URL("/login", request.url);
    login.searchParams.set("redirect", `${pathname}${search}`);
    return withCsp(request, NextResponse.redirect(login));
  }

  const role = roleHintFrom(request);

  // No usable hint: let it through to the client, where AuthProvider holds the
  // real token and MainLayout makes the final call. Redirecting on a missing
  // hint would bounce a legitimately signed-in user whose hint cookie expired
  // slightly ahead of their Keycloak session.
  if (!role) {
    return withCsp(request, NextResponse.next());
  }

  if (!canRoleAccessPath(role, pathname)) {
    return withCsp(
      request,
      NextResponse.redirect(new URL(getDefaultRouteForRole(role), request.url)),
    );
  }

  return withCsp(request, NextResponse.next());
}

export const config = {
  // Next owns every /_next/* resource (including the Next 16 HMR websocket).
  // Applying a session redirect there breaks hydration and leaves login inert.
  matcher: ["/((?!api|auth|_next|favicon.ico).*)"],
};
