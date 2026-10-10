"use client";

/**
 * One facility's day: registrations, consultations, medicines, lab results,
 * surgeries, admissions and discharges, with the staff who did each. Patients
 * appear as day codes (P-XXXXXX), never names. Loaded only when the officer
 * asks, because every load is recorded in the facility's audit log.
 */
import { useState } from "react";

import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import { getMonitorActivity, type MonitorActivity } from "./api";

const KIND_LABEL = {
  registered: "monitor.kind.registered",
  consultation: "monitor.kind.consultation",
  medicine: "monitor.kind.medicine",
  lab_result: "monitor.kind.lab_result",
  surgery: "monitor.kind.surgery",
  admitted: "monitor.kind.admitted",
  discharged: "monitor.kind.discharged",
} as const;

function kindLabel(kind: string): (typeof KIND_LABEL)[keyof typeof KIND_LABEL] | null {
  return kind in KIND_LABEL ? KIND_LABEL[kind as keyof typeof KIND_LABEL] : null;
}

export function ActivityTrail({ facilityId }: { facilityId: string }) {
  const { t } = useLocale();
  const [day, setDay] = useState("");
  const [data, setData] = useState<MonitorActivity | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [patient, setPatient] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setData(await getMonitorActivity(facilityId, day || null));
      setPatient(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("monitor.errLoadActivity"));
    } finally {
      setBusy(false);
    }
  }

  const events = data ? (patient ? data.events.filter((event) => event.patient === patient) : data.events) : [];

  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex flex-wrap items-end gap-2">
        <h3 className="mr-2 text-sm font-medium">{t("monitor.activityTitle")}</h3>
        <label className="text-xs text-muted-foreground">
          {t("monitor.day")}{" "}
          <input type="date" value={day} onChange={(event) => setDay(event.target.value)} className="ml-1 rounded-md border border-border px-2 py-1 text-xs" />
        </label>
        <button type="button" disabled={busy} onClick={() => void load()} className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
          {data ? t("monitor.reloadActivity") : t("monitor.showActivity")}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">{t("monitor.activityAudited")}</p>
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="text-sm">
            {t("monitor.activitySummary", { day: data.day, patients: data.patients })}
            {data.first_patient && data.first_at ? ` · ${t("monitor.firstPatient")} ${data.first_patient} (${formatDateTime(data.first_at)})` : ""}
            {data.last_patient && data.last_at ? ` · ${t("monitor.lastPatient")} ${data.last_patient} (${formatDateTime(data.last_at)})` : ""}
          </p>
          <p className="text-xs text-muted-foreground">
            {Object.entries(data.counts)
              .map(([kind, count]) => {
                const label = kindLabel(kind);
                return `${label ? t(label) : kind}: ${count}`;
              })
              .join(" · ")}
          </p>
          {patient ? (
            <p className="text-xs">
              {t("monitor.journeyOf", { patient })}{" "}
              <button type="button" className="underline" onClick={() => setPatient(null)}>
                {t("monitor.showEveryone")}
              </button>
            </p>
          ) : null}
          {data.truncated ? <p className="text-xs text-amber-800">{t("monitor.activityTruncated")}</p> : null}
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("monitor.noActivity")}</p>
          ) : (
            <ol className="max-h-96 space-y-1 overflow-y-auto text-sm">
              {events.map((event, index) => {
                const label = kindLabel(event.kind);
                return (
                  <li key={`${event.at}-${index}`} className="grid grid-cols-[9rem_7rem_6rem_1fr] gap-2 border-t border-border py-1">
                    <span className="tabular-nums text-xs text-muted-foreground">{formatDateTime(event.at)}</span>
                    <span className="text-xs font-medium">{label ? t(label) : event.kind}</span>
                    <button type="button" className="text-left font-mono text-xs underline" onClick={() => setPatient(event.patient)}>
                      {event.patient}
                    </button>
                    <span>
                      {event.detail}
                      {event.staff ? <span className="text-xs text-muted-foreground"> · {event.staff}</span> : null}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          <p className="text-xs text-muted-foreground">{data.privacy_note}</p>
        </>
      ) : null}
    </div>
  );
}
