"use client";

/**
 * Ask the hospital for an appointment. The patient picks a department, a day
 * and morning or afternoon; reception books the exact time and doctor (or
 * says why not). HealthDoc records shift names, not clinic hours, so the
 * portal does not offer clock-time slots it would have to invent.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import {
  cancelPortalAppointment,
  listPortalAppointmentRequests,
  listPortalDepartments,
  requestPortalAppointment,
  withdrawPortalAppointmentRequest,
  type PortalAppointmentRequest,
  type PortalDepartment,
} from "../api";

const STATUS_STYLE: Record<PortalAppointmentRequest["status"], string> = {
  requested: "bg-amber-100 text-amber-900",
  confirmed: "bg-emerald-100 text-emerald-800",
  declined: "bg-red-100 text-red-800",
  withdrawn: "bg-slate-100 text-slate-600",
};

const STATUS_LABEL = {
  requested: "patientPortal.appt.status.requested",
  confirmed: "patientPortal.appt.status.confirmed",
  declined: "patientPortal.appt.status.declined",
  withdrawn: "patientPortal.appt.status.withdrawn",
} as const;

/** Today and the last day the server accepts (requests.MAX_DAYS_AHEAD = 60), on this device's calendar. */
function bookableRange(now = new Date()): { min: string; max: string } {
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const last = new Date(now);
  last.setDate(last.getDate() + 60);
  return { min: iso(now), max: iso(last) };
}

