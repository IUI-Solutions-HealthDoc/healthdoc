"use client";

/**
 * Appointment requests patients sent from the portal. Reception books each
 * with a time (and optionally a different day or a doctor) through the same
 * checks as a desk booking, or declines it with a reason the patient reads.
 */
import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { listBookableProviders } from "@/features/appointments/api";
import type { BookableProvider } from "@/features/appointments/types";
import { ApiError, api, newIdempotencyKey } from "@/lib/api";
import { apiErrorCode } from "@/lib/api-error-policy.mjs";
import { formatAge } from "@/lib/format-age";
import { useLocale } from "@/lib/i18n";

interface AppointmentRequest {
  id: string;
  patient_name: string | null;
  patient_uhid: string | null;
  patient_age_years?: number | null;
  patient_mobile_masked?: string | null;
  department_id: string;
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

interface ConfirmBody {
  start_time: string;
  appointment_date: string | null;
  doctor_user_id: string;
  outside_session_agreed?: boolean;
}

// Matches requests.SESSION_HOURS on the server; 12:00-12:59 is both, 13:00 is afternoon.
const SESSION_HOURS = { morning: ["00:00", "12:59"], afternoon: ["12:00", "23:59"] } as const;

function confirmRequest(id: string, body: ConfirmBody, key: string) {
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
  const [doctor, setDoctor] = useState("");
  const [doctors, setDoctors] = useState<BookableProvider[] | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [reason, setReason] = useState("");
  const [declining, setDeclining] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The doctors rostered that day in the requested department: the patient
  // is told whom they will see (QA 12 Oct 2026, booked with no doctor).
  useEffect(() => {
    let live = true;
    setDoctors(null);
    setDoctor("");
    listBookableProviders(day, item.department_id)
      .then((res) => { if (live) setDoctors(res.items ?? []); })
      .catch(() => { if (live) setDoctors([]); });
    return () => { live = false; };
  }, [day, item.department_id]);

  const [low, high] = SESSION_HOURS[item.session] ?? ["00:00", "23:59"];
  const outsideSession = /^\d{2}:\d{2}$/.test(time) && (time < low || time > high);

  async function act(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setKey(newIdempotencyKey());
      // The row leaves the list on success; say what happened before it goes.
      toast.success(done);
      onDone();
    } catch (reason) {
      if (reason instanceof ApiError && apiErrorCode(reason.payload) === "outside_requested_session") setAgreed(false);
      setError(reason instanceof ApiError ? reason.message : t("receptionist.requests.errSave"));
    } finally {
      setBusy(false);
    }
  }

  const sessionLabel = t(item.session === "morning" ? "patientPortal.appt.morning" : "patientPortal.appt.afternoon");

  return (
    <li className="rounded-md border border-border bg-white p-3 text-sm dark:bg-slate-900">
      <p className="font-medium">
        {item.patient_name ?? "—"}{" "}
        <span className="text-xs text-muted-foreground">
          {[item.patient_uhid ?? t("patient.identityUnavailable"), formatAge(item.patient_age_years), item.patient_mobile_masked]
            .filter(Boolean)
            .join(" · ")}
        </span>
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
          <button type="button" disabled={busy || !reason.trim()}
            onClick={() => void act(() => declineRequest(item.id, reason.trim(), key), `Declined. ${item.patient_name ?? "The patient"} will see the reason in the portal.`)}
            className="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-700 disabled:opacity-50">
            {t("receptionist.requests.decline")}
          </button>
          <button type="button" onClick={() => setDeclining(false)} className="text-xs underline">{t("common.cancel")}</button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input type="date" aria-label="Appointment date" value={day} onChange={(e) => setDay(e.target.value)} className="rounded-md border border-border px-2 py-1 text-xs" />
          <input type="time" aria-label="Appointment time" value={time} onChange={(e) => setTime(e.target.value)} className="rounded-md border border-border px-2 py-1 text-xs" />
          <select value={doctor} onChange={(e) => setDoctor(e.target.value)} aria-label="Doctor"
            className="rounded-md border border-border px-2 py-1 text-xs">
            <option value="">{doctors === null ? t("common.loading") : doctors.length ? "Choose doctor…" : "No doctor rostered that day"}</option>
            {(doctors ?? []).map((d) => <option key={d.staff_user_id} value={d.staff_user_id}>{d.staff_name}</option>)}
          </select>
          <button type="button" disabled={busy || !/^\d{2}:\d{2}$/.test(time) || !doctor || (outsideSession && !agreed)}
            onClick={() => void act(
              () => confirmRequest(item.id, {
                start_time: time,
                appointment_date: day && day !== item.preferred_date ? day : null,
                doctor_user_id: doctor,
                ...(outsideSession ? { outside_session_agreed: agreed } : {}),
              }, key),
              `Booked: ${item.patient_name ?? "patient"} on ${day} at ${time}. The patient sees it in the portal.`,
            )}
            className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
            {t("receptionist.requests.book")}
          </button>
          <button type="button" onClick={() => setDeclining(true)} className="text-xs underline">{t("receptionist.requests.decline")}</button>
          {outsideSession ? (
            <label className="flex w-full items-center gap-2 text-xs text-amber-800">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              {`The patient asked for the ${sessionLabel.toLowerCase()}. ${time} is outside it — the patient agreed to this time.`}
            </label>
          ) : null}
        </div>
      )}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p> : null}
    </li>
  );
}
