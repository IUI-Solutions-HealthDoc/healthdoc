"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
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
  updateAppointment,
} from "@/features/appointments/api";
import type {
  Appointment,
  AppointmentCheckInResult,
  AppointmentCreate,
  AppointmentService,
  AppointmentStatus,
} from "@/features/appointments/types";
import { listQueueOpeningOptions, searchPatients } from "@/features/receptionist/api";
import type { PatientSearchResult } from "@/features/receptionist/types";
import { getUserFacingError } from "@/lib/api";
import { PageHeading } from "@/components/common/PageHeading";
import { useLocale, type MessageKey } from "@/lib/i18n";

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
  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const [selectedDate, setSelectedDate] = useState(todayStr);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [services, setServices] = useState<AppointmentService[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [doctors, setDoctors] = useState<Array<{ id: string; full_name: string }>>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  // Booking Modal State
  const [bookingModalOpen, setBookingModalOpen] = useState(false);
  const [serviceModalOpen, setServiceModalOpen] = useState(false);

  // Form states for booking
  const [patientSearchTerm, setPatientSearchTerm] = useState("");
  const [patientSearchResults, setPatientSearchResults] = useState<PatientSearchResult[]>([]);
  const [patientSearching, setPatientSearching] = useState(false);
  const [selectedPatient, setSelectedPatient] = useState<PatientSearchResult | null>(null);

  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [selectedDoctorId, setSelectedDoctorId] = useState("");
  const [selectedServiceId, setSelectedServiceId] = useState("");
  const [apptTime, setApptTime] = useState("09:00");
  const [apptDuration, setApptDuration] = useState(15);
  const [isWalkIn, setIsWalkIn] = useState(false);
  const [isTeleconsult, setIsTeleconsult] = useState(false);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Form states for new service catalogue entry
  const [newServiceName, setNewServiceName] = useState("");
  const [newServiceDuration, setNewServiceDuration] = useState(15);
  const [newServiceDeptId, setNewServiceDeptId] = useState("");
  const [newServiceDesc, setNewServiceDesc] = useState("");
  const [serviceSubmitting, setServiceSubmitting] = useState(false);

  // Check-in confirmation state
  const [_checkInResult, setCheckInResult] = useState<AppointmentCheckInResult | null>(null);

  // Load initial reference data
  useEffect(() => {
    async function init() {
      try {
        const [deptRes, srvRes, rosterRes] = await Promise.all([
          listDepartments(),
          listAppointmentServices(),
          listQueueOpeningOptions().catch(() => ({ service_date: "", items: [] })),
        ]);
        setDepartments(deptRes.items ?? []);
        setServices(srvRes ?? []);
        const uniqueDoctors = Array.from(
          new Map(
            (rosterRes.items ?? []).map((item) => [
              item.staff_user_id,
              { id: item.staff_user_id, full_name: item.staff_name },
            ])
          ).values()
        );
        setDoctors(uniqueDoctors);
      } catch (err) {
        console.error("Failed to load reference data", err);
      }
    }
    init();
  }, []);

  // Fetch appointments whenever date changes
  const loadAppointments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAppointments({
        date_from: selectedDate,
        date_to: selectedDate,
        status: statusFilter === "all" ? undefined : statusFilter,
      });
      setAppointments(res);
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errLoadAppointments")));
    } finally {
      setLoading(false);
    }
  }, [selectedDate, statusFilter, t]);

  useEffect(() => {
    loadAppointments();
  }, [loadAppointments]);

  // Handle patient search for booking
  async function handleSearchPatient(e: React.FormEvent) {
    e.preventDefault();
    if (!patientSearchTerm.trim()) return;
    setPatientSearching(true);
    try {
      const res = await searchPatients({ uhid: patientSearchTerm.trim() });
      if (res.items && res.items.length > 0) {
        setPatientSearchResults(res.items);
      } else {
        const byPhone = await searchPatients({ mobile: patientSearchTerm.trim() });
        setPatientSearchResults(byPhone.items ?? []);
      }
    } catch {
      setPatientSearchResults([]);
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

    setSubmitting(true);
    setError(null);

    const srv = services.find((s) => s.id === selectedServiceId);

    const payload: AppointmentCreate = {
      patient_id: selectedPatient.id,
      department_id: selectedDeptId,
      doctor_user_id: selectedDoctorId || null,
      service_id: selectedServiceId || null,
      service_name: srv ? srv.name : t("receptionist.defaultConsultation"),
      duration_minutes: apptDuration,
      appointment_date: selectedDate,
      start_time: apptTime,
      is_walk_in: isWalkIn,
      is_teleconsult: isTeleconsult,
      notes: notes.trim() || null,
    };

    try {
      await createAppointment(payload);
      setFeedback(t("receptionist.feedbackBooked"));
      setBookingModalOpen(false);
      resetBookingForm();
      loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errBookAppointment")));
    } finally {
      setSubmitting(false);
    }
  }

  function resetBookingForm() {
    setSelectedPatient(null);
    setPatientSearchTerm("");
    setPatientSearchResults([]);
    setSelectedDeptId("");
    setSelectedDoctorId("");
    setSelectedServiceId("");
    setApptTime("09:00");
    setApptDuration(15);
    setIsWalkIn(false);
    setIsTeleconsult(false);
    setNotes("");
  }

  // Handle Check-in Action
  async function handleCheckIn(appointmentId: string) {
    setError(null);
    setFeedback(null);
    setCheckInResult(null);
    try {
      const res = await checkInAppointment(appointmentId, { priority: "normal" });
      setCheckInResult(res);
      setFeedback(
        t("receptionist.feedbackCheckIn", {
          visit: res.visit_number,
          token: res.token_display ?? t("receptionist.tokenIssuedFallback"),
        }),
      );
      loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCheckIn")));
    }
  }

  // Handle Cancel Action
  async function handleCancel(appointmentId: string) {
    const reason = window.prompt(t("receptionist.promptCancelReason"));
    if (!reason || !reason.trim()) return;

    try {
      await updateAppointment(appointmentId, {
        status: "cancelled",
        cancellation_reason: reason.trim(),
      });
      setFeedback(t("receptionist.feedbackCancelled"));
      loadAppointments();
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCancelAppointment")));
    }
  }

  // Handle Create Service in Catalogue
  async function handleCreateService(e: React.FormEvent) {
    e.preventDefault();
    if (!newServiceName.trim()) return;

    setServiceSubmitting(true);
    try {
      const created = await createAppointmentService({
        name: newServiceName.trim(),
        duration_minutes: newServiceDuration,
        department_id: newServiceDeptId || null,
        description: newServiceDesc.trim() || null,
      });
      setServices((prev) => [...prev, created]);
      setFeedback(t("receptionist.feedbackServiceAdded", { name: created.name }));
      setServiceModalOpen(false);
      setNewServiceName("");
      setNewServiceDuration(15);
      setNewServiceDeptId("");
      setNewServiceDesc("");
    } catch (err) {
      setError(getUserFacingError(err, t("receptionist.errCreateService")));
    } finally {
      setServiceSubmitting(false);
    }
  }

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
            onClick={() => setBookingModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
          >
            <Plus className="h-4 w-4" />
            {t("receptionist.bookAppointment")}
          </button>
        </div>
      </div>

      {/* Notifications */}
      {feedback && (
        <div className="mt-4 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <span>{feedback}</span>
          </div>
          <button type="button" onClick={() => setFeedback(null)} className="text-emerald-700 hover:text-emerald-900">
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
              onClick={() => setBookingModalOpen(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700"
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
                    {appt.status === "booked" && (
                      <div className="flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => handleCheckIn(appt.id)}
                          className="flex-1 rounded-md bg-emerald-600 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
                        >
                          {t("receptionist.checkIn")}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleCancel(appt.id)}
                          className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400"
                        >
                          {t("common.cancel")}
                        </button>
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
                        onChange={(e) => setPatientSearchTerm(e.target.value)}
                        className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                      />
                      <button
                        type="button"
                        onClick={handleSearchPatient}
                        disabled={patientSearching}
                        className="rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 dark:bg-slate-700"
                      >
                        {patientSearching ? t("common.searching") : t("common.search")}
                      </button>
                    </div>

                    {patientSearchResults.length > 0 && (
                      <div className="max-h-36 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-800/60">
                        {patientSearchResults.map((p) => (
                          <div
                            key={p.id}
                            onClick={() => {
                              setSelectedPatient(p);
                              setPatientSearchResults([]);
                            }}
                            className="cursor-pointer rounded p-2 text-xs hover:bg-indigo-50 dark:hover:bg-indigo-950/40"
                          >
                            <div className="font-semibold text-slate-900 dark:text-slate-100">
                              {p.full_name}
                            </div>
                            <div className="text-slate-500">
                              {t("receptionist.labelUhid")}: {p.uhid} | {t("receptionist.labelPhone")}: {p.mobile_masked || "N/A"}
                            </div>
                          </div>
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
                        UHID: {selectedPatient.uhid}
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
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                >
                  <option value="">{t("receptionist.anyAvailableProvider")}</option>
                  {doctors.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.full_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Date, Time & Duration */}
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
                  disabled={submitting || !selectedPatient || !selectedDeptId}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {submitting ? t("common.loading") : t("receptionist.confirmBooking")}
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
                  disabled={serviceSubmitting || !newServiceName.trim()}
                  className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {serviceSubmitting ? t("receptionist.addingService") : t("receptionist.addService")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
