"use client";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";

export function ModuleEnabledChip({ enabled }: { enabled: boolean }) {
  const { t } = useLocale();
  return (
    <StatusChip
      status={enabled ? "active" : "cancelled"}
      label={enabled ? t("billing.tariff.stateEnabled") : t("admin.ui.disabled")}
    />
  );
}
