"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle, X } from "lucide-react";
import { recordImmunization } from "../api";
import { useClinicalWrite } from "@/lib/useClinicalWrite";
import { useLocale } from "@/lib/i18n";
import type { Vaccine } from "../types";

interface RecordImmunizationModalProps {
  isOpen: boolean;
  onClose: () => void;
  patientId: string;
  catalogue: Vaccine[];
  onSuccess: () => void;
}

export function RecordImmunizationModal({
  isOpen,
  onClose,
  patientId,
  catalogue,
  onSuccess,
}: RecordImmunizationModalProps) {
  const { t } = useLocale();
  const [selectedVaccineId, setSelectedVaccineId] = useState<string>(
    catalogue[0]?.id || ""
  );
  const [doseNumber, setDoseNumber] = useState<number>(1);
  const [administeredDate, setAdministeredDate] = useState<string>(
    () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  );
  const [batchNumber, setBatchNumber] = useState<string>("");
  const [expiryDate, setExpiryDate] = useState<string>("");
  const [manufacturer, setManufacturer] = useState<string>("");
  const [site, setSite] = useState<string>(catalogue[0]?.site || "");
  const [route, setRoute] = useState<string>(catalogue[0]?.route || "");
  const [adverseReaction, setAdverseReaction] = useState<string>("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const write = useClinicalWrite();

  if (!isOpen) return null;

  const handleVaccineChange = (vaccineId: string) => {
    setSelectedVaccineId(vaccineId);
    const v = catalogue.find((item) => item.id === vaccineId);
    if (v) {
      setDoseNumber(1);
      if (v.route) setRoute(v.route);
      if (v.site) setSite(v.site);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || !write.isCurrent()) return;
    setError(null);

    if (!catalogue.some((v) => v.id === selectedVaccineId)) {
      setError(t("immunization.record.errSelectVaccine"));
      return;
    }
    if (!expiryDate || expiryDate < administeredDate.slice(0, 10)) {
      setError(t("immunization.record.errExpiry"));
      return;
    }
    if (!batchNumber.trim()) {
      setError(t("immunization.record.errBatch"));
      return;
    }

    try {
      setIsSubmitting(true);
      await write.run({
        patient_id: patientId,
        vaccine_code: catalogue.find((v) => v.id === selectedVaccineId)!.code,
        dose_number: doseNumber,
        administered_at: new Date(administeredDate).toISOString(),
        batch_number: batchNumber.trim(),
        expiry_date: expiryDate,
        manufacturer: manufacturer.trim() || null,
        site: site.trim() || null,
        route: route.trim() || null,
        adverse_reaction: adverseReaction.trim() || null,
      }, recordImmunization);
      if (!write.isCurrent()) return;
      onSuccess();
      onClose();
    } catch (err: unknown) {
      if (write.isCurrent()) {
        setError(err instanceof Error ? err.message : t("immunization.record.errFailed"));
      }
    } finally {
      if (write.isCurrent()) setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <div>
            <h3 className="text-lg font-bold text-card-foreground">{t("immunization.record.title")}</h3>
            <p className="text-xs text-muted-foreground">{t("immunization.record.subtitle")}</p>
          </div>
          <button
            onClick={onClose}
            disabled={isSubmitting || write.retryPending}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            aria-label={t("common.close")}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <fieldset disabled={isSubmitting || write.retryPending} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              {t("immunization.record.vaccine")}
            </label>
            <select
              value={selectedVaccineId}
              onChange={(e) => handleVaccineChange(e.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              {catalogue.map((v) => (
                <option key={v.id} value={v.id}>
                  {t("immunization.record.vaccineOption", {
                    name: v.name,
                    code: v.code,
                    doses: v.standard_doses,
                  })}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.doseNumber")}
              </label>
              <input
                type="number"
                min="1"
                max="10"
                value={doseNumber}
                onChange={(e) => setDoseNumber(parseInt(e.target.value) || 1)}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.dateAdministered")}
              </label>
              <input
                type="datetime-local"
                value={administeredDate}
                onChange={(e) => setAdministeredDate(e.target.value)}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.batchLot")}
              </label>
              <input
                type="text"
                placeholder={t("immunization.record.batchPlaceholder")}
                value={batchNumber}
                onChange={(e) => setBatchNumber(e.target.value)}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.expiryDate")}
              </label>
              <input
                type="date"
                required
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.route")}
              </label>
              <input
                type="text"
                value={route}
                onChange={(e) => setRoute(e.target.value)}
                placeholder={t("immunization.record.routePlaceholder")}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                {t("immunization.record.anatomicalSite")}
              </label>
              <input
                type="text"
                value={site}
                onChange={(e) => setSite(e.target.value)}
                placeholder={t("immunization.record.sitePlaceholder")}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              {t("immunization.record.manufacturer")}
            </label>
            <input
              type="text"
              placeholder={t("immunization.record.manufacturerPlaceholder")}
              value={manufacturer}
              onChange={(e) => setManufacturer(e.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
              {t("immunization.record.adverseReactions")}
            </label>
            <textarea
              rows={2}
              placeholder={t("immunization.record.adversePlaceholder")}
              value={adverseReaction}
              onChange={(e) => setAdverseReaction(e.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          </fieldset>
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting || write.retryPending}
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              <CheckCircle className="h-4 w-4" />
              {isSubmitting
                ? t("immunization.record.recording")
                : write.retryPending
                  ? t("forms.renderer.retrySave")
                  : t("immunization.record.saveRecord")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
