"use client";

/**
 * Appointment requests patients sent from the portal. Reception books each
 * with a time (and optionally a different day or a doctor) through the same
 * checks as a desk booking, or declines it with a reason the patient reads.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface AppointmentRequest {
  id: string;
  patient_name: string | null;
  patient_uhid: string | null;
  department_name: string | null;
  preferred_date: string;
  session: "morning" | "afternoon";
  is_teleconsult: boolean;
  reason: string | null;
  status: string;
  created_at: string;
}

function listRequests(): Promise<AppointmentRequest[]> {
  return api<AppointmentRequest[]>("/appointments/requests?status=requested");
}

function confirmRequest(id: string, body: { start_time: string; appointment_date: string | null }, key: string) {
  return api(`/appointments/requests/${id}/confirm`, { method: "POST", idempotencyKey: key, body: JSON.stringify(body) });
}

function declineRequest(id: string, reason: string, key: string) {
  return api(`/appointments/requests/${id}/decline`, { method: "POST", idempotencyKey: key, body: JSON.stringify({ reason }) });
}

export function OnlineAppointmentRequests({ onBooked }: { onBooked: () => void }) {
  const { t } = useLocale();
  const [items, setItems] = useState<AppointmentRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listRequests());
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("receptionist.requests.errLoad"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <p className="mt-4 text-sm text-danger" role="alert">{error}</p>;
  if (!items || items.length === 0) return null;

  return (
    <section className="mt-6 rounded-lg border border-amber-200 bg-amber-50/40 p-4 dark:border-amber-900 dark:bg-amber-950/20">
      <h2 className="text-sm font-semibold">{t("receptionist.requests.title", { count: items.length })}</h2>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <RequestRow key={item.id} item={item} onDone={() => { void load(); onBooked(); }} />
        ))}
      </ul>
    </section>
  );
}

function RequestRow({ item, onDone }: { item: AppointmentRequest; onDone: () => void }) {
  const { t } = useLocale();
  const [time, setTime] = useState("");
  const [day, setDay] = useState(item.preferred_date);
  const [reason, setReason] = useState("");
  const [declining, setDeclining] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setKey(newIdempotencyKey());
      onDone();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("receptionist.requests.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-md border border-border bg-white p-3 text-sm dark:bg-slate-900">
      <p className="font-medium">
        {item.patient_name ?? "—"} <span className="text-xs text-muted-foreground">{item.patient_uhid}</span>
      </p>
      <p className="text-xs text-muted-foreground">
        {[item.department_name, item.preferred_date,
          t(item.session === "morning" ? "patientPortal.appt.morning" : "patientPortal.appt.afternoon"),
          item.is_teleconsult ? t("patientPortal.appt.teleconsultShort") : null].filter(Boolean).join(" · ")}
      </p>
      {item.reason ? <p className="mt-1 text-xs">{item.reason}</p> : null}
      {declining ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} placeholder={t("receptionist.requests.declineReason")}
            className="min-w-64 flex-1 rounded-md border border-border px-2 py-1 text-xs" />
          <button type="button" disabled={busy || !reason.trim()} onClick={() => void act(() => declineRequest(item.id, reason.trim(), key))}
            className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-700 disabled:opacity-50">
            {t("receptionist.requests.decline")}
          </button>
          <button type="button" onClick={() => setDeclining(false)} className="text-xs underline">{t("common.cancel")}</button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="rounded-md border border-border px-2 py-1 text-xs" />
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="rounded-md border border-border px-2 py-1 text-xs" />
          <button type="button" disabled={busy || !/^\d{2}:\d{2}$/.test(time)}
            onClick={() => void act(() => confirmRequest(item.id, { start_time: time, appointment_date: day && day !== item.preferred_date ? day : null }, key))}
            className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
            {t("receptionist.requests.book")}
          </button>
          <button type="button" onClick={() => setDeclining(true)} className="text-xs underline">{t("receptionist.requests.decline")}</button>
        </div>
      )}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p> : null}
    </li>
  );
}
