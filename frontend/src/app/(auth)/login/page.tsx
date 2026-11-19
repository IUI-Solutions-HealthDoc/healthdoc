"use client";

import { Suspense } from "react";
import { LoginScreen } from "@/features/login/LoginScreen";
import { useLocale } from "@/lib/i18n";

export default function Page() {
  const { t } = useLocale();
  return (
    <Suspense
      fallback={
        <div className="surface-card p-8 text-sm text-muted-foreground">{t("auth.ui.loadingSignIn")}</div>
      }
    >
      <LoginScreen />
    </Suspense>
  );
}
