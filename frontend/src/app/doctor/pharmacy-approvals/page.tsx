"use client";

import { useCallback, useEffect, useState } from "react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { PageHeading } from "@/components/common/PageHeading";
import { useLocale } from "@/lib/i18n";
import {
  decideSubstitution,
  listPendingSubstitutions,
} from "@/features/pharmacy/api";
import type { PendingSubstitution } from "@/features/pharmacy/types";
import { ApiError, formatDateTime } from "@/lib/api";

function Approvals() {
  const { t } = useLocale();
  const [items, setItems] = useState<PendingSubstitution[] | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await listPendingSubstitutions();
      setItems(response.items);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("doctor.pharmacyApprovals.errLoad"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(item: PendingSubstitution, approved: boolean) {
    const rejectionReason = reasons[item.item_id]?.trim();
    if (!approved && !rejectionReason) {
      setError("Enter a rejection reason before rejecting the substitution.");
      return;
    }
    setBusyId(item.item_id);
    setError(null);
    setMessage(null);
    try {
      const result = await decideSubstitution(item.item_id, approved, rejectionReason);
      setItems((current) => current?.filter((entry) => entry.item_id !== item.item_id) ?? []);
      setMessage(
        approved
          ? `Approved ${item.substitute_medicine_name}; ${result.quantity_dispensed} issued by FEFO.`
          : `Rejected substitution for ${item.patient_full_name}.`,
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Decision could not be saved");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <PageHeading titleKey="doctor.pharmacyApprovalsTitle" />
        <button type="button" className="text-sm underline" onClick={() => void load()}>
          {t("common.refresh")}
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">
          {message}
        </p>
      ) : null}

      {items === null ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : null}
      {items?.length === 0 ? (
        <section className="surface-card p-6 text-sm text-muted-foreground">
          {t("doctor.pharmacyApprovals.noPending")}
        </section>
      ) : null}

      <div className="space-y-4">
        {items?.map((item) => (
          <article key={item.item_id} className="surface-card space-y-4 p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="font-medium">{item.patient_full_name}</h2>
                <p className="text-sm text-muted-foreground">
                  {item.uhid ?? item.patient_id} · requested {formatDateTime(item.requested_at)}
                </p>
              </div>
              <span className="rounded-full bg-warning-muted px-3 py-1 text-xs font-medium text-warning">
                Pending · quantity {item.quantity_requested}
              </span>
            </div>

            <dl className="grid gap-3 text-sm md:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Prescribed</dt>
                <dd className="font-medium">{item.prescribed_medicine_name}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Requested substitute</dt>
                <dd className="font-medium">
                  {item.substitute_medicine_name}
                  {item.substitute_strength ? ` ${item.substitute_strength}` : ""}
                  {item.substitute_form ? ` · ${item.substitute_form}` : ""}
                </dd>
              </div>
              <div className="md:col-span-2">
                <dt className="text-muted-foreground">Pharmacist reason</dt>
                <dd>{item.substitute_reason}</dd>
              </div>
            </dl>

            <label className="block space-y-1 text-sm">
              <span className="text-muted-foreground">Rejection reason (required only to reject)</span>
              <textarea
                className="min-h-20 w-full rounded-md border border-border px-3 py-2"
                value={reasons[item.item_id] ?? ""}
                onChange={(event) =>
                  setReasons((current) => ({ ...current, [item.item_id]: event.target.value }))
                }
              />
            </label>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                disabled={busyId === item.item_id}
                onClick={() => void decide(item, true)}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busyId === item.item_id ? "Saving…" : "Approve and issue stock"}
              </button>
              <button
                type="button"
                disabled={busyId === item.item_id}
                onClick={() => void decide(item, false)}
                className="rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger disabled:opacity-50"
              >
                Reject
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <Approvals />
    </ModuleCapabilityGate>
  );
}
