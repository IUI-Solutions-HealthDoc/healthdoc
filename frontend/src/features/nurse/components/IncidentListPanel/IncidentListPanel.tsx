"use client";

import { INCIDENT_STATUS_LABELS } from "@/features/nurse/constants";
import type { ClinicalIncident } from "@/features/nurse/types";
import { formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

type Props = {
  incidents: ClinicalIncident[];
  loading?: boolean;
  error?: string | null;
};

function shortId(value: string | null | undefined) {
  return value ? value.slice(0, 8) : "—";
}

export function IncidentListPanel({ incidents, loading, error }: Props) {
  const { t } = useLocale();
  if (loading) {
    return (
      <div className="surface-card p-5 text-sm text-muted-foreground">
        {t("nurse.loadingIncidents")}
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="rounded-md bg-danger-muted p-4 text-sm text-danger">
        {error}
      </p>
    );
  }

  if (incidents.length === 0) {
    return (
      <div className="surface-card p-5 text-sm text-muted-foreground">
        No clinical incidents filed for this patient yet.
      </div>
    );
  }

  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-border px-5 py-3">
        <h3 className="font-semibold">Filed incidents</h3>
        <p className="text-xs text-muted-foreground">
          Live register from `GET /nursing/incidents` (read-only for nurses; review is HOD/admin).
        </p>
      </div>
      <ul className="divide-y divide-border">
        {incidents.map((row) => (
          <li key={row.id} className="space-y-1 px-5 py-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="capitalize">{row.incident_type.replaceAll("_", " ")}</strong>
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
                {INCIDENT_STATUS_LABELS[row.status] ?? row.status}
              </span>
            </div>
            <p className="text-muted-foreground">
              {row.severity.replaceAll("_", " ")} · {formatDateTime(row.occurred_at)}
            </p>
            <p>{row.description}</p>
            <p className="text-xs text-muted-foreground">
              Action: {row.immediate_action} · Reporter {shortId(row.reported_by)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
