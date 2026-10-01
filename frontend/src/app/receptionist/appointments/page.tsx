"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Calendar as CalendarIcon,
  CheckCircle2,
  Clock,
  Filter,
  Plus,
  Search,
  User,
  Video,
  X,
} from "lucide-react";

import { listDepartments, type Department } from "@/features/admin/api/departments";
import {
  checkInAppointment,
  createAppointment,
  createAppointmentService,
  listAppointments,
  listAppointmentServices,
  listBookableProviders,
  updateAppointment,
} from "@/features/appointments/api";
import {
  appointmentActions,
  checkInOutcome,
  classifyPatientQuery,
  createRetryKeys,
} from "@/features/appointments/deskLogic";
import type {
  Appointment,
  AppointmentCreate,
  AppointmentService,
  AppointmentStatus,
  AppointmentUpdate,
  BookableProvider,
} from "@/features/appointments/types";
import { searchPatients } from "@/features/receptionist/api";
import type { PatientSearchResult } from "@/features/receptionist/types";
import { getUserFacingError } from "@/lib/api";
import { localToday } from "@/lib/dates";
import { PageHeading } from "@/components/common/PageHeading";
import { useLocale, type MessageKey } from "@/lib/i18n";

type Feedback = { tone: "success" | "warning"; text: string };

