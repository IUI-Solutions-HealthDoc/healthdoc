"use client";

import { useCallback, useEffect, useState } from "react";

import AdmissionForm from "@/features/ipd/components/AdmissionForm";
import DischargeForm from "@/features/ipd/components/DischargeForm";
import AddPatientMovementForm from "@/components/AddPatientMovementForm";
import BedGrid from "@/components/BedGrid";
import { AdmissionChartDrawer } from "@/features/ipd/components/AdmissionChartDrawer";

import { useAddAdmission, useAddDischarge } from "@/features/ipd/hooks";
import { useAddPatientMovement } from "@/components/AddPatientMovementForm";
import {
  getWards,
  getBeds,
  getActiveAdmissions,
  getDischarges,
  getPendingAdmissions,
  type Admission,
  type Discharge,
  type PendingAdmissionItem,
} from "@/features/ipd/api/ipd";
import { DEFAULT_NOTIFICATION_PREVIEW } from "@/features/ipd/constants";

import type { Ward } from "@/features/nurse/components/WardSelector/WardSelector.types";
import { flattenBedGrids, type Bed } from "@/components/BedGrid/BedGrid.types";

type Tab = "dashboard" | "to_admit" | "admit" | "transfer" | "discharge";

export default function IpdPage() {
  const [tab, setTab] = useState<Tab>("dashboard");

  const [wards, setWards] = useState<Ward[]>([]);
  const [beds, setBeds] = useState<Bed[]>([]);
  const [admissions, setAdmissions] = useState<Admission[]>([]);
  const [discharges, setDischarges] = useState<Discharge[]>([]);
  const [pendingAdmissions, setPendingAdmissions] = useState<PendingAdmissionItem[]>([]);
  const [selectedAdmissionId, setSelectedAdmissionId] = useState("");
  const [chartAdmissionId, setChartAdmissionId] = useState<string | null>(null);
  const [selectedWardFilter, setSelectedWardFilter] = useState<string>("all");
  const [loadError, setLoadError] = useState<string | null>(null);

  const { submitAdmission, isSubmitting: isAdmitting } = useAddAdmission();
  const { submitDischarge, isSubmitting: isDischarging } = useAddDischarge();
  const { submitPatientMovement, isSubmitting: isTransferring } = useAddPatientMovement();

  const loadData = useCallback(async () => {
    try {
      setLoadError(null);
      const wardsRes = await getWards();
      const [bedGrids, admissionsRes, dischargesRes, pendingRes] = await Promise.all([
        Promise.all(wardsRes.map((ward) => getBeds(ward.id))),
        getActiveAdmissions(),
        getDischarges(),
        getPendingAdmissions(),
      ]);

      setWards(wardsRes);
      setBeds(flattenBedGrids(bedGrids));
      setAdmissions(admissionsRes);
      setDischarges(dischargesRes);
      setPendingAdmissions(pendingRes || []);
    } catch (error) {
      console.error("Unable to load IPD data", error);
      setLoadError("Unable to load live IPD data. Check the API connection and retry.");
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const selectedAdmission = admissions.find((a) => a.id === selectedAdmissionId);

  // KPIs per Architecture doc §24 (Reports and MIS): "IPD admissions/
  // discharges/bed occupancy".
  const activeAdmissionsCount = admissions.filter((a) => a.status === "admitted").length;

  const bedStatusCounts = beds.reduce<Record<string, number>>((acc, bed) => {
    acc[bed.status] = (acc[bed.status] ?? 0) + 1;
    return acc;
  }, {});

  const today = new Date().toDateString();
  const dischargesTodayCount = discharges.filter(
    (d) => new Date(d.discharged_at).toDateString() === today
  ).length;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold text-primary">IPD</h1>
        <p className="mt-2 text-muted-foreground">
          Admit patients, record in-hospital ward/bed transfers, or discharge
          (including transfer to another facility).
        </p>
      </div>

      <div className="flex gap-2 border-b">
        {(
          [
            { id: "dashboard", label: "Dashboard" },
            { id: "to_admit", label: `To Admit Queue (${pendingAdmissions.length})` },
            { id: "admit", label: "Admit" },
            { id: "transfer", label: "Ward transfer" },
            { id: "discharge", label: "Discharge" },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-primary text-primary font-bold"
                : "text-muted-foreground hover:text-slate-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loadError && (
        <div className="surface-card border border-destructive p-4 text-sm text-destructive">
          {loadError}
        </div>
      )}

      {/* HD-14: Zero-ward actionable guidance banner */}
      {wards.length === 0 && (
        <div className="rounded-xl border border-amber-300 bg-amber-50/90 p-5 text-amber-950 shadow-sm">
          <div className="flex items-start gap-4">
            <span className="text-3xl">⚠️</span>
            <div className="flex-1">
              <h3 className="text-base font-bold text-amber-900">
                No Inpatient Wards Configured
              </h3>
              <p className="mt-1 text-sm text-amber-800">
                This facility has no active wards or beds set up yet. Hospital administrators must configure wards and bed layouts before patient admissions can be accepted.
              </p>
              <div className="mt-3">
                <a
                  href="/maintenance"
                  className="inline-flex items-center rounded-lg bg-amber-700 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-amber-800 transition"
                >
                  Configure Hospital Wards in Maintenance →
                </a>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === "dashboard" && (
        <div className="space-y-6">
          {/* KPI Cards */}
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="surface-card p-4">
              <p className="text-sm text-muted-foreground">Active Admissions</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{activeAdmissionsCount}</p>
            </div>

            <div className="surface-card p-4">
              <p className="text-sm text-muted-foreground">Pending &ldquo;To Admit&rdquo; Orders</p>
              <p className="mt-1 text-2xl font-bold text-blue-700">{pendingAdmissions.length}</p>
            </div>

            <div className="surface-card p-4">
              <p className="text-sm text-muted-foreground">Discharges Today</p>
              <p className="mt-1 text-2xl font-bold text-emerald-700">{dischargesTodayCount}</p>
            </div>
          </div>

          {/* HD-14: Multi-Ward Bed Status Board & Status Legend */}
          <div className="surface-card p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900">
                  Live Ward Bed Board (HD-14)
                </h2>
                <p className="text-xs text-muted-foreground">
                  Click any occupied bed to view patient admission chart (HD-15) and safety checklist (HD-16).
                </p>
              </div>

              {/* Status Legend */}
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-emerald-500 ring-2 ring-emerald-200" />
                  <span className="font-medium text-slate-700">Vacant ({bedStatusCounts["vacant"] ?? 0})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-indigo-600 ring-2 ring-indigo-200" />
                  <span className="font-medium text-slate-700">Occupied ({bedStatusCounts["occupied"] ?? 0})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-amber-500 ring-2 ring-amber-200" />
                  <span className="font-medium text-slate-700">Maintenance ({bedStatusCounts["maintenance"] ?? 0})</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-purple-500 ring-2 ring-purple-200" />
                  <span className="font-medium text-slate-700">Reserved ({bedStatusCounts["reserved"] ?? 0})</span>
                </div>
              </div>
            </div>

            {/* Ward Filter Tabs */}
            {wards.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-2 border-t">
                <button
                  type="button"
                  onClick={() => setSelectedWardFilter("all")}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                    selectedWardFilter === "all"
                      ? "bg-slate-900 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  All Wards ({beds.length} beds)
                </button>
                {wards.map((ward) => {
                  const wardBeds = beds.filter((b) => b.ward_id === ward.id);
                  return (
                    <button
                      key={ward.id}
                      type="button"
                      onClick={() => setSelectedWardFilter(ward.id)}
                      className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                        selectedWardFilter === ward.id
                          ? "bg-slate-900 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {ward.name} ({wardBeds.length})
                    </button>
                  );
                })}
              </div>
            )}

            {/* Render BedGrid */}
            <BedGrid
              beds={
                selectedWardFilter === "all"
                  ? beds
                  : beds.filter((b) => b.ward_id === selectedWardFilter)
              }
              onBedClick={(bed) => {
                if (bed.occupant?.admission_id) {
                  setChartAdmissionId(bed.occupant.admission_id);
                }
              }}
            />
          </div>
        </div>
      )}

      {/* HD-13: To Admit Queue Tab */}
      {tab === "to_admit" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-slate-900">
                &ldquo;To Admit&rdquo; Clinical Disposition Queue (HD-13)
              </h2>
              <p className="text-sm text-muted-foreground">
                Patients ordered for inpatient admission by OPD and Emergency clinicians awaiting ward bed allocation.
              </p>
            </div>
            <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-bold text-blue-800">
              {pendingAdmissions.length} Pending
            </span>
          </div>

          {pendingAdmissions.length === 0 ? (
            <div className="surface-card p-10 text-center">
              <p className="text-base font-semibold text-slate-700">No Pending Admissions</p>
              <p className="mt-1 text-sm text-muted-foreground">
                All doctor-ordered inpatient dispositions have been assigned to beds.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {pendingAdmissions.map((item) => {
                const isEmergency = item.priority === "emergency";
                const isUrgent = item.priority === "urgent";

                return (
                  <div
                    key={item.disposition_id}
                    className="surface-card flex flex-col justify-between p-4 border rounded-xl shadow-sm hover:shadow-md transition"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h3 className="font-bold text-base text-slate-900">
                            {item.patient_name}
                          </h3>
                          <p className="text-xs text-slate-500">
                            UHID: {item.patient_uhid} · {item.patient_sex || ""} · {item.patient_age ? `${item.patient_age} yrs` : ""}
                          </p>
                        </div>
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${
                            isEmergency
                              ? "bg-red-100 text-red-700 animate-pulse ring-1 ring-red-300"
                              : isUrgent
                              ? "bg-amber-100 text-amber-800"
                              : "bg-blue-100 text-blue-800"
                          }`}
                        >
                          {item.priority}
                        </span>
                      </div>

                      <div className="mt-3 space-y-1.5 text-xs">
                        {item.recommended_ward_name && (
                          <p className="text-slate-700">
                            <strong className="text-slate-900">Rec Ward:</strong> {item.recommended_ward_name}
                          </p>
                        )}
                        {item.doctor_name && (
                          <p className="text-slate-700">
                            <strong className="text-slate-900">Doctor:</strong> {item.doctor_name}
                          </p>
                        )}
                        {item.reason && (
                          <div className="mt-2 rounded bg-slate-50 p-2 text-slate-700 border border-slate-200/60">
                            <strong className="text-slate-900">Indication:</strong> {item.reason}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="mt-4 pt-3 border-t flex items-center justify-between">
                      <span className="text-[11px] text-slate-400">
                        {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <button
                        type="button"
                        onClick={() => setTab("admit")}
                        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 transition"
                      >
                        Admit to Bed →
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {tab === "admit" && (
        <AdmissionForm
          wards={wards}
          beds={beds}
          isSubmitting={isAdmitting}
          onSubmit={async (data) => {
            const ok = await submitAdmission(data);
            if (ok) await loadData();
            return ok;
          }}
        />
      )}

      {(tab === "transfer" || tab === "discharge") && (
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-semibold">
              Select Admission
            </label>
            <select
              className="w-full rounded-md border px-3 py-2 text-sm"
              value={selectedAdmissionId}
              onChange={(e) => setSelectedAdmissionId(e.target.value)}
            >
              <option value="">Select…</option>
              {admissions.map((a) => {
                const bed = beds.find((b) => b.bed_id === a.bed_id);
                return (
                  <option key={a.id} value={a.id}>
                    {a.patient_id} — Bed {bed?.bed_number ?? a.bed_id}
                  </option>
                );
              })}
            </select>
          </div>

          {selectedAdmission && tab === "transfer" && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                In-hospital ward or bed move. To send the patient to another
                facility, use Discharge with type Transferred to Another Facility.
              </p>
            <AddPatientMovementForm
              admissionId={selectedAdmission.id}
              wards={wards}
              beds={beds}
              isSubmitting={isTransferring}
              onSubmit={async (data) => {
                const ok = await submitPatientMovement(data);
                if (ok) {
                  setSelectedAdmissionId("");
                  await loadData();
                }
                return ok;
              }}
            />
            </div>
          )}

          {selectedAdmission && tab === "discharge" && (
            <DischargeForm
              admissionId={selectedAdmission.id}
              notificationPreview={DEFAULT_NOTIFICATION_PREVIEW}
              isSubmitting={isDischarging}
              onSubmit={async (data) => {
                const ok = await submitDischarge(data);
                if (ok) {
                  setSelectedAdmissionId("");
                  await loadData();
                }
                return ok;
              }}
            />
          )}
        </div>
      )}

      {/* HD-15: Admission Chart Drawer */}
      <AdmissionChartDrawer
        admissionId={chartAdmissionId}
        open={Boolean(chartAdmissionId)}
        onClose={() => setChartAdmissionId(null)}
      />
    </div>
  );
}
