"use client";

import { useEffect, useState, useCallback } from "react";
import { ApiError, api, formatDateTime } from "@/lib/api";
import EMARTable from "@/components/tables/EMARTable";
import type { MedicationRecord } from "@/components/tables/EMARTable";
import MedicationAdministrationModal, {
  PrescriptionOption,
} from "@/features/nurse/components/MedicationAdministrationModal";
import { PageHeading } from "@/components/common/PageHeading";

interface Admission {
  id: string;
  visit_id: string;
  patient_id: string;
  ward_id: string;
  bed_id: string;
  admitted_at: string;
  reason: string | null;
  status: string;
}

interface PatientInfo {
  id: string;
  full_name: string;
  uhid: string;
  sex: string | null;
  age_years: number | null;
  dob: string | null;
}

interface AdmissionInfo {
  id: string;
  admitted_at: string | null;
  ward_name: string;
  bed_number: string;
  reason: string | null;
}

interface AdmissionChart {
  patient: PatientInfo;
  admission: AdmissionInfo;
  medications: PrescriptionOption[];
}

export default function Page() {
  const [admissions, setAdmissions] = useState<Admission[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [chart, setChart] = useState<AdmissionChart | null>(null);
  const [records, setRecords] = useState<MedicationRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Modal states
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [correctionTarget, setCorrectionTarget] = useState<MedicationRecord | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Admission[]>("/admissions")
      .then((rows) => {
        if (cancelled) return;
        const active = rows.filter((a) => a.status === "admitted");
        setAdmissions(active);
        setSelected((current) => current ?? active[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof ApiError ? reason.message : "Could not load admissions");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadChartAndRecords = useCallback(async (admissionId: string) => {
    setError(null);
    try {
      const [chartRes, emarRes] = await Promise.all([
        api<AdmissionChart>(`/admissions/${admissionId}/chart`),
        api<MedicationRecord[]>(`/nursing/admissions/${admissionId}/medication-administrations`),
      ]);
      setChart(chartRes);
      setRecords(emarRes);
    } catch (reason: unknown) {
      setError(reason instanceof ApiError ? reason.message : "Could not load admission chart and eMAR");
    }
  }, []);

  useEffect(() => {
    if (!selected) return;
    void loadChartAndRecords(selected);
  }, [selected, loadChartAndRecords]);

  function handleOpenNewRecord() {
    setCorrectionTarget(null);
    setIsModalOpen(true);
  }

  function handleOpenCorrection(medication: MedicationRecord) {
    setCorrectionTarget(medication);
    setIsModalOpen(true);
  }

  async function handleAcknowledge(medication: MedicationRecord) {
    if (!selected) return;
    try {
      await api(`/nursing/medication-administrations/${medication.id}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      void loadChartAndRecords(selected);
    } catch (reason: unknown) {
      setError(reason instanceof ApiError ? reason.message : "Failed to acknowledge administration");
    }
  }

  const selectedAdmission = admissions?.find((a) => a.id === selected);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageHeading titleKey="nurse.emarTitle" />

        {selected && selectedAdmission && (
          <button
            type="button"
            onClick={handleOpenNewRecord}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 shadow-sm"
          >
            + Record Dose
          </button>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-md bg-danger/10 border border-danger/30 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {admissions !== null && admissions.length === 0 && (
        <div className="surface-card p-6">
          <p className="text-sm text-muted-foreground">No active admissions.</p>
        </div>
      )}

      {admissions && admissions.length > 0 && (
        <label className="block max-w-md space-y-1 text-sm">
          <span className="text-muted-foreground">Select Inpatient Admission</span>
          <select
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
            value={selected ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {admissions.map((admission) => (
              <option key={admission.id} value={admission.id}>
                {formatDateTime(admission.admitted_at)} · {admission.reason ?? "Admission"}
              </option>
            ))}
          </select>
        </label>
      )}

      {/* Patient Demographic & Stay Header (HD-17) */}
      {chart && (
        <div className="surface-card rounded-lg border border-border p-4 bg-muted/20">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-xs text-muted-foreground block">Patient</span>
              <span className="font-semibold text-foreground text-base">
                {chart.patient.full_name || "Unnamed patient"}
              </span>
              <div className="text-xs text-muted-foreground mt-0.5 font-mono">
                UHID: {chart.patient.uhid}
              </div>
            </div>

            <div>
              <span className="text-xs text-muted-foreground block">Demographics</span>
              <span className="font-medium text-foreground">
                {chart.patient.age_years ? `${chart.patient.age_years} yrs` : "Age unknown"} ·{" "}
                {chart.patient.sex ? chart.patient.sex.toUpperCase() : "Unknown"}
              </span>
              {chart.patient.dob && (
                <div className="text-xs text-muted-foreground mt-0.5">
                  DOB: {chart.patient.dob}
                </div>
              )}
            </div>

            <div>
              <span className="text-xs text-muted-foreground block">Location</span>
              <span className="font-medium text-foreground">
                Ward: {chart.admission.ward_name || "General"}
              </span>
              <div className="text-xs text-muted-foreground mt-0.5">
                Bed: {chart.admission.bed_number || "—"}
              </div>
            </div>

            <div>
              <span className="text-xs text-muted-foreground block">Admission</span>
              <span className="font-medium text-foreground">
                {chart.admission.admitted_at ? formatDateTime(chart.admission.admitted_at) : "—"}
              </span>
              <div className="text-xs text-muted-foreground mt-0.5 truncate" title={chart.admission.reason ?? ""}>
                Reason: {chart.admission.reason || "Not specified"}
              </div>
            </div>
          </div>
        </div>
      )}

      {selected && records === null && !error && (
        <p className="text-sm text-muted-foreground">Loading eMAR chart…</p>
      )}

      {records && (
        <EMARTable
          medications={records}
          onCorrect={handleOpenCorrection}
          onAcknowledge={handleAcknowledge}
        />
      )}

      {selected && selectedAdmission && (
        <MedicationAdministrationModal
          isOpen={isModalOpen}
          onClose={() => {
            setIsModalOpen(false);
            setCorrectionTarget(null);
          }}
          onSuccess={() => {
            void loadChartAndRecords(selected);
          }}
          admissionId={selected}
          patientId={selectedAdmission.patient_id}
          prescriptionItems={chart?.medications ?? []}
          correctionRecord={correctionTarget}
        />
      )}
    </div>
  );
}
