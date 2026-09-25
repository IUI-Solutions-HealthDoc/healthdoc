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

function MedicineLabel({ medicine }: { medicine: MedicineSearchResult }) {
  return (
    <>
      {medicine.name}
      {medicine.strength ? ` ${medicine.strength}` : ""}
      {medicine.form ? ` · ${medicine.form}` : ""}
      {` (${medicine.total_available_quantity} available)`}
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
        {[item.frequency, item.duration_days ? `${item.duration_days} days` : null, item.route]
          .filter(Boolean)
          .join(" · ") || "No dosing details recorded"}
        {item.instructions ? ` — ${item.instructions}` : ""}
      </p>

      {!item.medicine_item_id && (
        <p role="alert" className="text-sm text-danger">
          This prescription line is not linked to an inventory medicine and cannot be dispensed.
        </p>
      )}

      <label className="block max-w-xs space-y-1 text-sm">
        <span className="text-muted-foreground">Quantity to dispense</span>
        <input
          type="number"
          min="0"
          step="0.01"
          className="w-full rounded-md border border-border px-3 py-2"
          value={draft.quantity}
          onChange={(event) => onChange({ quantity: event.target.value })}
          placeholder="Enter quantity"
        />
      </label>
      <p className="text-xs text-muted-foreground">
        The prescription stores dose and duration, but no calculated issue quantity. Confirm the
        authorized quantity before submitting.
      </p>

      <div className="flex flex-wrap gap-5 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.manualBatch}
            disabled={draft.substitute}
            onChange={(event) => onChange({ manualBatch: event.target.checked, batchId: "" })}
          />
          Pin a batch manually
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
          Request a substitute
        </label>
      </div>

      {!draft.substitute && (
        <div className="rounded-md border border-border p-3 text-sm">
          {stockLoading ? (
            <p className="text-muted-foreground">Checking live stock…</p>
          ) : prescribedStock ? (
            <>
              <p>
                Live stock: <MedicineLabel medicine={prescribedStock} />
              </p>
              {draft.manualBatch ? (
                <label className="mt-3 block space-y-1">
                  <span className="text-muted-foreground">Batch (server FEFO order)</span>
                  <select
                    className="w-full rounded-md border border-border px-3 py-2"
                    value={draft.batchId}
                    onChange={(event) => onChange({ batchId: event.target.value })}
                  >
                    <option value="">Select batch</option>
                    {prescribedStock.batches.map((batch) => (
                      <option key={batch.batch_id} value={batch.batch_id}>
                        {batch.batch_number} · exp {batch.expiry_date} · {batch.quantity} available
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <p className="mt-2 text-muted-foreground">
                  The server will allocate non-expired stock across batches using FEFO.
                </p>
              )}
            </>
          ) : (
            <p className="text-warning">No live stock was found for this inventory item.</p>
          )}
        </div>
      )}

      {draft.substitute && (
        <div className="space-y-3 rounded-md border border-warning bg-warning-muted p-4 text-sm">
          <p className="font-medium">Doctor approval is required before substitute stock moves.</p>
          <label className="block space-y-1">
            <span>Search substitute medicine</span>
            <input
              className="w-full rounded-md border border-border bg-white px-3 py-2"
              value={draft.substituteTerm}
              onChange={(event) =>
                onChange({ substituteTerm: event.target.value, substituteItemId: "" })
              }
              placeholder="At least two characters"
            />
          </label>
          {substitutes.length > 0 && (
            <label className="block space-y-1">
              <span>Substitute</span>
              <select
                className="w-full rounded-md border border-border bg-white px-3 py-2"
                value={draft.substituteItemId}
                onChange={(event) => onChange({ substituteItemId: event.target.value })}
              >
                <option value="">Select medicine</option>
                {substitutes.map((medicine) => (
                  <option key={medicine.item_id} value={medicine.item_id}>
                    {medicine.name} {medicine.strength ?? ""} · {medicine.total_available_quantity}
                    {" available"}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block space-y-1">
            <span>Clinical substitution reason</span>
            <textarea
              className="min-h-20 w-full rounded-md border border-border bg-white px-3 py-2"
              value={draft.substituteReason}
              onChange={(event) => onChange({ substituteReason: event.target.value })}
              placeholder="Required for the ordering doctor’s audit trail"
            />
          </label>
        </div>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">Clinical override reasons</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-muted-foreground">Allergy override (minimum 20 characters)</span>
            <textarea
              className="min-h-20 w-full rounded-md border border-border px-3 py-2"
              value={draft.allergyOverrideReason}
              onChange={(event) => onChange({ allergyOverrideReason: event.target.value })}
            />
          </label>
          <label className="space-y-1">
            <span className="text-muted-foreground">
              Interaction override (minimum 20 characters)
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
  return (
    <section className="surface-card space-y-3 border border-success p-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-medium">Dispense recorded</h2>
        <span className="rounded-full bg-success-muted px-3 py-1 text-sm text-success">
          {result.status.replaceAll("_", " ")}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        Version {result.version} · {formatDateTime(result.created_at)}
      </p>
      <ul className="space-y-2 text-sm">
        {result.items.map((item) => (
          <li key={item.prescription_item_id} className="rounded-md border border-border p-3">
            Requested {item.quantity_prescribed ?? "—"}; dispensed {item.quantity_dispensed}.
            {item.approval_status === "pending" ? (
              <strong className="ml-2 text-warning">Waiting for ordering-doctor approval.</strong>
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
            Open a live prescription from the queue before stock can be issued.
          </p>
          <Link href="/pharmacy/prescription-queue" className="mt-4 inline-block underline">
            Open prescription queue
          </Link>
        </section>
        <section className="space-y-4">
          <h2 className="text-lg font-medium">Expiry tracker</h2>
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
          Back to queue
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
              <span className="text-muted-foreground">Patient ID:</span>{" "}
              <span className="font-mono">{prescription.patient_id}</span>
            </p>
            {prescription.notes ? <p className="mt-2">Notes: {prescription.notes}</p> : null}
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
                <strong>Allow partial fulfillment.</strong>
                <span className="mt-1 block text-muted-foreground">
                  If stock is short, issue available quantities and record the remainder as partial.
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
                ? "Recording…"
                : `Record dispense (${selectedCount} item${selectedCount === 1 ? "" : "s"})`}
            </button>
          </section>
        </>
      )}

      {result ? <ResultCard result={result} /> : null}
    </div>
  );
}

export default function Page() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <Dispense />
      </Suspense>
    </ModuleCapabilityGate>
  );
}