export function AppointmentRequestsTab() {
  const { localizeField, t } = useLocale();
  const [departments, setDepartments] = useState<PortalDepartment[] | null>(null);
  const [requests, setRequests] = useState<PortalAppointmentRequest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState({ department_id: "", preferred_date: "", session: "morning" as "morning" | "afternoon", is_teleconsult: false, reason: "" });
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Withdraw and cancel ask once more before acting: one click used to
  // withdraw with no confirmation and no undo (QA 12 Oct 2026).
  const [pending, setPending] = useState<{ id: string; action: "withdraw" | "cancel" } | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const range = bookableRange();
  const dateOutOfRange = Boolean(form.preferred_date) &&
    (form.preferred_date < range.min || form.preferred_date > range.max);

  const load = useCallback(async () => {
    try {
      const [deps, mine] = await Promise.all([listPortalDepartments(), listPortalAppointmentRequests()]);
      setDepartments(deps);
      setRequests(mine);
      setLoadError(null);
    } catch (reason) {
      setLoadError(reason instanceof ApiError ? reason.message : t("patientPortal.appt.errLoad"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !form.department_id || !form.preferred_date) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await requestPortalAppointment(
        { ...form, reason: form.reason.trim() || null },
        key,
      );
      setForm({ department_id: "", preferred_date: "", session: "morning", is_teleconsult: false, reason: "" });
      setKey(newIdempotencyKey());
      setNotice(t("patientPortal.appt.sent"));
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("patientPortal.appt.errSend"));
    } finally {
      setBusy(false);
    }
  }

  async function withdraw(id: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await withdrawPortalAppointmentRequest(id);
      setPending(null);
      setNotice(t("patientPortal.appt.withdrawn"));
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("patientPortal.appt.errSend"));
    } finally {
      setBusy(false);
    }
  }

  async function cancelAppointment(id: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await cancelPortalAppointment(id, cancelReason.trim() || null);
      setPending(null);
      setCancelReason("");
      setNotice(t("patientPortal.appt.cancelled"));
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("patientPortal.appt.errSend"));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return <p className="text-sm text-danger" role="alert">{loadError}</p>;
  }
  if (departments === null || requests === null) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  return (
    <div className="space-y-5">
      <form onSubmit={submit} noValidate className="surface-card grid gap-3 p-5 md:grid-cols-2">
        <h2 className="text-lg font-medium md:col-span-2">{t("patientPortal.appt.title")}</h2>
        <p className="text-sm text-muted-foreground md:col-span-2">{t("patientPortal.appt.intro")}</p>
        <label className="text-sm">
          <span className="text-muted-foreground">{t("patientPortal.appt.department")}</span>
          <select value={form.department_id} onChange={(e) => setForm((f) => ({ ...f, department_id: e.target.value }))}
            className="mt-1 w-full rounded-md border border-border px-2 py-2">
            <option value="">{t("patientPortal.appt.chooseDepartment")}</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{localizeField(d.name, d.name_hi)}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="text-muted-foreground">{t("patientPortal.appt.date")}</span>
          <input type="date" value={form.preferred_date} min={range.min} max={range.max}
            onChange={(e) => setForm((f) => ({ ...f, preferred_date: e.target.value }))}
            aria-invalid={dateOutOfRange}
            className={`mt-1 w-full rounded-md border px-2 py-2 ${dateOutOfRange ? "border-danger" : "border-border"}`} />
          {dateOutOfRange ? (
            <span className="text-xs text-danger">{t("patientPortal.appt.dateRange")}</span>
          ) : null}
        </label>
        <fieldset className="text-sm">
          <legend className="text-muted-foreground">{t("patientPortal.appt.session")}</legend>
          <div className="mt-1 flex gap-4">
            {(["morning", "afternoon"] as const).map((session) => (
              <label key={session} className="flex items-center gap-2">
                <input type="radio" name="session" checked={form.session === session}
                  onChange={() => setForm((f) => ({ ...f, session }))} />
                {t(session === "morning" ? "patientPortal.appt.morning" : "patientPortal.appt.afternoon")}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_teleconsult} onChange={(e) => setForm((f) => ({ ...f, is_teleconsult: e.target.checked }))} />
          {t("patientPortal.appt.teleconsult")}
        </label>
        <label className="text-sm md:col-span-2">
          <span className="text-muted-foreground">{t("patientPortal.appt.reason")}</span>
          <textarea value={form.reason} maxLength={500} rows={2} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            className="mt-1 w-full rounded-md border border-border px-2 py-2" />
        </label>
        {error ? <p className="text-sm text-danger md:col-span-2" role="alert">{error}</p> : null}
        {notice ? <p className="text-sm text-success md:col-span-2" role="status">{notice}</p> : null}
        <button type="submit" disabled={busy || !form.department_id || !form.preferred_date || dateOutOfRange}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50 md:col-span-2">
          {t("patientPortal.appt.send")}
        </button>
      </form>

      <section className="space-y-2">
        <h3 className="text-sm font-medium">{t("patientPortal.appt.mine")}</h3>
        {requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("patientPortal.appt.none")}</p>
        ) : (
          <ul className="space-y-2">
            {requests.map((r) => (
              <li key={r.id} className="surface-card p-4 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">
                    {r.department_name} · {r.preferred_date} · {t(r.session === "morning" ? "patientPortal.appt.morning" : "patientPortal.appt.afternoon")}
                    {r.is_teleconsult ? ` · ${t("patientPortal.appt.teleconsultShort")}` : ""}
                  </span>
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[r.status]}`}>{t(STATUS_LABEL[r.status])}</span>
                </div>
                {r.reason ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("patientPortal.appt.yourReason")} {r.reason}
                  </p>
                ) : null}
                {r.status === "confirmed" && r.appointment_status === "cancelled" ? (
                  <p className="mt-1 text-slate-600">
                    {t("patientPortal.appt.appointmentCancelled")}
                    {r.cancellation_reason ? ` — ${r.cancellation_reason}` : ""}
                  </p>
                ) : r.status === "confirmed" && r.appointment_date ? (
                  <p className="mt-1">
                    {t("patientPortal.appt.bookedFor", { date: r.appointment_date, time: r.start_time ?? "" })}
                    {r.doctor_name ? ` · ${r.doctor_name}` : ""}
                  </p>
                ) : null}
                {r.status === "confirmed" && r.teleconsult_status === "video_delivery_unavailable" ? (
                  <p className="mt-1 text-xs text-amber-800">{t("patientPortal.appt.noVideo")}</p>
                ) : null}
                {r.status === "declined" && r.decline_reason ? <p className="mt-1 text-red-800">{r.decline_reason}</p> : null}
                {pending?.id === r.id ? (
                  <div className="mt-2 space-y-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900" role="alert">
                    <p>{t(pending.action === "withdraw" ? "patientPortal.appt.confirmWithdraw" : "patientPortal.appt.confirmCancel")}</p>
                    {pending.action === "cancel" ? (
                      <input value={cancelReason} maxLength={300} onChange={(e) => setCancelReason(e.target.value)}
                        placeholder={t("patientPortal.appt.cancelReason")}
                        className="w-full rounded-md border border-border px-2 py-1" />
                    ) : null}
                    <div className="flex gap-3">
                      <button type="button" disabled={busy}
                        onClick={() => void (pending.action === "withdraw" ? withdraw(r.id) : cancelAppointment(r.id))}
                        className="rounded-md border border-red-300 bg-white px-3 py-1 font-medium text-red-700 disabled:opacity-50">
                        {t(pending.action === "withdraw" ? "patientPortal.appt.withdraw" : "patientPortal.appt.cancelAppointment")}
                      </button>
                      <button type="button" onClick={() => setPending(null)} className="underline">
                        {t("patientPortal.appt.keep")}
                      </button>
                    </div>
                  </div>
                ) : r.status === "requested" ? (
                  <button type="button" disabled={busy} onClick={() => setPending({ id: r.id, action: "withdraw" })} className="mt-2 text-xs underline disabled:opacity-50">
                    {t("patientPortal.appt.withdraw")}
                  </button>
                ) : r.status === "confirmed" && (r.appointment_status === "booked" || r.appointment_status === "confirmed") ? (
                  <button type="button" disabled={busy} onClick={() => setPending({ id: r.id, action: "cancel" })} className="mt-2 text-xs underline disabled:opacity-50">
                    {t("patientPortal.appt.cancelAppointment")}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
