"use client";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";

export function ActiveStatusChip({ active }: { active: boolean }) {
  const { t } = useLocale();
  return (
    <StatusChip
      status={active ? "active" : "cancelled"}
      label={active ? t("monitor.activeToday") : t("admin.users.inactive")}
    />
  );
}
