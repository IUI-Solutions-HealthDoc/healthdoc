"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import AddPatientMovementForm from "@/components/AddPatientMovementForm";
import { useAddPatientMovement } from "@/components/AddPatientMovementForm/useAddPatientMovement";
import BedGrid from "@/components/BedGrid";
import { flattenBedGrids, type Bed } from "@/components/BedGrid/BedGrid.types";
import EMARTable from "@/components/tables/EMARTable";
import type { MedicationRecord } from "@/components/tables/EMARTable/EMARTable.types";
import VitalsTimeline, { VitalsChart } from "@/components/VitalsTimeline";
import type { VitalRecord } from "@/components/VitalsTimeline/VitalsTimeline.types";
import type {
  Discharge,
  DischargeSummary,
} from "@/features/ipd/api/ipd";
import {
  getActiveAdmissions,
  getBeds,
  getDischarges,
  getWards,
} from "@/features/ipd/api/ipd";
import AddHandoverForm from "@/features/nurse/components/AddHandoverForm";
import AddIntakeOutputForm from "@/features/nurse/components/AddIntakeOutputForm";
import AddVitalsForm from "@/features/nurse/components/AddVitalsForm";
import HandoverNotes from "@/features/nurse/components/HandoverNotes";
import type { HandoverNote } from "@/features/nurse/components/HandoverNotes/HandoverNotes.types";
import IncidentReportForm from "@/features/nurse/components/IncidentReportForm";
import { IncidentListPanel } from "@/features/nurse/components/IncidentListPanel";
import TaskQueue, { type Order } from "@/features/nurse/components/TaskQueue";
import WardSelector from "@/features/nurse/components/WardSelector";
import type { Ward } from "@/features/nurse/components/WardSelector/WardSelector.types";
import { useAddHandover } from "@/features/nurse/hooks/useAddHandover";
import { useAddIntakeOutput } from "@/features/nurse/hooks/useAddIntakeOutput";
import { useAddVitals } from "@/features/nurse/hooks/useAddVitals";
import { useIncidents } from "@/features/nurse/hooks/useIncidents";
import type { HandoverRecipientOption } from "@/features/nurse/types";
import {
  acceptNursingTask,
  completeNursingTask,
  getAdmissionFluidBalance,
  getAdmissionMedicationAdministrations,
  getAdmissionSummary,
  getNursingTasks,
  getPatientVitals,
  type FluidBalance,
  type NursingTask,
} from "@/features/nurse/api/nursing";
import { formatDateTime } from "@/lib/api";

type PatientAction = "vitals" | "fluid" | "transfer" | "handover" | "incident" | null;

function toOrder(task: NursingTask): Order {
  return {
    id: task.id,
    encounter_id: task.encounter_id,
    patient_id: task.patient_id,
    order_type: task.order_type,
    priority: task.priority,
    status: task.status,
    ordered_at: task.ordered_at,
    accepted_at: task.accepted_at,
    accepted_by: task.accepted_by,
    completed_at: task.completed_at,
    completed_by: task.completed_by,
    completion_note: task.completion_note,
  };
}

