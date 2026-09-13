"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
// Capital B: the file is components/ui/Button.tsx. The lowercase import
// resolved on a case-insensitive macOS filesystem and failed in Linux CI.
import { Button } from "@/components/ui/Button";
import { HealthDocBrand } from "@/components/common/HealthDocBrand";
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
    <div className="surface-card rounded-2xl border border-border/80 bg-card p-8 shadow-xl shadow-slate-900/5 transition-all">
      <div className="flex flex-col items-center text-center">
        <HealthDocBrand
          size={64}
          preload
          className="items-center"
          nameClassName="brand-gradient text-3xl font-bold tracking-tight"
          subtitle="Enterprise HMIS"
        />
        <h1 className="mt-5 text-2xl font-bold tracking-tight text-foreground">
          Clinical Portal Sign-In
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Authenticate using your authorized hospital credentials
        </p>
      </div>

      <div className="mt-6 space-y-4">
        {sessionExpired && (
          <div
            className="flex items-start gap-3 rounded-xl border border-amber-300/80 bg-amber-50/90 p-3.5 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
            role="status"
          >
            <span className="mt-0.5 text-amber-600 dark:text-amber-400">⚠️</span>
            <p className="leading-snug">
              <strong>Session Expired:</strong> Please sign in again to continue. Unsaved clinical drafts were not retained.
            </p>
          </div>
        )}

        {error && (
          <div
            className="flex items-start gap-3 rounded-xl border border-red-300/80 bg-red-50/90 p-3.5 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
            role="alert"
          >
            <span className="mt-0.5 text-red-600 dark:text-red-400">⛔</span>
            <p className="leading-snug">{error}</p>
          </div>
        )}

        {!keycloakConfigured && (
          <div
            className="flex items-start gap-3 rounded-xl border border-red-300/80 bg-red-50/90 p-3.5 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
            role="alert"
          >
            <span className="mt-0.5 text-red-600 dark:text-red-400">⚠️</span>
            <p className="leading-snug">
              Sign-in is not configured for this deployment. Contact your hospital system administrator.
            </p>
          </div>
        )}

        <Button
          type="button"
          onClick={() => void handleKeycloakLogin()}
          className="w-full h-12 text-base font-semibold shadow-md transition-all hover:shadow-lg active:scale-[0.99]"
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

        <div className="mt-6 border-t border-border/60 pt-5">
          <div className="flex flex-col items-center gap-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-4">
              <span className="inline-flex items-center gap-1">
                🔒 Keycloak sign-in
              </span>
              <span>•</span>
              <span className="inline-flex items-center gap-1">
                🛡️ Role-based access
              </span>
              <span>•</span>
              <span className="inline-flex items-center gap-1">
                ⚖️ Consent controls
              </span>
            </div>
            <p className="mt-1 text-center text-[11px] text-muted-foreground/80">
              Authorized personnel only. Use the workspace assigned to your role.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
