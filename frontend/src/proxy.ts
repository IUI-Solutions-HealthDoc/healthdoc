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
 */

const KNOWN_ROLES = new Set<string>(Object.values(ROLES));

/**
 * Paths that need no session.
 *
 * `/` is here because the root page decides where to send you once the client
 * knows the real role. `/silent-check-sso.html` must never be redirected —
 * Keycloak loads it in a hidden iframe and a 307 would break silent SSO for
 * every already-authenticated user. The logo and manifest are public browser
 * assets; redirecting the logo makes Next's image optimiser receive the login
 * page instead of a PNG and render a broken image. The rest come from
 * `isPublicPath`, shared
 * with MainLayout so the edge and the client cannot disagree — notably
 * `/queue-display`, the waiting-room wall screen, which is unauthenticated by
 * design on both sides of the stack.
 */
function needsNoSession(pathname: string): boolean {
  return (
    pathname === "/" ||
    pathname === "/silent-check-sso.html" ||
    pathname === "/healthdoc-logo.png" ||
    pathname === "/manifest.webmanifest" ||
    isPublicPath(pathname)
  );
}

function roleHintFrom(request: NextRequest): Role | null {
  const raw = request.cookies.get(SESSION_ROLE_HINT_COOKIE)?.value;
  // Validated against the realm role list, not trusted: this came from a
  // cookie, and an unknown value must deny rather than be looked up.
  return raw && KNOWN_ROLES.has(raw) ? (raw as Role) : null;
}

/**
 * Content-Security-Policy, per request (WASA M3).
 *
 * WHY THIS MOVED OFF NGINX
 * ------------------------
 * nginx can only send one fixed policy, so the script-src had to carry
 * 'unsafe-inline' to admit Next's inline bootstrap — and 'unsafe-inline' is the
 * finding. A nonce has to be minted per response, which means it has to be
 * minted where the response is made. nginx no longer sets CSP for application
 * documents; it still owns the policies for /auth/ (Keycloak, not Next) and for
 * /silent-check-sso.html, which is deliberately different and is excluded below.
 *
 * WHY THE REQUEST HEADER, NOT JUST THE RESPONSE
 * ---------------------------------------------
 * Setting CSP only on the response would ship a policy that forbids the very
 * scripts Next is about to emit. Next reads the nonce back off the
 * Content-Security-Policy REQUEST header and stamps it onto its own script
 * tags; that read is the only reason the emitted HTML and the enforced policy
 * agree. Removing the request header white-screens the app.
 *
 * WHY 'unsafe-inline' SURVIVES ON style-src AND NOT script-src
 * -----------------------------------------------------------
 * Emotion/MUI inject styles at runtime with no nonce hook. An injected
 * stylesheet is not the finding and not the same risk class as injected script,
 * so it is stated here rather than quietly carried.
 */
const DEV_ONLY = process.env.NODE_ENV === "development";

function buildCsp(nonce: string): string {
  // 'unsafe-eval' is what `next dev --webpack` needs for react-refresh, and
  // dev's inline scripts are emitted before this nonce exists. The comparison
  // above is against "development" rather than for "production" on purpose: an
  // unset NODE_ENV must land on the STRICT policy, not the permissive one. A
  // loose default is how a control ends up switched off in the environment it
  // was written for.
  const scriptSrc = DEV_ONLY
    ? `'self' 'unsafe-inline' 'unsafe-eval'`
    : `'self' 'nonce-${nonce}'`;
  return [
    `default-src 'self'`,
    `script-src ${scriptSrc}`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data: blob:`,
    `font-src 'self'`,
    `connect-src 'self' wss:`,
    `frame-ancestors 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `object-src 'none'`,
  ].join("; ");
}

/**
 * nginx sets this file's policy at the location level and it must stay
 * different: Keycloak embeds it in a hidden iframe, so it needs
 * frame-ancestors 'self' where every application screen needs 'none'. Emitting
 * a second CSP header here would not relax that — two CSP headers are enforced
 * as their intersection — it would break silent SSO for every signed-in user.
 */
function ownsItsOwnCsp(pathname: string): boolean {
  return pathname === "/silent-check-sso.html";
}

/** Carries the nonce to the renderer and the policy to the browser. */
function withCsp(
  response: NextResponse,
  nonce: string,
  pathname: string,
): NextResponse {
  if (ownsItsOwnCsp(pathname)) return response;
  response.headers.set("Content-Security-Policy", buildCsp(nonce));
  return response;
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // One nonce per request, minted before any branch returns, because every
  // branch below has to carry the same policy — a redirect that omits CSP is a
  // hole the size of whichever screen the user was being sent to.
  const nonce = btoa(crypto.randomUUID());

  // Next reads the nonce back off this request header when it renders. Forward
  // it on the request as well as the response, or the emitted script tags carry
  // no nonce and the policy blocks them.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", buildCsp(nonce));
  const forward = () => NextResponse.next({ request: { headers: requestHeaders } });

  if (needsNoSession(pathname)) return withCsp(forward(), nonce, pathname);

  if (request.cookies.get(SESSION_PRESENCE_COOKIE)?.value !== "1") {
    const login = new URL("/login", request.url);
    login.searchParams.set("redirect", `${pathname}${search}`);
    return withCsp(NextResponse.redirect(login), nonce, pathname);
  }

  const role = roleHintFrom(request);

  // No usable hint: let it through to the client, where AuthProvider holds the
  // real token and MainLayout makes the final call. Redirecting on a missing
  // hint would bounce a legitimately signed-in user whose hint cookie expired
  // slightly ahead of their Keycloak session.
  if (!role) return withCsp(forward(), nonce, pathname);

  if (!canRoleAccessPath(role, pathname)) {
    return withCsp(
      NextResponse.redirect(new URL(getDefaultRouteForRole(role), request.url)),
      nonce,
      pathname,
    );
  }

  return withCsp(forward(), nonce, pathname);
}

export const config = {
  // Next owns every /_next/* resource (including the Next 16 HMR websocket).
  // Applying a session redirect there breaks hydration and leaves login inert.
  matcher: ["/((?!api|auth|_next|favicon.ico).*)"],
};
