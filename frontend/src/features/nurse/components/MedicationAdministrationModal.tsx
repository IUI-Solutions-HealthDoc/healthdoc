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
                ? t("nurse.ui.submitsAnAuditedCorrectionLinkedTo")
                : t("nurse.ui.recordGivenHeldOrRefusedDose")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={t("patientPortal.documents.modal.closeAria")}
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
            <strong>{t("nurse.ui.correctingPriorRecord")}</strong> {correctionRecord?.medicine_name ?? t("nurse.actionMedication")}{" "}{t("nurse.ui.id")}{" "}{correctionRecord?.id})
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4 text-sm">
          {!isCorrection && prescriptionItems.length > 0 ? (
            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("nurse.ui.prescriptionItem")}</span>
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
              <span className="font-medium text-foreground">{t("nurse.ui.prescriptionItemId")}</span>
              <input
                type="text"
                required
                className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-foreground"
                placeholder={t("nurse.ui.uuidOfPrescriptionItem")}
                value={prescriptionItemId}
                onChange={(e) => setPrescriptionItemId(e.target.value)}
              />
            </label>
          ) : null}

          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("nurse.ui.administrationStatus")}</span>
              <select
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={status}
                onChange={(e) => setStatus(e.target.value as MedicationStatus)}
                required
              >
                <option value="given">{t("nurse.ui.given")}</option>
                <option value="held">{t("nurse.ui.held")}</option>
                <option value="refused">{t("nurse.ui.refused")}</option>
              </select>
            </label>

            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("immunization.col.route")}</span>
              <select
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                value={route}
                onChange={(e) => setRoute(e.target.value)}
              >
                <option value="oral">{t("nurse.ui.oral")}</option>
                <option value="IV">{t("nurse.ui.intravenousIv")}</option>
                <option value="IM">{t("nurse.ui.intramuscularIm")}</option>
                <option value="subcutaneous">{t("nurse.ui.subcutaneousSc")}</option>
                <option value="topical">{t("nurse.ui.topical")}</option>
                <option value="inhalation">{t("nurse.ui.inhalation")}</option>
                <option value="rectal">{t("nurse.ui.rectal")}</option>
                <option value="sublingual">{t("nurse.ui.sublingual")}</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("nurse.ui.doseGivenPrepared")}</span>
              <input
                type="text"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                placeholder={t("nurse.ui.eG500Mg1Tab")}
                value={doseGiven}
                onChange={(e) => setDoseGiven(e.target.value)}
              />
            </label>

            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("nurse.ui.scheduledTimeOptional")}</span>
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
              <span className="font-medium text-danger">{t("nurse.ui.clinicalReasonFor")}{" "}{status === "held" ? t("nurse.ui.holding") : t("nurse.ui.refusing")}{" "}{t("nurse.ui.doseRequired")}</span>
              <input
                type="text"
                required
                className="w-full rounded-md border border-danger/50 bg-background px-3 py-2 text-foreground focus:border-danger"
                placeholder={t("nurse.ui.eGSystolicBp90Mmhg")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          )}

          {isCorrection && (
            <label className="block space-y-1">
              <span className="font-medium text-foreground">{t("nurse.ui.correctionReasonMandatoryMin10Characters")}</span>
              <textarea
                required
                rows={2}
                minLength={10}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                placeholder={t("nurse.ui.detailedReasonForAmendingTheOriginal")}
                value={correctionReason}
                onChange={(e) => setCorrectionReason(e.target.value)}
              />
              <span className="text-[11px] text-muted-foreground">{t("emergency.retriageMinChars", { count: correctionReason.length })}</span>
            </label>
          )}

          <label className="block space-y-1">
            <span className="font-medium text-foreground">{t("nurse.ui.notesOptional")}</span>
            <input
              type="text"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
              placeholder={t("nurse.ui.eGAdministeredAfterLightMeal")}
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
