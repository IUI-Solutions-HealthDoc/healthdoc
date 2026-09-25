"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { PageHeading } from "@/components/common/PageHeading";
import {
  createDispense,
  getPrescription,
  searchMedicines,
} from "@/features/pharmacy/api";
import { ExpiryTracker } from "@/features/pharmacy/ExpiryTracker";
import type {
  DispenseInput,
  DispenseResult,
  MedicineSearchResult,
  PrescriptionDetail,
  PrescriptionItem,
} from "@/features/pharmacy/types";
import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface LineDraft {
  quantity: string;
  manualBatch: boolean;
  batchId: string;
  substitute: boolean;
  substituteTerm: string;
  substituteItemId: string;
  substituteReason: string;
  allergyOverrideReason: string;
  interactionOverrideReason: string;
}

const emptyLine = (): LineDraft => ({
  quantity: "",
  manualBatch: false,
  batchId: "",
  substitute: false,
  substituteTerm: "",
  substituteItemId: "",
  substituteReason: "",
  allergyOverrideReason: "",
  interactionOverrideReason: "",
});

function MedicineLabel({
  medicine,
  availableLabel,
}: {
  medicine: MedicineSearchResult;
  availableLabel: string;
}) {
  return (
    <>
      {medicine.name}
      {medicine.strength ? ` ${medicine.strength}` : ""}
      {medicine.form ? ` · ${medicine.form}` : ""}
      {` (${medicine.total_available_quantity} ${availableLabel})`}
    </>
  );
}

