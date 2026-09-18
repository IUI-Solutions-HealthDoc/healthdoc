"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
// Capital B: the file is components/ui/Button.tsx. The lowercase import
// resolved on a case-insensitive macOS filesystem and failed in Linux CI.
import { Button } from "@/components/ui/Button";
import { HealthDocBrand } from "@/components/common/HealthDocBrand";
import {
  isKeycloakConfigured,
  loginWithKeycloak,
  loginWithCredentials,
} from "@/lib/auth/keycloak";
import { getDefaultRouteForRole } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";

export function LoginScreen() {
  const searchParams = useSearchParams();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCredentials, setShowCredentials] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
      await loginWithKeycloak(`${window.location.origin}/`);
    } catch (err) {
      console.error(err);
      setError("Sign-in failed. Please try again, or contact your administrator.");
      setBusy(false);
    }
  }

  async function handleCredentialsLogin(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const result = await loginWithCredentials(username, password);
      if (!result.success || !result.user) {
        setError(result.error || "Sign-in failed. Please check your credentials.");
        setBusy(false);
        return;
      }
      const redirect = searchParams.get("redirect");
      const target =
        redirect && redirect.startsWith("/")
          ? redirect
          : result.landingPath || (result.user.role ? getDefaultRouteForRole(result.user.role) : "/");
      window.location.replace(target);
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
          subtitle="Enterprise HIMS"
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

        {showCredentials ? (
          <form onSubmit={(e) => void handleCredentialsLogin(e)} className="space-y-3.5 text-left">
            <div>
              <label htmlFor="username" className="block text-xs font-semibold text-foreground/90 mb-1">
                Username or email
              </label>
              <input
                id="username"
                name="username"
                type="text"
                required
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Username or email"
                disabled={busy}
                className="w-full h-11 px-3.5 rounded-xl border border-input bg-background/80 text-sm text-foreground transition-all focus:border-[#001f54] focus:ring-2 focus:ring-[#001f54]/20 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-xs font-semibold text-foreground/90 mb-1">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  disabled={busy}
                  className="w-full h-11 px-3.5 pr-11 rounded-xl border border-input bg-background/80 text-sm text-foreground transition-all focus:border-[#001f54] focus:ring-2 focus:ring-[#001f54]/20 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <Button
              id="kc-login"
              type="submit"
              className="w-full h-11 text-base font-semibold shadow-md transition-all hover:shadow-lg active:scale-[0.99] mt-2"
              disabled={busy || !username.trim() || !password}
            >
              {busy ? "Signing in…" : "Sign In"}
            </Button>

            <div className="text-center pt-1">
              <button
                type="button"
                onClick={() => {
                  setShowCredentials(false);
                  setError(null);
                }}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors hover:underline"
              >
                ← Back
              </button>
            </div>
          </form>
        ) : (
          <Button
            type="button"
            onClick={() => setShowCredentials(true)}
            className="w-full h-12 text-base font-semibold shadow-md transition-all hover:shadow-lg active:scale-[0.99]"
            disabled={busy || isLoading || !keycloakConfigured}
          >
            {isLoading
              ? "Preparing sign-in…"
              : busy
                ? "Redirecting…"
                : "Sign in with Keycloak"}
          </Button>
        )}

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
