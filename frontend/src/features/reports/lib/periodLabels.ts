import type { MessageKey } from "@/lib/i18n";

import type { KpiPeriod } from "../types";

export const KPI_PERIOD_MESSAGE_KEYS: Record<KpiPeriod, MessageKey> = {
  today: "reports.kpi.period.today",
  "7d": "reports.kpi.period.7d",
  "30d": "reports.kpi.period.30d",
  custom: "reports.kpi.period.custom",
};
