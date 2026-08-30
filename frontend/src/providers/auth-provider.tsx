"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Role } from "@/config/roles";
import {
  type AuthUser,
  clearAuthToken,
  setAuthSession,
  setSessionPresence,
} from "@/lib/auth";
import {
  getKeycloakSessionUser,
  initKeycloak,
  isKeycloakConfigured,
  logoutFromKeycloak,
  onKeycloakSessionExpired,
} from "@/lib/auth/keycloak";
import { setAccessToken } from "@/lib/api";
import { idleTimeoutMs, sessionExpiredPath } from "@/lib/session-policy.mjs";
import { toast } from "@/components/ui/toast";

type AuthContextValue = {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  updateUser: (user: AuthUser) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  updateUser: () => undefined,
  logout: async () => undefined,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const expireLocalSession = useCallback(() => {
    setUser(null);
    setAccessToken(null);
    clearAuthToken();
    const destination = sessionExpiredPath(window.location.pathname, window.location.search);
    window.location.replace(destination);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      try {
        if (isKeycloakConfigured()) {
          const ok = await initKeycloak();
          if (cancelled) return;
          if (ok) {
            const session = getKeycloakSessionUser();
            if (session) {
              const next: AuthUser = {
                id: session.id,
                name: session.name,
                email: session.email,
                role: session.role,
              };
              setUser(next);
              setSessionPresence(next.role ?? undefined);
              if (next.role === null) {
                // Authenticated, but holding no role this app has a workspace
                // for. Log it loudly: in practice it means the realm and
                // config/roles.ts have drifted, and the symptom otherwise is
                // "login works but every screen 403s".
                console.warn(
                  "[auth] signed in with no recognised role; token roles:",
                  session.roles,
                );
              }
              return;
            }
          }
          clearAuthToken();
          setUser(null);
        }
      } catch (err) {
        console.error("[auth] Keycloak hydrate failed", err);
        if (!cancelled) {
          clearAuthToken();
          setUser(null);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => onKeycloakSessionExpired(expireLocalSession), [expireLocalSession]);

  useEffect(() => {
    if (isLoading || !user) return;

    const timeout = idleTimeoutMs(process.env.NEXT_PUBLIC_SESSION_IDLE_MINUTES);
    const warningLead = Math.min(60_000, timeout / 4);
    let warningTimer = 0;
    let expiryTimer = 0;

    const expire = () => {
      const destination = sessionExpiredPath(window.location.pathname, window.location.search);
      setUser(null);
      setAccessToken(null);
      clearAuthToken();
      if (isKeycloakConfigured()) {
        void logoutFromKeycloak(`${window.location.origin}${destination}`).catch(() => {
          window.location.replace(destination);
        });
      } else {
        window.location.replace(destination);
      }
    };

    const reset = () => {
      window.clearTimeout(warningTimer);
      window.clearTimeout(expiryTimer);
      warningTimer = window.setTimeout(() => {
        toast.warning("Session expiring", "Save your work or continue activity to stay signed in.");
      }, timeout - warningLead);
      expiryTimer = window.setTimeout(expire, timeout);
    };

    const visibleActivity = () => {
      if (document.visibilityState === "visible") reset();
    };
    const events: (keyof WindowEventMap)[] = ["pointerdown", "keydown", "touchstart"];
    for (const event of events) window.addEventListener(event, reset, { passive: true });
    document.addEventListener("visibilitychange", visibleActivity);
    reset();

    return () => {
      window.clearTimeout(warningTimer);
      window.clearTimeout(expiryTimer);
      for (const event of events) window.removeEventListener(event, reset);
      document.removeEventListener("visibilitychange", visibleActivity);
    };
  }, [isLoading, user]);

  function updateUser(nextUser: AuthUser) {
    setUser(nextUser);
    setAuthSession(nextUser);
  }

  async function logout() {
    setUser(null);
    setAccessToken(null);
    clearAuthToken();
    if (isKeycloakConfigured()) {
      await logoutFromKeycloak();
    } else {
      // A full document load, not router.push — on sign-out the point is to
      // discard every in-memory value, and a client-side navigation keeps the
      // React tree (and anything a screen is still holding) alive. The lint
      // rule optimises for navigation speed, which is the wrong trade here.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: Boolean(user),
        isLoading,
        updateUser,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export function useUserRole(): Role | null {
  const { user } = useAuth();
  return user?.role ?? null;
}
