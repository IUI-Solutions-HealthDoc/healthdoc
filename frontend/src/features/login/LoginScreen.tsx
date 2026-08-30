"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
// Capital B: the file is components/ui/Button.tsx. The lowercase import
// resolved on a case-insensitive macOS filesystem and failed in Linux CI.
import { Button } from "@/components/ui/Button";
import { isKeycloakConfigured, loginWithKeycloak } from "@/lib/auth/keycloak";
import { getDefaultRouteForRole } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";

/**
 * Sign-in. Keycloak OIDC, and nothing else.
 *
 * This screen used to carry a second path: a `NEXT_PUBLIC_AUTH_MODE=dev` role
 * picker that wrote a fabricated user into sessionStorage, set the presence
 * cookie, and dropped the browser into any of eleven role workspaces without a
 * bearer token. It was removed before production rather than left inert.
 *
 * It was already dead — the variable is set in no .env, no compose file, no
 * Dockerfile and no CI workflow, so `isDevAuthEnabled()` returned false in
 * every environment that has ever existed. That is exactly why it was worth
 * deleting rather than trusting: a build-time flag that nothing sets is one
 * misconfigured deployment away from being a role picker on a login page, and
 * the code shipped in the production bundle either way.
 */
export function LoginScreen() {
  const searchParams = useSearchParams();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keycloakConfigured = isKeycloakConfigured();
  const sessionExpired = searchParams.get("reason") === "session-expired";

  useEffect(() => {
    if (!isLoading && isAuthenticated && user?.role) {
      window.location.replace(getDefaultRouteForRole(user.role));
    }
  }, [isAuthenticated, isLoading, user?.role]);

  async function handleKeycloakLogin() {
    setBusy(true);
    setError(null);
    try {
      // Always return through the public root route. AuthProvider first restores
      // the in-memory token and writes the non-secret presence cookie; only then
      // does the root page enter a protected role workspace.
      await loginWithKeycloak(`${window.location.origin}/`);
    } catch (err) {
      console.error(err);
      setError("Sign-in failed. Please try again, or contact your administrator.");
      setBusy(false);
    }
  }

  return (
    <div className="surface-card p-8">
      <p className="brand-gradient text-3xl font-bold tracking-tight">healthdoc</p>
      <h1 className="mt-4 text-2xl font-semibold text-foreground">Sign in</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Hospital Information Management System
      </p>

      <div className="mt-6 space-y-4">
        {sessionExpired && (
          <p
            className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
            role="status"
          >
            Your session expired. Sign in again to continue; unsaved clinical work
            was not stored in the browser.
          </p>
        )}

        <Button
          type="button"
          onClick={() => void handleKeycloakLogin()}
          className="w-full"
          disabled={busy || isLoading || !keycloakConfigured}
        >
          {/* Wording left exactly as it was. Three e2e scripts locate this
              button by its text, and relabelling it is a product decision
              rather than part of removing dev scaffolding. */}
          {isLoading
            ? "Preparing sign-in…"
            : busy
              ? "Redirecting…"
              : "Sign in with Keycloak"}
        </Button>

        {error && (
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}

        {!keycloakConfigured ? (
          <p className="text-sm text-red-600" role="alert">
            Sign-in is not configured for this deployment. Contact your administrator.
          </p>
        ) : null}
      </div>

      {/* No self-registration link. Staff accounts are created in Keycloak and
          requested through /admin/account-requests — a hospital does not let
          people enrol themselves into a clinical system. */}
    </div>
  );
}