/** Providers rostered on a date; stale responses from an earlier date/department are dropped. */
function useBookableProviders(enabled: boolean, serviceDate: string, departmentId: string) {
  const [providers, setProviders] = useState<BookableProvider[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled || !serviceDate) {
      setProviders([]);
      setFailed(false);
      return;
    }
    let current = true;
    setLoading(true);
    setFailed(false);
    listBookableProviders(serviceDate, departmentId || undefined)
      .then((res) => {
        if (current) setProviders(res.items ?? []);
      })
      .catch(() => {
        if (!current) return;
        setProviders([]);
        setFailed(true);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [enabled, serviceDate, departmentId, attempt]);

  const uniqueProviders = useMemo(
    () => Array.from(new Map(providers.map((p) => [p.staff_user_id, p])).values()),
    [providers],
  );
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { providers: uniqueProviders, failed, loading, retry };
}

const FILTER_STATUSES: AppointmentStatus[] = [
  "booked",
  "confirmed",
  "checked_in",
  "completed",
  "cancelled",
  "no_show",
];

const STATUS_BADGE_STYLES: Record<AppointmentStatus, { bg: string; text: string }> = {
  booked: { bg: "bg-blue-50 dark:bg-blue-950/40", text: "text-blue-700 dark:text-blue-300" },
  confirmed: { bg: "bg-indigo-50 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-300" },
  checked_in: { bg: "bg-emerald-50 dark:bg-emerald-950/40", text: "text-emerald-700 dark:text-emerald-300" },
  completed: { bg: "bg-purple-50 dark:bg-purple-950/40", text: "text-purple-700 dark:text-purple-300" },
  cancelled: { bg: "bg-rose-50 dark:bg-rose-950/40", text: "text-rose-700 dark:text-rose-300" },
  no_show: { bg: "bg-amber-50 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300" },
  rescheduled: { bg: "bg-slate-50 dark:bg-slate-800", text: "text-slate-700 dark:text-slate-300" },
};

export default function AppointmentsPage() {
  const { t, localizeField } = useLocale();
  const appointmentStatusLabel = useCallback(
    (status: AppointmentStatus) => t(`appointment.status.${status}` as MessageKey),
    [t],
  );
  const todayStr = useMemo(() => localToday(), []);

  const [selectedDate, setSelectedDate] = useState(todayStr);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [services, setServices] = useState<AppointmentService[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [referenceState, setReferenceState] = useState<"loading" | "ready" | "failed">("loading");

  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  // Booking Modal State
  const [bookingModalOpen, setBookingModalOpen] = useState(false);
  const [serviceModalOpen, setServiceModalOpen] = useState(false);

  // Form states for booking
  const [patientSearchTerm, setPatientSearchTerm] = useState("");
  const [patientSearchResults, setPatientSearchResults] = useState<PatientSearchResult[]>([]);
  const [patientSearching, setPatientSearching] = useState(false);
  const [patientSearchMessage, setPatientSearchMessage] = useState<
    { tone: "error" | "info"; text: string } | null
  >(null);
  const [selectedPatient, setSelectedPatient] = useState<PatientSearchResult | null>(null);

  const [bookingDate, setBookingDate] = useState(todayStr);
  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [selectedDoctorId, setSelectedDoctorId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [apptTime, setApptTime] = useState("09:00");
  const [apptDuration, setApptDuration] = useState(15);
  const [isWalkIn, setIsWalkIn] = useState(false);
  const [isTeleconsult, setIsTeleconsult] = useState(false);
  const [notes, setNotes] = useState("");

  // Form states for new service catalogue entry
  const [newServiceName, setNewServiceName] = useState("");
  const [newServiceDuration, setNewServiceDuration] = useState(15);
  const [newServiceDeptId, setNewServiceDeptId] = useState("");
  const [newServiceDesc, setNewServiceDesc] = useState("");

  // Reschedule / cancel dialogs
  const [rescheduleTarget, setRescheduleTarget] = useState<Appointment | null>(null);
  const [rescheduleDate, setRescheduleDate] = useState(todayStr);
  const [rescheduleTime, setRescheduleTime] = useState("09:00");
  const [rescheduleDoctorId, setRescheduleDoctorId] = useState("");
  const [cancelTarget, setCancelTarget] = useState<Appointment | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  // One key per action while its payload is unchanged; a ref-held set blocks a
  // second click before React has re-rendered the disabled button.
  const retryKeysRef = useRef<ReturnType<typeof createRetryKeys> | null>(null);
  if (!retryKeysRef.current) retryKeysRef.current = createRetryKeys();
  const inFlight = useRef(new Set<string>());
  const [busyScopes, setBusyScopes] = useState<Set<string>>(() => new Set());
  const isBusy = (scope: string) => busyScopes.has(scope);

  async function runWrite<T>(scope: string, payload: unknown, send: (key: string) => Promise<T>): Promise<T | undefined> {
    if (inFlight.current.has(scope)) return undefined;
    inFlight.current.add(scope);
    setBusyScopes((prev) => new Set(prev).add(scope));
    const keys = retryKeysRef.current!;
    try {
      const result = await send(keys.keyFor(scope, payload));
      keys.settle(scope);
      return result;
    } finally {
      inFlight.current.delete(scope);
      setBusyScopes((prev) => {
        const next = new Set(prev);
        next.delete(scope);
        return next;
      });
    }
  }

  const booking = useBookableProviders(bookingModalOpen, bookingDate, selectedDeptId);
  const rescheduling = useBookableProviders(
    rescheduleTarget !== null,
    rescheduleDate,
    rescheduleTarget?.department_id ?? "",
  );

  // A provider picked for one date/department may not be rostered on another.
  useEffect(() => {
    if (booking.loading || !selectedDoctorId) return;
    if (!booking.providers.some((p) => p.staff_user_id === selectedDoctorId)) setSelectedDoctorId("");
  }, [booking.loading, booking.providers, selectedDoctorId]);

  const loadReferenceData = useCallback(async () => {
    setReferenceState("loading");
    try {
      const [deptRes, srvRes] = await Promise.all([listDepartments(), listAppointmentServices()]);
      setDepartments(deptRes.items ?? []);
      setServices(srvRes ?? []);
      setReferenceState("ready");
    } catch {
      setReferenceState("failed");
    }
  }, []);

  useEffect(() => {
    void loadReferenceData();
  }, [loadReferenceData]);

  // Fetch appointments whenever date changes
  const listRequest = useRef(0);
  const loadAppointments = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true);
    setListError(null);
    try {
      const res = await listAppointments({
        date_from: selectedDate,
        date_to: selectedDate,
        status: statusFilter === "all" ? undefined : statusFilter,
      });
      if (request === listRequest.current) setAppointments(res);
    } catch (err) {
      if (request !== listRequest.current) return;
      setAppointments([]);
      setListError(getUserFacingError(err, t("receptionist.errLoadAppointments")));
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [selectedDate, statusFilter, t]);

  useEffect(() => {
    void loadAppointments();
  }, [loadAppointments]);

  async function handleSearchPatient(e: React.SyntheticEvent) {
    e.preventDefault();
    const query = classifyPatientQuery(patientSearchTerm);
    setPatientSearchResults([]);
    if (query.kind === "invalid") {
      setPatientSearchMessage({ tone: "error", text: t("receptionist.errPatientQueryFormat") });
      return;
    }
    setPatientSearchMessage(null);
    setPatientSearching(true);
    try {
      const res = await searchPatients(query.criteria);
      const items = res.items ?? [];
      setPatientSearchResults(items);
      if (items.length === 0) {
        setPatientSearchMessage({ tone: "info", text: t("receptionist.noPatientMatch") });
      }
    } catch (err) {
      setPatientSearchMessage({
        tone: "error",
        text: getUserFacingError(err, t("receptionist.errPatientSearch")),
      });
    } finally {
      setPatientSearching(false);
    }
  }

  // Handle service selection change to sync duration
  function handleServiceChange(serviceId: string) {
    setSelectedServiceId(serviceId);
    const srv = services.find((s) => s.id === serviceId);
    if (srv) {
      setApptDuration(srv.duration_minutes);
      if (srv.department_id) {
        setSelectedDeptId(srv.department_id);
      }
    }
  }

  // Handle Appointment Booking Submit
  async function handleCreateAppointment(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedPatient) {
      setError(t("receptionist.errSelectPatient"));
      return;
    }
    if (!selectedDeptId) {
      setError(t("receptionist.errSelectDepartment"));
      return;
    }

    setError(null);

    const srv = services.find((s) => s.id === selectedServiceId);

    const payload: AppointmentCreate = {
      patient_id: selectedPatient.id,
      department_id: selectedDeptId,
      doctor_user_id: selectedDoctorId || null,
      service_id: selectedServiceId || null,
      service_name: srv ? srv.name : t("receptionist.defaultConsultation"),
      duration_minutes: apptDuration,
      appointment_date: bookingDate,
      start_time: apptTime,
      is_walk_in: isWalkIn,
      is_teleconsult: isTeleconsult,
      notes: notes.trim() || null,
    };

    try {
      const created = await runWrite("book", payload, (key) => createAppointment(payload, key));
      if (!created) return;
      setFeedback({ tone: "success", text: t("receptionist.feedbackBooked") });
      setBookingModalOpen(false);
      resetBookingForm();
      if (created.appointment_date !== selectedDate) setSelectedDate(created.appointment_date);
      else void loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errBookAppointment")));
    }
  }

  function openBookingModal() {
    setError(null);
    setBookingDate(selectedDate < todayStr ? todayStr : selectedDate);
    setBookingModalOpen(true);
  }

  function resetBookingForm() {
    setSelectedPatient(null);
    setPatientSearchTerm("");
    setPatientSearchResults([]);
    setPatientSearchMessage(null);
    setSelectedDeptId("");
    setSelectedDoctorId("");
    setSelectedServiceId("");
    setApptTime("09:00");
    setApptDuration(15);
    setIsWalkIn(false);
    setIsTeleconsult(false);
    setNotes("");
  }

  async function handleCheckIn(appointmentId: string) {
    setError(null);
    setFeedback(null);
    const payload = { priority: "normal" as const };
    try {
      const res = await runWrite(`check-in:${appointmentId}`, payload, (key) =>
        checkInAppointment(appointmentId, payload, key),
      );
      if (!res) return;
      const outcome = checkInOutcome(res);
      if (outcome.tone === "success") {
        setFeedback({
          tone: "success",
          text: t("receptionist.feedbackCheckIn", { visit: outcome.visit, token: outcome.token }),
        });
      } else {
        const reason = outcome.known
          ? t(`receptionist.tokenReason.${outcome.reason}` as MessageKey)
          : t("receptionist.tokenReasonOther", { code: outcome.reason });
        setFeedback({
          tone: "warning",
          text: t("receptionist.feedbackCheckInNoToken", { visit: outcome.visit, reason }),
        });
      }
      void loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCheckIn")));
    }
  }

  async function handleConfirm(appointmentId: string) {
    setError(null);
    const payload: AppointmentUpdate = { status: "confirmed" };
    try {
      const res = await runWrite(`update:${appointmentId}`, payload, (key) =>
        updateAppointment(appointmentId, payload, key),
      );
      if (!res) return;
      setFeedback({ tone: "success", text: t("receptionist.feedbackConfirmed") });
      void loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errConfirmAppointment")));
    }
  }

  function openCancelDialog(appt: Appointment) {
    setError(null);
    setCancelReason("");
    setCancelTarget(appt);
  }

  async function handleCancelSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!cancelTarget || !cancelReason.trim()) return;
    const appointmentId = cancelTarget.id;
    const payload: AppointmentUpdate = {
      status: "cancelled",
      cancellation_reason: cancelReason.trim(),
    };
    setError(null);
    try {
      const res = await runWrite(`update:${appointmentId}`, payload, (key) =>
        updateAppointment(appointmentId, payload, key),
      );
      if (!res) return;
      setCancelTarget(null);
      setFeedback({ tone: "success", text: t("receptionist.feedbackCancelled") });
      void loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCancelAppointment")));
    }
  }

  function openRescheduleDialog(appt: Appointment) {
    setError(null);
    setRescheduleDate(appt.appointment_date < todayStr ? todayStr : appt.appointment_date);
    setRescheduleTime(appt.start_time);
    setRescheduleDoctorId(appt.doctor_user_id ?? "");
    setRescheduleTarget(appt);
  }

  async function handleRescheduleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!rescheduleTarget) return;
    const appointmentId = rescheduleTarget.id;
    const payload: AppointmentUpdate = {
      appointment_date: rescheduleDate,
      start_time: rescheduleTime,
    };
    if ((rescheduleTarget.doctor_user_id ?? "") !== rescheduleDoctorId) {
      payload.doctor_user_id = rescheduleDoctorId || null;
    }
    setError(null);
    try {
      const res = await runWrite(`update:${appointmentId}`, payload, (key) =>
        updateAppointment(appointmentId, payload, key),
      );
      if (!res) return;
      setRescheduleTarget(null);
      setFeedback({ tone: "success", text: t("receptionist.feedbackRescheduled") });
      if (res.appointment_date !== selectedDate) setSelectedDate(res.appointment_date);
      else void loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errReschedule")));
    }
  }

  async function handleCreateService(e: React.FormEvent) {
    e.preventDefault();
    if (!newServiceName.trim()) return;

    const payload = {
      name: newServiceName.trim(),
      duration_minutes: newServiceDuration,
      department_id: newServiceDeptId || null,
      description: newServiceDesc.trim() || null,
    };
    try {
      const created = await runWrite("service", payload, (key) => createAppointmentService(payload, key));
      if (!created) return;
      setServices((prev) => [...prev, created]);
      setFeedback({ tone: "success", text: t("receptionist.feedbackServiceAdded", { name: created.name }) });
      setServiceModalOpen(false);
      setNewServiceName("");
      setNewServiceDuration(15);
      setNewServiceDeptId("");
      setNewServiceDesc("");
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCreateService")));
    }
  }

  const rescheduleProviderOptions = useMemo(() => {
    const options = rescheduling.providers.map((p) => ({ id: p.staff_user_id, name: p.staff_name }));
    const current = rescheduleTarget?.doctor_user_id;
    if (current && !options.some((o) => o.id === current)) {
      options.unshift({ id: current, name: rescheduleTarget?.doctor_name ?? current });
    }
    return options;
  }, [rescheduling.providers, rescheduleTarget]);

  const filteredAppointments = appointments.filter((appt) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (appt.patient_name && appt.patient_name.toLowerCase().includes(q)) ||
      (appt.patient_uhid && appt.patient_uhid.toLowerCase().includes(q)) ||
      (appt.service_name && appt.service_name.toLowerCase().includes(q)) ||
      (appt.doctor_name && appt.doctor_name.toLowerCase().includes(q))
    );
  });

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <PageHeading
          titleKey="receptionist.appointmentsTitle"
          subtitleKey="receptionist.appointmentsSubtitle"
          titleClassName="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setServiceModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            {t("receptionist.catalogueServices")}
          </button>
          <button
            type="button"
            onClick={openBookingModal}
            disabled={referenceState !== "ready"}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            {t("receptionist.bookAppointment")}
          </button>
        </div>
      </div>

      {referenceState === "failed" && (
        <div role="alert" className="mt-4 flex items-center justify-between rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-rose-600 dark:text-rose-400" />
            <span>{t("receptionist.errLoadReference")}</span>
          </div>
          <button
            type="button"
            onClick={() => void loadReferenceData()}
            className="rounded-md border border-rose-300 px-3 py-1 text-xs font-medium text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:text-rose-300"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {/* Notifications */}
      {feedback && (
        <div
          role="status"
          className={`mt-4 flex items-center justify-between rounded-lg border p-4 text-sm ${
            feedback.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
              : "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          }`}
        >
          <div className="flex items-center gap-2">
            {feedback.tone === "success" ? (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            )}
            <span>{feedback.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            aria-label={t("common.close")}
            className="opacity-70 hover:opacity-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-rose-600 dark:text-rose-400" />
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => setError(null)} className="text-rose-700 hover:text-rose-900">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Filter and Date Bar */}
      <div className="mt-6 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <CalendarIcon className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{t("common.date")}:</span>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          <button
            type="button"
            onClick={() => setSelectedDate(todayStr)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              selectedDate === todayStr
                ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400"
            }`}
          >
            {t("common.today")}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-slate-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              <option value="all">{t("receptionist.allStatuses")}</option>
              {FILTER_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {appointmentStatusLabel(status)}
                </option>
              ))}
            </select>
          </div>

          <div className="relative">
            <Search className="absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder={t("receptionist.searchPatientDoctor")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-48 rounded-md border border-slate-300 pl-8 pr-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 sm:w-64"
            />
          </div>
        </div>
      </div>

      {/* Appointments List */}
      <div className="mt-6">
        {loading ? (
          <div className="flex h-48 items-center justify-center rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <span className="text-sm text-slate-500">{t("receptionist.loadingAppointments")}</span>
          </div>
        ) : listError ? (
          <div role="alert" className="flex flex-col items-center justify-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-12 text-center text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
            <AlertCircle className="h-8 w-8 text-rose-500" />
            <span>{listError}</span>
            <button
              type="button"
              onClick={() => void loadAppointments()}
              className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:text-rose-300"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : filteredAppointments.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center dark:border-slate-800 dark:bg-slate-900">
            <CalendarIcon className="h-10 w-10 text-slate-400" />
            <h3 className="mt-3 text-base font-semibold text-slate-900 dark:text-slate-100">
              {t("receptionist.noAppointments")}
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("receptionist.noAppointmentsForDate", { date: selectedDate })}
            </p>
            <button
              type="button"
              onClick={openBookingModal}
              disabled={referenceState !== "ready"}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              {t("receptionist.bookAppointment")}
            </button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredAppointments.map((appt) => {
              const badgeStyle = STATUS_BADGE_STYLES[appt.status] ?? {
                bg: "bg-slate-100",
                text: "text-slate-700",
              };
              const catalogueService = services.find((s) => s.id === appt.service_id);
              const serviceDisplay = catalogueService
                ? localizeField(catalogueService.name, catalogueService.name_hi)
                : appt.service_name;
              const actions = appointmentActions(appt.status);
              const checkInBusy = isBusy(`check-in:${appt.id}`);
              const updateBusy = isBusy(`update:${appt.id}`);

              return (
                <div
                  key={appt.id}
                  className="relative flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-200 hover:shadow-md dark:border-slate-800 dark:bg-slate-900"
                >
                  <div>
                    {/* Time and Badges */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                        <Clock className="h-4 w-4 text-indigo-500" />
                        <span>{appt.start_time} - {appt.end_time}</span>
                        <span className="text-xs text-slate-400">({appt.duration_minutes}m)</span>
                      </div>
                      <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeStyle.bg} ${badgeStyle.text}`}>
                        {appointmentStatusLabel(appt.status)}
                      </span>
                    </div>

                    {/* Patient Info */}
                    <div className="mt-4">
                      <div className="flex items-center gap-2">
                        <User className="h-4 w-4 text-slate-400" />
                        <h4 className="font-semibold text-slate-900 dark:text-slate-100">
                          {appt.patient_name || t("receptionist.unknownPatient")}
                        </h4>
                      </div>
                      <p className="ml-6 text-xs text-slate-500 dark:text-slate-400">
                        {t("receptionist.labelUhid")}: {appt.patient_uhid || "N/A"}
                      </p>
                    </div>

                    {/* Department, Doctor, Service */}
                    <div className="mt-3 space-y-1 text-xs text-slate-600 dark:text-slate-400">
                      <div>
                        <span className="font-medium text-slate-700 dark:text-slate-300">{t("receptionist.department")}: </span>
                        {localizeField(appt.department_name || t("receptionist.generalClinic"), appt.department_name_hi)}
                      </div>
                      <div>
                        <span className="font-medium text-slate-700 dark:text-slate-300">{t("receptionist.labelProvider")}: </span>
                        {appt.doctor_name || t("receptionist.anyAvailableProvider")}
                      </div>
                      <div>
                        <span className="font-medium text-slate-700 dark:text-slate-300">{t("receptionist.labelService")}: </span>
                        {serviceDisplay}
                      </div>
                    </div>

                    {/* Walk-in & Teleconsult flags */}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {appt.is_walk_in && (
                        <span className="inline-flex items-center rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                          {t("receptionist.walkInBadge")}
                        </span>
                      )}
                      {appt.is_teleconsult && (
                        <span className="inline-flex items-center gap-1 rounded bg-sky-50 px-2 py-0.5 text-xs text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
                          <Video className="h-3 w-3" />
                          {t("receptionist.teleconsultUnavailableBadge")}
                        </span>
                      )}
                    </div>

                    {appt.notes && (
                      <p className="mt-2 text-xs italic text-slate-500">
                        &ldquo;{appt.notes}&rdquo;
                      </p>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="mt-5 border-t border-slate-100 pt-3 dark:border-slate-800">
                    {actions.checkIn && (
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void handleCheckIn(appt.id)}
                          disabled={checkInBusy || updateBusy || appt.appointment_date !== todayStr}
                          title={appt.appointment_date !== todayStr ? t("receptionist.checkInTodayOnly") : undefined}
                          className="flex-1 rounded-md bg-emerald-600 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {checkInBusy ? t("common.loading") : t("receptionist.checkIn")}
                        </button>
                        {actions.confirm && (
                          <button
                            type="button"
                            onClick={() => void handleConfirm(appt.id)}
                            disabled={checkInBusy || updateBusy}
                            className="rounded-md border border-indigo-300 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:text-indigo-300"
                          >
                            {t("receptionist.confirmAppointment")}
                          </button>
                        )}
                        {actions.reschedule && (
                          <button
                            type="button"
                            onClick={() => openRescheduleDialog(appt)}
                            disabled={checkInBusy || updateBusy}
                            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-400"
                          >
                            {t("receptionist.reschedule")}
                          </button>
                        )}
                        {actions.cancel && (
                          <button
                            type="button"
                            onClick={() => openCancelDialog(appt)}
                            disabled={checkInBusy || updateBusy}
                            className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-400"
                          >
                            {t("common.cancel")}
                          </button>
                        )}
                      </div>
                    )}

                    {appt.status === "checked_in" && (
                      <div className="flex items-center justify-between text-xs text-emerald-700 dark:text-emerald-400">
                        <span>{t("receptionist.checkedInAtArrival")}</span>
                        <span className="font-semibold">{t("receptionist.readyForConsultation")}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Booking Modal */}
      {bookingModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
            <button
              type="button"
              onClick={() => {
                setBookingModalOpen(false);
                resetBookingForm();
              }}
              className="absolute right-4 top-4 text-slate-400 hover:text-slate-600"
            >
              <X className="h-5 w-5" />
            </button>

            <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">
              {t("receptionist.bookAppointment")}
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {t("receptionist.bookingModalHint")}
            </p>

            <form onSubmit={handleCreateAppointment} className="mt-5 space-y-4">
              {/* Patient Lookup */}
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.findPatientUhidMobile")} *
                </label>
                {!selectedPatient ? (
                  <div className="mt-1 space-y-2">
                    <div className="flex gap-2">
                      <input
                        type="text"
                        placeholder={t("receptionist.patientSearchPlaceholder")}
                        value={patientSearchTerm}
                        onChange={(e) => {
                          setPatientSearchTerm(e.target.value);
                          setPatientSearchMessage(null);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void handleSearchPatient(e);
                        }}
                        aria-invalid={patientSearchMessage?.tone === "error"}
                        className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={(e) => void handleSearchPatient(e)}
                        disabled={patientSearching || !patientSearchTerm.trim()}
                        className="rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-700"
                      >
                        {patientSearching ? t("common.searching") : t("common.search")}
                      </button>
                    </div>

                    {patientSearchMessage && (
                      <p
                        role={patientSearchMessage.tone === "error" ? "alert" : "status"}
                        className={`text-xs ${
                          patientSearchMessage.tone === "error"
                            ? "text-rose-700 dark:text-rose-400"
                            : "text-slate-600 dark:text-slate-400"
                        }`}
                      >
                        {patientSearchMessage.text}
                      </p>
                    )}

                    {patientSearchResults.length > 0 && (
                      <div className="max-h-36 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-800/60">
                        {patientSearchResults.map((p) => (
                          <button
                            type="button"
                            key={p.id}
                            onClick={() => {
                              setSelectedPatient(p);
                              setPatientSearchResults([]);
                              setPatientSearchMessage(null);
                            }}
                            className="block w-full cursor-pointer rounded p-2 text-left text-xs hover:bg-indigo-50 dark:hover:bg-indigo-950/40"
                          >
                            <div className="font-semibold text-slate-900 dark:text-slate-100">
                              {p.full_name}
                            </div>
                            <div className="text-slate-500">
                              {t("receptionist.labelUhid")}: {p.uhid ?? p.thid ?? "N/A"} | {t("receptionist.labelPhone")}: {p.mobile_masked || "N/A"}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="mt-1 flex items-center justify-between rounded-lg border border-indigo-200 bg-indigo-50 p-3 dark:border-indigo-900 dark:bg-indigo-950/40">
                    <div>
                      <div className="font-medium text-indigo-900 dark:text-indigo-200">
                        {selectedPatient.full_name}
                      </div>
                      <div className="text-xs text-indigo-700 dark:text-indigo-400">
                        {t("receptionist.labelUhid")}: {selectedPatient.uhid ?? selectedPatient.thid ?? "N/A"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedPatient(null)}
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                    >
                      {t("common.changePatient")}
                    </button>
                  </div>
                )}
              </div>

              {/* Service Selection */}
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.serviceCatalogue")}
                </label>
                <select
                  value={selectedServiceId}
                  onChange={(e) => handleServiceChange(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.standardConsultation15")}</option>
                  {services.map((s) => (
                    <option key={s.id} value={s.id}>
                      {t("receptionist.serviceDurationMin", {
                        name: localizeField(s.name, s.name_hi),
                        minutes: s.duration_minutes,
                      })}
                    </option>
                  ))}
                </select>
              </div>

              {/* Department Selection */}
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.department")} *
                </label>
                <select
                  value={selectedDeptId}
                  onChange={(e) => setSelectedDeptId(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.selectDepartment")}</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {localizeField(d.name, d.name_hi)}
                    </option>
                  ))}
                </select>
              </div>

              {/* Doctor Selection (Optional per HD-11) */}
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.doctorProviderOptional")}
                </label>
                <select
                  value={selectedDoctorId}
                  onChange={(e) => setSelectedDoctorId(e.target.value)}
                  disabled={booking.loading}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.anyAvailableProvider")}</option>
                  {booking.providers.map((doc) => (
                    <option key={doc.staff_user_id} value={doc.staff_user_id}>
                      {doc.staff_name}
                    </option>
                  ))}
                </select>
                {booking.failed ? (
                  <p role="alert" className="mt-1 flex items-center gap-2 text-xs text-rose-700 dark:text-rose-400">
                    {t("receptionist.errLoadProviders")}
                    <button type="button" onClick={booking.retry} className="font-medium underline">
                      {t("common.retry")}
                    </button>
                  </p>
                ) : (
                  !booking.loading &&
                  booking.providers.length === 0 && (
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {t("receptionist.noRosteredProviders")}
                    </p>
                  )
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.appointmentDate")}
                </label>
                <input
                  type="date"
                  value={bookingDate}
                  min={todayStr}
                  onChange={(e) => setBookingDate(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              {/* Time & Duration */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.startTime")}
                  </label>
                  <input
                    type="time"
                    value={apptTime}
                    onChange={(e) => setApptTime(e.target.value)}
                    required
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.durationMinutes")}
                  </label>
                  <input
                    type="number"
                    min={5}
                    max={240}
                    value={apptDuration}
                    onChange={(e) => setApptDuration(Number(e.target.value))}
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  />
                </div>
              </div>

              {/* Walk-in and Teleconsult Toggles */}
              <div className="space-y-2 pt-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={isWalkIn}
                    onChange={(e) => setIsWalkIn(e.target.checked)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.walkInBooking")}
                  </span>
                </label>

                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={isTeleconsult}
                    onChange={(e) => setIsTeleconsult(e.target.checked)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.teleconsultBooking")}
                  </span>
                </label>
                {isTeleconsult && (
                  <p className="rounded bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                    {t("receptionist.teleconsultNotice")}
                  </p>
                )}
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.clinicalNotes")}
                </label>
                <textarea
                  rows={2}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t("receptionist.notesPlaceholder")}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              {error && (
                <p role="alert" className="rounded-md bg-rose-50 p-2 text-xs text-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
                  {error}
                </p>
              )}

              <div className="mt-6 flex justify-end gap-3 pt-3">
                <button
                  type="button"
                  onClick={() => {
                    setBookingModalOpen(false);
                    resetBookingForm();
                  }}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isBusy("book") || !selectedPatient || !selectedDeptId || !bookingDate || bookingDate < todayStr}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {isBusy("book") ? t("common.loading") : t("receptionist.confirmBooking")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Catalogue Modal */}
      {serviceModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="relative max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
            <button
              type="button"
              onClick={() => setServiceModalOpen(false)}
              className="absolute right-4 top-4 text-slate-400 hover:text-slate-600"
            >
              <X className="h-5 w-5" />
            </button>

            <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">
              {t("receptionist.serviceCatalogueTitle")}
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {t("receptionist.serviceCatalogueHint")}
            </p>

            <div className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200 p-2 dark:divide-slate-800 dark:border-slate-800">
              {services.map((s) => (
                <div key={s.id} className="py-2 text-xs">
                  <div className="font-semibold text-slate-900 dark:text-slate-100">{localizeField(s.name, s.name_hi)}</div>
                  <div className="text-slate-500">{s.duration_minutes} minutes {s.description && `— ${s.description}`}</div>
                </div>
              ))}
            </div>

            <form onSubmit={handleCreateService} className="mt-5 space-y-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                {t("receptionist.addNewService")}
              </h3>
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.serviceName")}
                </label>
                <input
                  type="text"
                  required
                  placeholder={t("receptionist.serviceNamePlaceholder")}
                  value={newServiceName}
                  onChange={(e) => setNewServiceName(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.durationMinutes")} *
                </label>
                <input
                  type="number"
                  min={5}
                  max={240}
                  value={newServiceDuration}
                  onChange={(e) => setNewServiceDuration(Number(e.target.value))}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.departmentOptional")}
                </label>
                <select
                  value={newServiceDeptId}
                  onChange={(e) => setNewServiceDeptId(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.anyDepartment")}</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {localizeField(d.name, d.name_hi)}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.description")}
                </label>
                <input
                  type="text"
                  placeholder={t("receptionist.descriptionPlaceholder")}
                  value={newServiceDesc}
                  onChange={(e) => setNewServiceDesc(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setServiceModalOpen(false)}
                  className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 dark:border-slate-700 dark:text-slate-300"
                >
                  {t("common.close")}
                </button>
                <button
                  type="submit"
                  disabled={isBusy("service") || !newServiceName.trim()}
                  className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {isBusy("service") ? t("receptionist.addingService") : t("receptionist.addService")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {rescheduleTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="reschedule-title"
            className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900"
          >
            <button
              type="button"
              onClick={() => setRescheduleTarget(null)}
              aria-label={t("common.close")}
              className="absolute right-4 top-4 text-slate-400 hover:text-slate-600"
            >
              <X className="h-5 w-5" />
            </button>
            <h2 id="reschedule-title" className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {t("receptionist.rescheduleTitle")}
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {rescheduleTarget.patient_name || t("receptionist.unknownPatient")} ·{" "}
              {rescheduleTarget.appointment_date} {rescheduleTarget.start_time}
            </p>
            <form onSubmit={handleRescheduleSubmit} className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.appointmentDate")}
                  </label>
                  <input
                    type="date"
                    value={rescheduleDate}
                    min={todayStr}
                    onChange={(e) => setRescheduleDate(e.target.value)}
                    required
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                    {t("receptionist.startTime")}
                  </label>
                  <input
                    type="time"
                    value={rescheduleTime}
                    onChange={(e) => setRescheduleTime(e.target.value)}
                    required
                    className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.doctorProviderOptional")}
                </label>
                <select
                  value={rescheduleDoctorId}
                  onChange={(e) => setRescheduleDoctorId(e.target.value)}
                  disabled={rescheduling.loading}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.anyAvailableProvider")}</option>
                  {rescheduleProviderOptions.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.name}
                    </option>
                  ))}
                </select>
                {rescheduling.failed && (
                  <p role="alert" className="mt-1 flex items-center gap-2 text-xs text-rose-700 dark:text-rose-400">
                    {t("receptionist.errLoadProviders")}
                    <button type="button" onClick={rescheduling.retry} className="font-medium underline">
                      {t("common.retry")}
                    </button>
                  </p>
                )}
              </div>
              {error && (
                <p role="alert" className="rounded-md bg-rose-50 p-2 text-xs text-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
                  {error}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setRescheduleTarget(null)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300"
                >
                  {t("common.close")}
                </button>
                <button
                  type="submit"
                  disabled={isBusy(`update:${rescheduleTarget.id}`) || !rescheduleDate || rescheduleDate < todayStr}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {isBusy(`update:${rescheduleTarget.id}`) ? t("common.loading") : t("receptionist.saveReschedule")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {cancelTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="cancel-title"
            className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900"
          >
            <h2 id="cancel-title" className="text-lg font-bold text-slate-900 dark:text-slate-100">
              {t("receptionist.cancelAppointmentTitle")}
            </h2>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {cancelTarget.patient_name || t("receptionist.unknownPatient")} ·{" "}
              {cancelTarget.appointment_date} {cancelTarget.start_time}
            </p>
            <form onSubmit={handleCancelSubmit} className="mt-4 space-y-3">
              <div>
                <label htmlFor="cancel-reason" className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  {t("receptionist.cancelReasonLabel")}
                </label>
                <textarea
                  id="cancel-reason"
                  rows={2}
                  maxLength={500}
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  required
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>
              {error && (
                <p role="alert" className="rounded-md bg-rose-50 p-2 text-xs text-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
                  {error}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setCancelTarget(null)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300"
                >
                  {t("receptionist.keepAppointment")}
                </button>
                <button
                  type="submit"
                  disabled={isBusy(`update:${cancelTarget.id}`) || !cancelReason.trim()}
                  className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-50"
                >
                  {isBusy(`update:${cancelTarget.id}`) ? t("common.loading") : t("receptionist.cancelAppointmentTitle")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