function Metric({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div className="surface-card p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}

export default function Page() {
  // `null` means "not loaded yet", which is NOT the same as "loaded, and
  // there are none" (#488). While this was `Ward[]` starting at `[]`, the two
  // were indistinguishable and the panel rendered "Loading wards…" forever on
  // a perfectly successful 200 that happened to return an empty list — the
  // exact symptom reported, with the request succeeding every time.
  const [wards, setWards] = useState<Ward[] | null>(null);
  const [allBeds, setAllBeds] = useState<Bed[]>([]);
  const [selectedWard, setSelectedWard] = useState("");
  const [selectedBedId, setSelectedBedId] = useState<string | null>(null);
  const [discharges, setDischarges] = useState<Discharge[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [taskQueueStatus, setTaskQueueStatus] = useState<
    "loading" | "connected" | "error"
  >("loading");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [vitals, setVitals] = useState<VitalRecord[]>([]);
  const [fluidBalance, setFluidBalance] = useState<FluidBalance | null>(null);
  const [medications, setMedications] = useState<MedicationRecord[]>([]);
  const [handoverNotes, setHandoverNotes] = useState<HandoverNote[]>([]);
  const [summary, setSummary] = useState<DischargeSummary | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<PatientAction>(null);

  const { submitVitals, isSubmitting: isSubmittingVitals } = useAddVitals();
  const { submitIntakeOutput, isSubmitting: isSubmittingFluid } = useAddIntakeOutput();
  const { submitPatientMovement, isSubmitting: isSubmittingTransfer } =
    useAddPatientMovement();
  const { submitHandover, isSubmitting: isSubmittingHandover } = useAddHandover();

  const selectedPatientId = useMemo(
    () =>
      allBeds.find((bed) => bed.bed_id === selectedBedId)?.occupant?.patient_id ?? null,
    [allBeds, selectedBedId],
  );
  const {
    incidents,
    loading: incidentsLoading,
    error: incidentsError,
    refresh: refreshIncidents,
  } = useIncidents(selectedPatientId);

  const handoverRecipients = useMemo<HandoverRecipientOption[]>(() => {
    const seen = new Map<string, HandoverRecipientOption>();
    for (const note of handoverNotes) {
      if (!note.handed_over_to || seen.has(note.handed_over_to)) continue;
      seen.set(note.handed_over_to, {
        value: note.handed_over_to,
        label: `Prior recipient · ${note.handed_over_to.slice(0, 8)}`,
      });
    }
    return [...seen.values()];
  }, [handoverNotes]);

  const loadBase = useCallback(async () => {
    setLoadError(null);
    setTaskQueueStatus("loading");
    try {
      const wardRows = await getWards();
      const [bedGrids, admissionRows, dischargeRows, taskRows] = await Promise.all([
        Promise.all(wardRows.map((ward) => getBeds(ward.id))),
        getActiveAdmissions(),
        getDischarges(),
        getNursingTasks(),
      ]);
      void admissionRows;
      setWards(wardRows);
      setAllBeds(flattenBedGrids(bedGrids));
      setDischarges(dischargeRows);
      setOrders(taskRows.map(toOrder));
      setSelectedWard((current) =>
        wardRows.some((ward) => ward.id === current) ? current : (wardRows[0]?.id ?? ""),
      );
      setTaskQueueStatus("connected");
    } catch (reason) {
      console.error("Unable to load live ward data", reason);
      setLoadError("Unable to load live ward data. Check the API connection and retry.");
      setTaskQueueStatus("error");
    }
  }, []);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  const selectedBed = useMemo(
    () => allBeds.find((bed) => bed.bed_id === selectedBedId) ?? null,
    [allBeds, selectedBedId],
  );
  const occupant = selectedBed?.occupant ?? null;
  const wardBeds = allBeds.filter((bed) => bed.ward_id === selectedWard);

  const loadPatientDetail = useCallback(async (bed: Bed | null) => {
    if (!bed?.occupant) {
      setVitals([]);
      setFluidBalance(null);
      setMedications([]);
      setHandoverNotes([]);
      setSummary(null);
      setDetailError(null);
      return;
    }
    setDetailLoading(true);
    setDetailError(null);
    setHandoverNotes([]);
    const [vitalsResult, fluidResult, emarResult, summaryResult] =
      await Promise.allSettled([
        getPatientVitals(bed.occupant.patient_id),
        getAdmissionFluidBalance(bed.occupant.admission_id),
        getAdmissionMedicationAdministrations(bed.occupant.admission_id),
        getAdmissionSummary(bed.occupant.admission_id),
      ]);
    setVitals(vitalsResult.status === "fulfilled" ? vitalsResult.value : []);
    setFluidBalance(fluidResult.status === "fulfilled" ? fluidResult.value : null);
    setMedications(emarResult.status === "fulfilled" ? emarResult.value : []);
    setSummary(summaryResult.status === "fulfilled" ? summaryResult.value : null);
    if (
      [vitalsResult, fluidResult, emarResult, summaryResult].some(
        (entry) => entry.status === "rejected",
      )
    ) {
      setDetailError("Some live patient panels could not be loaded. Retry before acting on this chart.");
    }
    setDetailLoading(false);
  }, []);

  useEffect(() => {
    void loadPatientDetail(selectedBed);
  }, [loadPatientDetail, selectedBed]);

  function changeWard(wardId: string) {
    setSelectedWard(wardId);
    setSelectedBedId(null);
    setActiveAction(null);
  }

  function selectBed(bed: Bed) {
    setSelectedBedId(bed.bed_id);
    setActiveAction(null);
  }

  async function acceptOrder(orderId: string) {
    try {
      const accepted = await acceptNursingTask(orderId);
      setOrders((current) =>
        current.map((order) => (order.id === accepted.id ? toOrder(accepted) : order)),
      );
    } catch (reason) {
      console.error("Unable to accept nursing task", reason);
      setTaskQueueStatus("error");
    }
  }

  async function checkOff(orderId: string) {
    try {
      const completed = await completeNursingTask(orderId);
      setOrders((current) =>
        current.map((order) => (order.id === completed.id ? toOrder(completed) : order)),
      );
    } catch (reason) {
      console.error("Unable to complete nursing task", reason);
      setTaskQueueStatus("error");
    }
  }

  const today = new Date().toDateString();
  const dischargesToday = discharges.filter(
    (discharge) => new Date(discharge.discharged_at).toDateString() === today,
  ).length;
  const patientOrders = occupant
    ? orders.filter((order) => order.patient_id === occupant.patient_id)
    : [];

  const wardName = (wardId: string | null) =>
    (wards ?? []).find((ward) => ward.id === wardId)?.name ?? (wardId ? wardId.slice(0, 8) : "—");
  const bedName = (bedId: string | null) =>
    allBeds.find((bed) => bed.bed_id === bedId)?.bed_number ?? (bedId ? bedId.slice(0, 8) : "—");

  return (
    <main className="mx-auto max-w-screen-2xl space-y-8 px-6 py-8">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-primary">Nurse ward dashboard</h1>
          <p className="mt-2 text-muted-foreground">
            Live bed occupancy, observations, fluid balance, eMAR, handover, incidents and orders.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-2 text-sm"
            onClick={() => setActiveAction(activeAction === "incident" ? null : "incident")}
          >
            Report incident
          </button>
          <button type="button" onClick={() => void loadBase()} className="text-sm underline">
            Refresh ward
          </button>
        </div>
      </section>

      {loadError ? (
        <p role="alert" className="rounded-md bg-danger-muted p-4 text-sm text-danger">
          {loadError}
        </p>
      ) : null}

      {activeAction === "incident" && !occupant ? (
        <IncidentReportForm
          wardId={selectedWard || undefined}
          onSuccess={() => setActiveAction(null)}
        />
      ) : null}

      {wards === null ? (
        <div className="surface-card p-6 text-sm text-muted-foreground">Loading wards…</div>
      ) : wards.length > 0 ? (
        <WardSelector wards={wards} selectedWard={selectedWard} onChange={changeWard} />
      ) : (
        // Phrased like the other empty states on this screen ("No beds
        // available", "No pending orders") so a ward-less facility reads as a
        // fact about the data rather than a page that never finished.
        <div className="surface-card p-6 text-sm text-muted-foreground">
          No wards found for this facility.
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-3">
        <Metric
          label="Occupied beds"
          value={wardBeds.filter((bed) => bed.status === "occupied").length}
          detail="Live admissions in this ward"
        />
        <Metric
          label="Vacant beds"
          value={wardBeds.filter((bed) => bed.status === "vacant").length}
          detail="Available now"
        />
        <Metric label="Discharges today" value={dischargesToday} detail="Facility-wide" />
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">Pending doctor orders</h2>
          <p className="text-sm text-muted-foreground">
            Accept records ownership (`accepted_at` / `accepted_by`). Complete records
            check-off (`completed_at` / `completed_by`).
          </p>
        </div>
        <p
          data-testid="nursing-api-status"
          data-status={taskQueueStatus}
          className={taskQueueStatus === "error" ? "text-sm text-danger" : "sr-only"}
        >
          {taskQueueStatus === "error"
            ? "Unable to load nursing tasks. Check the API connection and retry."
            : `Nursing API ${taskQueueStatus}`}
        </p>
        <TaskQueue orders={orders} onAccept={acceptOrder} onCheckOff={checkOff} />
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">Ward overview</h2>
          <p className="text-sm text-muted-foreground">
            Occupants come directly from the active admission attached to each bed.
          </p>
        </div>
        <BedGrid beds={wardBeds} selectedBedId={selectedBedId} onBedClick={selectBed} />
      </section>

      {!selectedBed ? (
        <section className="surface-card p-6 text-sm text-muted-foreground">
          Select a bed to open its live clinical panels.
        </section>
      ) : !occupant ? (
        <section className="surface-card p-6 text-sm text-muted-foreground">
          Bed {selectedBed.bed_number} has no active occupant.
        </section>
      ) : (
        <>
          <section className="surface-card space-y-3 p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">{occupant.patient_name ?? "Unnamed patient"}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {occupant.uhid ?? occupant.patient_id} · Bed {selectedBed.bed_number}
                </p>
              </div>
              <span className="rounded-full bg-info-muted px-3 py-1 text-sm text-info">
                Admitted {formatDateTime(occupant.admitted_at)}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              Admission <span className="font-mono">{occupant.admission_id}</span>
            </p>
          </section>

          {detailLoading ? <p className="text-sm text-muted-foreground">Loading patient chart…</p> : null}
          {detailError ? (
            <p role="alert" className="rounded-md bg-danger-muted p-4 text-sm text-danger">
              {detailError}
            </p>
          ) : null}

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Vitals</h2>
                <p className="text-sm text-muted-foreground">All recorded observations for this patient.</p>
              </div>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-2 text-sm"
                onClick={() => setActiveAction(activeAction === "vitals" ? null : "vitals")}
              >
                Record vitals
              </button>
            </div>
            <VitalsTimeline records={vitals} />
            <VitalsChart records={vitals} />
            {activeAction === "vitals" ? (
              <AddVitalsForm
                patientId={occupant.patient_id}
                admissionId={occupant.admission_id}
                isSubmitting={isSubmittingVitals}
                onSubmit={async (data) => {
                  const ok = await submitVitals(data);
                  if (ok) {
                    setVitals(await getPatientVitals(occupant.patient_id));
                    setActiveAction(null);
                  }
                  return ok;
                }}
              />
            ) : null}
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Fluid balance</h2>
                <p className="text-sm text-muted-foreground">Running admission totals from recorded intake/output.</p>
              </div>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-2 text-sm"
                onClick={() => setActiveAction(activeAction === "fluid" ? null : "fluid")}
              >
                Add intake/output
              </button>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Metric label="Intake" value={fluidBalance?.total_intake_ml ?? 0} detail="mL" />
              <Metric label="Output" value={fluidBalance?.total_output_ml ?? 0} detail="mL" />
              <Metric label="Net" value={fluidBalance?.net_ml ?? 0} detail="mL" />
            </div>
            {activeAction === "fluid" ? (
              <AddIntakeOutputForm
                admissionId={occupant.admission_id}
                isSubmitting={isSubmittingFluid}
                onSubmit={async (data) => {
                  const ok = await submitIntakeOutput(data);
                  if (ok) {
                    setFluidBalance(await getAdmissionFluidBalance(occupant.admission_id));
                    setActiveAction(null);
                  }
                  return ok;
                }}
              />
            ) : null}
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">eMAR</h2>
                <p className="text-sm text-muted-foreground">Recorded doses for this admission only.</p>
              </div>
              <Link href="/nurse/emar" className="text-sm underline">
                Open full eMAR
              </Link>
            </div>
            <EMARTable medications={medications} />
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Movement history</h2>
                <p className="text-sm text-muted-foreground">Audited ward and bed changes for this admission.</p>
              </div>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-2 text-sm"
                onClick={() => setActiveAction(activeAction === "transfer" ? null : "transfer")}
              >
                Transfer patient
              </button>
            </div>
            <div className="surface-card p-5">
              {summary?.movements.length ? (
                <ol className="space-y-3 text-sm">
                  {summary.movements.map((movement) => (
                    <li key={movement.id} className="border-b border-border pb-3 last:border-none last:pb-0">
                      <strong>{wardName(movement.to_ward_id)} · Bed {bedName(movement.to_bed_id)}</strong>
                      <span className="ml-2 text-muted-foreground">{formatDateTime(movement.moved_at)}</span>
                      {movement.from_ward_id ? (
                        <span className="mt-1 block text-muted-foreground">
                          From {wardName(movement.from_ward_id)} · Bed {bedName(movement.from_bed_id)}
                        </span>
                      ) : null}
                      {movement.reason ? <span className="mt-1 block">{movement.reason}</span> : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">No transfers recorded for this admission.</p>
              )}
            </div>
            {activeAction === "transfer" ? (
              <AddPatientMovementForm
                admissionId={occupant.admission_id}
                wards={wards ?? []}
                beds={allBeds}
                isSubmitting={isSubmittingTransfer}
                onSubmit={async (data) => {
                  const ok = await submitPatientMovement(data);
                  if (ok) {
                    setSelectedBedId(null);
                    setActiveAction(null);
                    await loadBase();
                  }
                  return ok;
                }}
              />
            ) : null}
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Shift handover (SBAR)</h2>
                <p className="text-sm text-muted-foreground">
                  Disabled until FastAPI publishes handover-notes read/write contracts.
                </p>
              </div>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-2 text-sm"
                onClick={() => setActiveAction(activeAction === "handover" ? null : "handover")}
              >
                View handover form
              </button>
            </div>
            <HandoverNotes admissionId={occupant.admission_id} notes={handoverNotes} />
            {activeAction === "handover" ? (
              <AddHandoverForm
                admissionId={occupant.admission_id}
                recipientOptions={handoverRecipients}
                isSubmitting={isSubmittingHandover}
                onSubmit={submitHandover}
              />
            ) : null}
          </section>

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Clinical incident</h2>
                <p className="text-sm text-muted-foreground">
                  File against this patient/admission on `clinical_incidents` (0046).
                </p>
              </div>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-2 text-sm"
                onClick={() => setActiveAction(activeAction === "incident" ? null : "incident")}
              >
                Report incident
              </button>
            </div>
            <IncidentListPanel
              incidents={incidents}
              loading={incidentsLoading}
              error={incidentsError}
            />
            {activeAction === "incident" ? (
              <IncidentReportForm
                patientId={occupant.patient_id}
                admissionId={occupant.admission_id}
                wardId={selectedWard || undefined}
                onSuccess={() => {
                  setActiveAction(null);
                  void refreshIncidents();
                }}
              />
            ) : null}
          </section>

          <section className="space-y-4">
            <h2 className="text-xl font-semibold">Outstanding orders for this patient</h2>
            <TaskQueue orders={patientOrders} onAccept={acceptOrder} onCheckOff={checkOff} />
          </section>
        </>
      )}
    </main>
  );
}
