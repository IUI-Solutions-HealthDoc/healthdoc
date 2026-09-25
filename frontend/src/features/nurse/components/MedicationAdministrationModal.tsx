"use client";

import { useEffect, useState } from "react";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { MedicationRecord, MedicationStatus } from "@/components/tables/EMARTable";

export interface PrescriptionOption {
  id: string;
  medicine_name: string;
  dosage: string;
  route: string;
  priority?: string;
  status: string;
}

interface MedicationAdministrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  admissionId: string;
  patientId: string;
  prescriptionItems?: PrescriptionOption[];
  correctionRecord?: MedicationRecord | null;
}

export default function MedicationAdministrationModal({
  isOpen,
  onClose,
  onSuccess,
  admissionId,
  patientId,
  prescriptionItems = [],
  correctionRecord = null,
}: MedicationAdministrationModalProps) {
  const { t } = useLocale();
  const isCorrection = Boolean(correctionRecord);

  const [prescriptionItemId, setPrescriptionItemId] = useState<string>("");
  const [status, setStatus] = useState<MedicationStatus>("given");
  const [doseGiven, setDoseGiven] = useState<string>("");
  const [route, setRoute] = useState<string>("oral");
  const [scheduledAt, setScheduledAt] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [correctionReason, setCorrectionReason] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize or prefill state when opened
  useEffect(() => {
    if (!isOpen) return;

    setError(null);
    if (correctionRecord) {
      setPrescriptionItemId(correctionRecord.prescription_item_id);
      setStatus(correctionRecord.status);
      setDoseGiven(correctionRecord.dose_given ?? correctionRecord.dosage ?? "");
      setRoute(correctionRecord.route ?? "oral");
      setScheduledAt(
        correctionRecord.scheduled_at
          ? new Date(correctionRecord.scheduled_at).toISOString().slice(0, 16)
          : ""
      );
      setReason(correctionRecord.reason ?? "");
      setCorrectionReason("");
      setNotes(correctionRecord.notes ?? "");
    } else {
      const firstActive = prescriptionItems.find((p) => p.status !== "stopped");
      setPrescriptionItemId(firstActive?.id ?? prescriptionItems[0]?.id ?? "");
      setStatus("given");
      setDoseGiven(firstActive?.dosage ?? "");
      setRoute(firstActive?.route ?? "oral");
      setScheduledAt("");
      setReason("");
      setCorrectionReason("");
      setNotes("");
    }
  }, [isOpen, correctionRecord, prescriptionItems]);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!prescriptionItemId) {
      setError("Please select a prescription item or medication.");
      return;
    }

    if ((status === "held" || status === "refused") && !reason.trim()) {
      setError(`A clinical reason is mandatory when medication is ${status}.`);
      return;
    }

    if (isCorrection && (!correctionReason.trim() || correctionReason.trim().length < 10)) {
      setError("Dose correction reason must be at least 10 characters long.");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        prescription_item_id: prescriptionItemId,
        admission_id: admissionId,
        patient_id: patientId,
        status,
        dose_given: doseGiven.trim() || null,
        route: route.trim() || null,
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
        reason: (status === "held" || status === "refused") ? reason.trim() : (reason.trim() || null),
        notes: notes.trim() || null,
        // Correction fields (HD-17)
        correction_of_id: isCorrection ? correctionRecord?.id : null,
        is_correction: isCorrection,
        correction_reason: isCorrection ? correctionReason.trim() : null,
      };

      await api("/nursing/medication-administrations", {
        method: "POST",
        body: JSON.stringify(payload),
        idempotencyKey: newIdempotencyKey(),
      });

      onSuccess();
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 409) {
          setError(`Cannot record dose: ${err.message}`);
        } else {
          setError(err.message);
        }
      } else {
        setError(err instanceof Error ? err.message : t("nurse.medicationModal.errRecord"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="surface-card max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-card p-6 shadow-xl">
        <div className="flex items-center justify-between border-b border-border pb-3">
          <div>
            <h2 className="text-lg font-semibold">
              {isCorrection
                ? t("nurse.medicationModal.correctTitle")
                : t("nurse.medicationModal.recordTitle")}
            </h2>
            <p className="text-xs text-muted-foreground">
              {isCorrection
                ? "Submits an audited correction linked to the original dose record."
                : "Record given, held, or refused dose on the eMAR sheet."}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close modal"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-md bg-danger/10 border border-danger/30 p-3 text-sm text-danger">
            {error}
          </div>
        )}

        {isCorrection && (
          <div className="mt-4 rounded-md bg-blue-500/10 border border-blue-500/30 p-3 text-xs text-blue-800 dark:text-blue-300">
            <strong>Correcting prior record:</strong> {correctionRecord?.medicine_name ?? "Medication"} (ID: {correctionRecord?.id})
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4 text-sm">
          {!isCorrection && prescriptionItems.length > 0 ? (
            <label className="block space-y-1">
              <span className="font-medium text-foreground">Prescription Item</span>
              <select
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={prescriptionItemId}
                onChange={(e) => {
                  const id = e.target.value;
                  setPrescriptionItemId(id);
                  const found = prescriptionItems.find((p) => p.id === id);
                  if (found) {
                    if (found.dosage) setDoseGiven(found.dosage);
                    if (found.route) setRoute(found.route);
                  }
                }}
                required
              >
                {prescriptionItems.map((item) => (
                  <option key={item.id} value={item.id} disabled={item.status === "stopped"}>
                    {item.priority && item.priority !== "routine" ? `[${item.priority.toUpperCase()}] ` : ""}
                    {item.medicine_name} — {item.dosage} ({item.route})
                    {item.status === "stopped" ? " (STOPPED)" : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : !isCorrection ? (
            <label className="block space-y-1">
              <span className="font-medium text-foreground">Prescription Item ID</span>
              <input
                type="text"
                required
                className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-foreground"
                placeholder="UUID of prescription item"
                value={prescriptionItemId}
                onChange={(e) => setPrescriptionItemId(e.target.value)}
              />
            </label>
          ) : null}

          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1">
              <span className="font-medium text-foreground">Administration Status</span>
              <select
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={status}
                onChange={(e) => setStatus(e.target.value as MedicationStatus)}
                required
              >
                <option value="given">Given</option>
                <option value="held">Held</option>
                <option value="refused">Refused</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="font-medium text-foreground">Route</span>
              <select
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={route}
                onChange={(e) => setRoute(e.target.value)}
              >
                <option value="oral">Oral</option>
                <option value="IV">Intravenous (IV)</option>
                <option value="IM">Intramuscular (IM)</option>
                <option value="subcutaneous">Subcutaneous (SC)</option>
                <option value="topical">Topical</option>
                <option value="inhalation">Inhalation</option>
                <option value="rectal">Rectal</option>
                <option value="sublingual">Sublingual</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1">
              <span className="font-medium text-foreground">Dose Given / Prepared</span>
              <input
                type="text"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                placeholder="e.g. 500 mg, 1 tab"
                value={doseGiven}
                onChange={(e) => setDoseGiven(e.target.value)}
              />
            </label>

            <label className="block space-y-1">
              <span className="font-medium text-foreground">Scheduled Time (optional)</span>
              <input
                type="datetime-local"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
              />
            </label>
          </div>

          {(status === "held" || status === "refused") && (
            <label className="block space-y-1">
              <span className="font-medium text-danger">
                Clinical Reason for {status === "held" ? "Holding" : "Refusing"} Dose (Required)
              </span>
              <input
                type="text"
                required
                className="w-full rounded-md border border-danger/50 bg-background px-3 py-2 text-foreground focus:border-danger"
                placeholder="e.g. Systolic BP < 90 mmHg, patient nauseous, pending surgery"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          )}

          {isCorrection && (
            <label className="block space-y-1">
              <span className="font-medium text-foreground">
                Correction Reason (Mandatory, min 10 characters)
              </span>
              <textarea
                required
                rows={2}
                minLength={10}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                placeholder="Detailed reason for amending the original dose administration entry..."
                value={correctionReason}
                onChange={(e) => setCorrectionReason(e.target.value)}
              />
              <span className="text-[11px] text-muted-foreground">
                {correctionReason.length}/10 minimum characters
              </span>
            </label>
          )}

          <label className="block space-y-1">
            <span className="font-medium text-foreground">Notes (Optional)</span>
            <input
              type="text"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
              placeholder="e.g. Administered after light meal, IV site clean"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          <div className="flex items-center justify-end gap-3 border-t border-border pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting
                ? t("nurse.medicationModal.recording")
                : isCorrection
                  ? t("nurse.medicationModal.correctionSubmit")
                  : t("nurse.medicationModal.recordSubmit")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
