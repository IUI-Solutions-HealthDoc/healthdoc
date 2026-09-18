"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { getDefaultRouteForRole } from "@/lib/auth/routes";
import { useAuth } from "@/providers/auth-provider";

export default function HomePage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading) {
      if (isAuthenticated) {
        router.replace(getDefaultRouteForRole(user?.role ?? null));
      } else {
        router.replace("/login?redirect=%2F");
      }
    }
  }, [isAuthenticated, isLoading, router, user?.role]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-muted-foreground">
      Loading your workspace…
    </div>
  );
}
