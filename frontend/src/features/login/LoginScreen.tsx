"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ROLES, type Role } from "@/config/roles";
// Capital B: the file is components/ui/Button.tsx. The lowercase import
// resolved on a case-insensitive macOS filesystem and failed in Linux CI.
import { Button } from "@/components/ui/Button";
import { FieldSelect } from "@/components/ui/mui-field";
import { type AuthUser, setAuthSession } from "@/lib/auth";
import { isDevAuthEnabled } from "@/lib/auth/mode";
import { isKeycloakConfigured, loginWithKeycloak } from "@/lib/auth/keycloak";
import { getDefaultRouteForRole } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";

/**
 * Dev-mode role picker.
 *
 * A deliberate subset of the realm's 13 roles: the workspaces that exist as
 * screens today. Not a `Record<Role, …>` — that would force a fake identity to
 * be invented for every realm role the moment one is added.
 *
 * This produces no bearer token. In dev mode the UI renders, and every API
 * call is unauthenticated and will be rejected.
 */
const DEV_ROLE_CHOICES: readonly { role: Role; label: string; name: string }[] = [
  { role: ROLES.RECEPTIONIST, label: "Receptionist", name: "Priya Nair" },
  { role: ROLES.DOCTOR, label: "Doctor", name: "Dr. Singh" },
  { role: ROLES.NURSE, label: "Nurse", name: "Anjali Rao" },
  { role: ROLES.PHARMACIST, label: "Pharmacist", name: "Ravi Kumar" },
  { role: ROLES.LAB_TECH, label: "Lab technician", name: "Lab Tech" },
  { role: ROLES.RADIOLOGY_TECH, label: "Radiology technician", name: "Radiology Tech" },
  { role: ROLES.EMERGENCY, label: "Emergency clinician", name: "Emergency Clinician" },
  { role: ROLES.SUPERVISOR, label: "Records supervisor", name: "Records Supervisor" },
  { role: ROLES.HOD, label: "Head of department", name: "Department Head" },
  { role: ROLES.AUDITOR, label: "Auditor", name: "Auditor" },
  { role: ROLES.ADMIN, label: "Admin", name: "Admin User" },
  { role: ROLES.PATIENT, label: "Patient", name: "Patient User" },
  { role: ROLES.SUPERADMIN, label: "Platform superadmin", name: "Platform Admin" },
];

function devUserFor(role: Role): AuthUser {
  const choice = DEV_ROLE_CHOICES.find((c) => c.role === role) ?? DEV_ROLE_CHOICES[0];
  return {
    id: `dev-${choice.role}`,
    name: choice.name,
    // .local, not a real-looking domain — dev fixtures should not be mistaken
    // for seeded staff accounts.
    email: `${choice.role}@hospital.local`,
    role: choice.role,
  };
}

export function LoginScreen() {
  const searchParams = useSearchParams();
  const { updateUser, user, isAuthenticated, isLoading } = useAuth();
  const [role, setRole] = useState<Role>(ROLES.RECEPTIONIST);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const devAuth = isDevAuthEnabled();
  const keycloakConfigured = isKeycloakConfigured();
  const sessionExpired = searchParams.get("reason") === "session-expired";

  useEffect(() => {
    if (!isLoading && isAuthenticated && user?.role) {
      window.location.replace(getDefaultRouteForRole(user.role));
    }
  }, [isAuthenticated, isLoading, user?.role]);

  function redirectAfterLogin(selectedRole: Role) {
    const redirectTo = searchParams.get("redirect");
    const destination =
      redirectTo &&
      redirectTo.startsWith("/") &&
      !redirectTo.startsWith("//") &&
      redirectTo !== "/"
        ? redirectTo
        : getDefaultRouteForRole(selectedRole);
    window.location.href = destination;
  }

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
      setError("Keycloak sign-in failed. Check KEYCLOAK is running and NEXT_PUBLIC_KEYCLOAK_URL.");
      setBusy(false);
    }
  }

  function handleDevLogin() {
    if (!devAuth) return;
    const user = devUserFor(role);
    // UX presence only — no bearer token; APIs stay unauthenticated in pure UI mode.
    setAuthSession(user);
    updateUser(user);
    redirectAfterLogin(role);
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
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
            Your session expired. Sign in again to continue; unsaved clinical work was not stored in the browser.
          </p>
        )}
        {!devAuth && (
          <>
            <Button
              type="button"
              onClick={() => void handleKeycloakLogin()}
              className="w-full"
              disabled={busy || isLoading || !keycloakConfigured}
            >
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
                Sign-in is not configured. Set NEXT_PUBLIC_KEYCLOAK_URL for this deployment.
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Identity is Keycloak OIDC. Middleware only gates navigation; API
              calls use a Bearer access token held in memory.
            </p>
          </>
        )}

        {devAuth && (
          <>
            <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Dev auth mode (`NEXT_PUBLIC_AUTH_MODE=dev`). UI scaffolding only —
              not production identity. Do not use against real patient data.
            </p>
            <FieldSelect
              label="Dev role"
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
              options={DEV_ROLE_CHOICES.map((c) => ({ value: c.role, label: c.label }))}
            />
            <Button type="button" onClick={handleDevLogin} className="w-full">
              Continue (dev UI only)
            </Button>
          </>
        )}
      </div>

      {/* No self-registration link. Staff accounts are created in Keycloak and
          requested through /admin/account-requests — a hospital does not let
          people enrol themselves into a clinical system. */}
    </div>
  );
}