function DispenseLine({
  item,
  draft,
  onChange,
}: {
  item: PrescriptionItem;
  draft: LineDraft;
  onChange: (patch: Partial<LineDraft>) => void;
}) {
  const { t } = useLocale();
  const [prescribedStock, setPrescribedStock] = useState<MedicineSearchResult | null>(null);
  const [stockLoading, setStockLoading] = useState(false);
  const [substitutes, setSubstitutes] = useState<MedicineSearchResult[]>([]);

  useEffect(() => {
    if (!item.medicine_item_id) return;
    let cancelled = false;
    setStockLoading(true);
    searchMedicines(item.medicine_name)
      .then((response) => {
        if (!cancelled) {
          setPrescribedStock(
            response.items.find((candidate) => candidate.item_id === item.medicine_item_id) ?? null,
          );
        }
      })
      .catch(() => {
        if (!cancelled) setPrescribedStock(null);
      })
      .finally(() => {
        if (!cancelled) setStockLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.medicine_item_id, item.medicine_name]);

  useEffect(() => {
    const term = draft.substituteTerm.trim();
    if (!draft.substitute || term.length < 2) {
      setSubstitutes([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      searchMedicines(term)
        .then((response) => {
          if (!cancelled) {
            setSubstitutes(
              response.items.filter((candidate) => candidate.item_id !== item.medicine_item_id),
            );
          }
        })
        .catch(() => {
          if (!cancelled) setSubstitutes([]);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [draft.substitute, draft.substituteTerm, item.medicine_item_id]);

  return (
    <fieldset className="surface-card space-y-4 p-5" disabled={!item.medicine_item_id}>
      <legend className="px-1 font-medium">
        {item.medicine_name}
        {item.dosage ? ` · ${item.dosage}` : ""}
      </legend>
      <p className="text-sm text-muted-foreground">
        {[
          item.frequency,
          item.duration_days ? t("pharmacy.dispense.daysUnit", { count: item.duration_days }) : null,
          item.route,
        ]
          .filter(Boolean)
          .join(" · ") || t("pharmacy.dispense.noDosingDetails")}
        {item.instructions ? ` — ${item.instructions}` : ""}
      </p>

      {!item.medicine_item_id && (
        <p role="alert" className="text-sm text-danger">
          {t("pharmacy.dispense.notLinked")}
        </p>
      )}

      <label className="block max-w-xs space-y-1 text-sm">
        <span className="text-muted-foreground">{t("pharmacy.dispense.quantityLabel")}</span>
        <input
          type="number"
          min="0"
          step="0.01"
          className="w-full rounded-md border border-border px-3 py-2"
          value={draft.quantity}
          onChange={(event) => onChange({ quantity: event.target.value })}
          placeholder={t("pharmacy.dispense.quantityPlaceholder")}
        />
      </label>
      <p className="text-xs text-muted-foreground">{t("pharmacy.dispense.quantityHint")}</p>

      <div className="flex flex-wrap gap-5 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.manualBatch}
            disabled={draft.substitute}
            onChange={(event) => onChange({ manualBatch: event.target.checked, batchId: "" })}
          />
          {t("pharmacy.dispense.pinBatch")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.substitute}
            onChange={(event) =>
              onChange({
                substitute: event.target.checked,
                manualBatch: false,
                batchId: "",
                substituteItemId: "",
              })
            }
          />
          {t("pharmacy.dispense.requestSubstitute")}
        </label>
      </div>

      {!draft.substitute && (
        <div className="rounded-md border border-border p-3 text-sm">
          {stockLoading ? (
            <p className="text-muted-foreground">{t("pharmacy.dispense.checkingStock")}</p>
          ) : prescribedStock ? (
            <>
              <p>
                {t("pharmacy.dispense.liveStock")}{" "}
                <MedicineLabel
                  medicine={prescribedStock}
                  availableLabel={t("pharmacy.dispense.availableSuffix")}
                />
              </p>
              {draft.manualBatch ? (
                <label className="mt-3 block space-y-1">
                  <span className="text-muted-foreground">{t("pharmacy.dispense.batchFefo")}</span>
                  <select
                    className="w-full rounded-md border border-border px-3 py-2"
                    value={draft.batchId}
                    onChange={(event) => onChange({ batchId: event.target.value })}
                  >
                    <option value="">{t("pharmacy.dispense.selectBatch")}</option>
                    {prescribedStock.batches.map((batch) => (
                      <option key={batch.batch_id} value={batch.batch_id}>
                        {batch.batch_number} · exp {batch.expiry_date} · {batch.quantity} available
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <p className="mt-2 text-muted-foreground">{t("pharmacy.dispense.fefoHint")}</p>
              )}
            </>
          ) : (
            <p className="text-warning">{t("pharmacy.dispense.noStockFound")}</p>
          )}
        </div>
      )}

      {draft.substitute && (
        <div className="space-y-3 rounded-md border border-warning bg-warning-muted p-4 text-sm">
          <p className="font-medium">{t("pharmacy.dispense.substituteApproval")}</p>
          <label className="block space-y-1">
            <span>{t("pharmacy.dispense.searchSubstitute")}</span>
            <input
              className="w-full rounded-md border border-border bg-white px-3 py-2"
              value={draft.substituteTerm}
              onChange={(event) =>
                onChange({ substituteTerm: event.target.value, substituteItemId: "" })
              }
              placeholder={t("pharmacy.dispense.substituteMinChars")}
            />
          </label>
          {substitutes.length > 0 && (
            <label className="block space-y-1">
              <span>{t("pharmacy.dispense.substituteLabel")}</span>
              <select
                className="w-full rounded-md border border-border bg-white px-3 py-2"
                value={draft.substituteItemId}
                onChange={(event) => onChange({ substituteItemId: event.target.value })}
              >
                <option value="">{t("pharmacy.dispense.selectMedicine")}</option>
                {substitutes.map((medicine) => (
                  <option key={medicine.item_id} value={medicine.item_id}>
                    {medicine.name} {medicine.strength ?? ""} · {medicine.total_available_quantity}{" "}
                    {t("pharmacy.dispense.availableSuffix")}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block space-y-1">
            <span>{t("pharmacy.dispense.substituteReason")}</span>
            <textarea
              className="min-h-20 w-full rounded-md border border-border bg-white px-3 py-2"
              value={draft.substituteReason}
              onChange={(event) => onChange({ substituteReason: event.target.value })}
              placeholder={t("pharmacy.dispense.substituteReasonPlaceholder")}
            />
          </label>
        </div>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">
          {t("pharmacy.dispense.overrideSummary")}
        </summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-muted-foreground">{t("pharmacy.dispense.allergyOverride")}</span>
            <textarea
              className="min-h-20 w-full rounded-md border border-border px-3 py-2"
              value={draft.allergyOverrideReason}
              onChange={(event) => onChange({ allergyOverrideReason: event.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-muted-foreground">
              {t("pharmacy.dispense.interactionOverride")}
            </span>
            <textarea
              className="min-h-20 w-full rounded-md border border-border px-3 py-2"
              value={draft.interactionOverrideReason}
              onChange={(event) => onChange({ interactionOverrideReason: event.target.value })}
            />
          </label>
        </div>
      </details>
    </fieldset>
  );
}

function ResultCard({ result }: { result: DispenseResult }) {
  const { t } = useLocale();
  return (
    <section className="surface-card space-y-3 border border-success p-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium">{t("pharmacy.dispense.recordedTitle")}</h2>
        <span className="rounded-full bg-success-muted px-3 py-1 text-sm text-success">
          {result.status.replaceAll("_", " ")}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {t("pharmacy.dispense.versionAt", {
          version: result.version,
          datetime: formatDateTime(result.created_at),
        })}
      </p>
      <ul className="space-y-2 text-sm">
        {result.items.map((item) => (
          <li key={item.prescription_item_id} className="rounded-md border border-border p-3">
            {t("pharmacy.dispense.requestedDispensed", {
              requested: item.quantity_prescribed ?? "—",
              dispensed: item.quantity_dispensed,
            })}
            {item.approval_status === "pending" ? (
              <strong className="ml-2 text-warning">
                {t("pharmacy.dispense.pendingDoctorApproval")}
              </strong>
            ) : null}
            {item.batches.length > 0 ? (
              <span className="mt-1 block text-muted-foreground">
                {item.batches
                  .map((batch) => `${batch.batch_number}: ${batch.quantity_from_batch}`)
                  .join(" · ")}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Dispense() {
  const { t } = useLocale();
  const prescriptionId = useSearchParams().get("prescription") ?? "";
  const [prescription, setPrescription] = useState<PrescriptionDetail | null>(null);
  const [drafts, setDrafts] = useState<Record<string, LineDraft>>({});
  const [allowPartial, setAllowPartial] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [result, setResult] = useState<DispenseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setIdempotencyKey(newIdempotencyKey());
  }, []);

  const load = useCallback(async () => {
    if (!prescriptionId) return;
    setLoading(true);
    try {
      const response = await getPrescription(prescriptionId);
      setPrescription(response);
      setDrafts(Object.fromEntries(response.items.map((item) => [item.id, emptyLine()])));
      setResult(null);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load prescription");
    } finally {
      setLoading(false);
    }
  }, [prescriptionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedCount = useMemo(
    () => Object.values(drafts).filter((draft) => Number(draft.quantity) > 0).length,
    [drafts],
  );

  function updateDraft(itemId: string, patch: Partial<LineDraft>) {
    setDrafts((current) => ({
      ...current,
      [itemId]: { ...(current[itemId] ?? emptyLine()), ...patch },
    }));
  }

  async function submit() {
    if (!prescription || !idempotencyKey) return;
    const items: DispenseInput["items"] = [];
    for (const item of prescription.items) {
      const draft = drafts[item.id];
      if (!draft || Number(draft.quantity) <= 0) continue;
      if (draft.manualBatch && !draft.batchId) {
        setError(`Select a batch for ${item.medicine_name}.`);
        return;
      }
      if (draft.substitute && (!draft.substituteItemId || !draft.substituteReason.trim())) {
        setError(`Select a substitute and enter a reason for ${item.medicine_name}.`);
        return;
      }
      items.push({
        prescription_item_id: item.id,
        quantity_dispensed: draft.quantity,
        ...(draft.manualBatch ? { batch_id: draft.batchId } : {}),
        ...(draft.substitute
          ? {
              substitute_item_id: draft.substituteItemId,
              substitute_reason: draft.substituteReason.trim(),
            }
          : {}),
        ...(draft.allergyOverrideReason.trim()
          ? { allergy_override_reason: draft.allergyOverrideReason.trim() }
          : {}),
        ...(draft.interactionOverrideReason.trim()
          ? { interaction_override_reason: draft.interactionOverrideReason.trim() }
          : {}),
      });
    }
    if (items.length === 0) {
      setError("Enter a quantity for at least one prescription item.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const response = await createDispense(
        { prescription_id: prescription.id, items, allow_partial: allowPartial },
        idempotencyKey,
      );
      setResult(response);
      setIdempotencyKey(newIdempotencyKey());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Dispense could not be recorded");
    } finally {
      setSubmitting(false);
    }
  }

  if (!prescriptionId) {
    return (
      <div className="space-y-8">
        <section className="surface-card p-6">
          <PageHeading titleKey="pharmacy.dispenseTitle" />
          <p className="mt-2 text-sm text-muted-foreground">
            {t("pharmacy.dispenseSelectPrescription")}
          </p>
          <Link href="/pharmacy/prescription-queue" className="mt-4 inline-block underline">
            {t("pharmacy.openPrescriptionQueue")}
          </Link>
        </section>
        <section className="space-y-4">
          <h2 className="text-lg font-medium">{t("pharmacy.expiryTracker")}</h2>
          <ExpiryTracker />
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeading titleKey="pharmacy.dispenseTitle" />
        <Link href="/pharmacy/prescription-queue" className="text-sm underline">
          {t("pharmacy.backToQueue")}
        </Link>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      )}

      {prescription && (
        <>
          <section className="surface-card p-4 text-sm">
            <p>
              <span className="text-muted-foreground">{t("pharmacy.dispense.patientId")}</span>{" "}
              <span className="font-mono">{prescription.patient_id}</span>
            </p>
            {prescription.notes ? (
              <p className="mt-2">
                {t("pharmacy.dispense.notes")} {prescription.notes}
              </p>
            ) : null}
          </section>

          <div className="space-y-4">
            {prescription.items.map((item) => (
              <DispenseLine
                key={item.id}
                item={item}
                draft={drafts[item.id] ?? emptyLine()}
                onChange={(patch) => updateDraft(item.id, patch)}
              />
            ))}
          </div>

          <section className="surface-card space-y-4 p-5">
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={allowPartial}
                onChange={(event) => setAllowPartial(event.target.checked)}
              />
              <span>
                <strong>{t("pharmacy.dispense.allowPartial")}</strong>
                <span className="mt-1 block text-muted-foreground">
                  {t("pharmacy.dispense.allowPartialHint")}
                </span>
              </span>
            </label>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={submitting || selectedCount === 0 || Boolean(result)}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {submitting
                ? t("pharmacy.recording")
                : selectedCount === 1
                  ? t("pharmacy.recordDispenseOne")
                  : t("pharmacy.recordDispenseMany", { count: selectedCount })}
            </button>
          </section>
        </>
      )}

      {result ? <ResultCard result={result} /> : null}
    </div>
  );
}

function DispenseLoadingFallback() {
  const { t } = useLocale();
  return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
}

export default function Page() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <Suspense fallback={<DispenseLoadingFallback />}>
        <Dispense />
      </Suspense>
    </ModuleCapabilityGate>
  );
}
