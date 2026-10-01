"use client";

import { HfrFacilityRegistry } from "@/features/admin/HfrFacilityRegistry";
import { HprLoginPanel } from "@/features/admin/HprLoginPanel";
import { useLocale } from "@/lib/i18n";

export default function Page() {
  const { t } = useLocale();
  return (
    <div className="space-y-6 p-6">
      <h1 className="text-3xl font-semibold">{t("admin.hfr.title")}</h1>
      <HfrFacilityRegistry />
      <HprLoginPanel />
    </div>
  );
}
