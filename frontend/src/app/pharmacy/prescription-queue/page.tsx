"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { ApiError, formatDateTime } from "@/lib/api";
import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { PageHeading } from "@/components/common/PageHeading";
import { listPrescriptionQueue } from "@/features/pharmacy/api";
import type { PrescriptionQueueItem } from "@/features/pharmacy/types";

/**
 * Pharmacy prescription queue (#175).
 *
 * Wrapped in ModuleCapabilityGate: pharmacy is one of the five toggleable
 * modules (facility_modules), and a facility without a pharmacy should be told
 * the module is off, not shown an empty queue that reads as "no work today".
 */
function StatusChip({ status }: { status: string | null }) {
  // null is not "unknown" — it means nothing has been dispensed against this
  // prescription yet, which is precisely the queue's reason to exist.
  const label = status ?? "awaiting dispense";
  const tone =
    status === null
      ? "bg-info-muted text-info"
      : status === "completed"
        ? "bg-success-muted text-success"
        : "bg-warning-muted text-warning";
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ${tone}`}>
      {label.replaceAll("_", " ")}
    </span>
  );
}

function Queue() {
  const [items, setItems] = useState<PrescriptionQueueItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await listPrescriptionQueue();
      setItems(response.items);
      setTotal(response.total);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "Could not load the prescription queue",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between gap-4">
        <PageHeading titleKey="pharmacy.queueTitle" />
        <button type="button" onClick={() => void load()} className="text-sm underline">
          Refresh
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {items && items.length === 0 && (
        <div className="surface-card p-6">
          <p className="text-sm text-muted-foreground">Nothing waiting to be dispensed.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="surface-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse">
              <thead className="bg-muted">
                <tr>
                  <th className="px-4 py-3 text-left">UHID</th>
                  <th className="px-4 py-3 text-left">Patient</th>
                  <th className="px-4 py-3 text-left">Items</th>
                  <th className="px-4 py-3 text-left">Prescribed</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.prescription_id}
                    className="border-b border-border last:border-none"
                  >
                    <td className="px-4 py-3 font-mono text-sm">
                      {item.uhid ?? item.thid ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-medium">{item.patient_full_name}</td>
                    <td className="px-4 py-3 text-sm">{item.item_count}</td>
                    <td className="px-4 py-3 text-sm">
                      {formatDateTime(item.prescribed_at)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusChip status={item.dispense_status} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/pharmacy/dispense?prescription=${item.prescription_id}`}
                        className="text-sm underline"
                      >
                        Dispense
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <Queue />
    </ModuleCapabilityGate>
  );
}
