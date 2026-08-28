"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { canRoleAccessPath, getDefaultRouteForRole, isPublicPath } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const isPublic = isPublicPath(pathname);
  const allowed = pathname === "/" || canRoleAccessPath(user?.role ?? null, pathname);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    const sync = () => setOpen(desktop.matches);
    sync();
    desktop.addEventListener("change", sync);
    return () => desktop.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (isLoading) return;
    if (isPublic) {
      // Only /login bounces an authenticated user onward. The wall display is
      // a destination in its own right — a nurse who opens it to check the
      // board should see the board, not be redirected to their workspace.
      if (pathname === "/login" && isAuthenticated && user?.role) {
        router.replace(getDefaultRouteForRole(user.role));
      }
      return;
    }
    if (!isAuthenticated) {
      router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
      return;
    }
    if (user?.role && !allowed) {
      router.replace(getDefaultRouteForRole(user.role));
    }
  }, [allowed, isAuthenticated, isLoading, isPublic, pathname, router, user?.role]);

  if (isPublic) return <>{children}</>;

  if (isLoading || !isAuthenticated || (user?.role && !allowed)) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading your workspace…
      </div>
    );
  }

  if (!user?.role) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="surface-card max-w-lg p-8 text-center">
          <h1 className="text-xl font-semibold">No HealthDoc role assigned</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Your Keycloak account is valid, but it has no supported workspace role.
            Ask an administrator to assign one.
          </p>
          <button className="mt-6 underline" type="button" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <Navbar open={open} setOpen={setOpen} />

      <Sidebar open={open} setOpen={setOpen} />

      <main
        id="main-content"
        tabIndex={-1}
        className={`p-6 pt-20 transition-[margin] duration-300 ${open ? "md:ml-[260px]" : "md:ml-0"}`}
      >
        {children}
      </main>
    </div>
  );
}
