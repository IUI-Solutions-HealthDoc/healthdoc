"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, formatDateTime } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/AsyncState";
import { useLocale, type MessageKey } from "@/lib/i18n";

interface PrescriptionQueueItem {
  prescription_id: string;
  patient_id: string;
  patient_full_name: string;
  uhid?: string | null;
  thid?: string | null;
  prescribed_at: string;
  item_count: number;
  dispense_status?: string | null;
}

interface PrescriptionQueueResponse {
  items: PrescriptionQueueItem[];
  total: number;
}

const QUEUE_COLUMNS: MessageKey[] = [
  "pharmacy.col.patient",
  "pharmacy.col.identifier",
  "pharmacy.col.items",
  "pharmacy.col.dispenseStatus",
  "pharmacy.col.prescribed",
  "pharmacy.col.actions",
];

export function PrescriptionQueue({ dispenseMode = false }: { dispenseMode?: boolean }) {
  const { t } = useLocale();
  const [rows, setRows] = useState<PrescriptionQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<PrescriptionQueueResponse>("/pharmacy/queue?page=1&page_size=100")
      .then((response) => {
        if (cancelled) return;
        setRows(response.items);
        setTotal(response.total);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Failed to load prescription queue");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-labelledby="pharmacy-queue-heading" style={{ padding: "2rem" }}>
      <h1 id="pharmacy-queue-heading">
        {dispenseMode ? t("pharmacy.dispensePrescriptions") : t("pharmacy.queueTitle")}
      </h1>
      <p>{loading ? `${t("pharmacy.loadingPrescriptions")}…` : `${total} prescription${total === 1 ? "" : "s"}`}</p>
      {dispenseMode ? (
        <p>Dispensing mutations remain unavailable until a prescription-item detail contract is connected.</p>
      ) : null}
      {loading ? <LoadingState label={t("pharmacy.loadingPrescriptions")} /> : null}
      {error ? <ErrorState message={error} /> : null}
      {!loading && !error && rows.length === 0 ? (
        <EmptyState title={t("pharmacy.queueEmptyTitle")} description={t("pharmacy.queueEmptyDescription")} />
      ) : null}
      {rows.length > 0 ? (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <caption className="sr-only">Prescription queue</caption>
            <thead>
              <tr>
                {QUEUE_COLUMNS.map((labelKey) => (
                  <th key={labelKey} scope="col" style={{ textAlign: "left", padding: "0.75rem", borderBottom: "1px solid #d7dde5" }}>{t(labelKey)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.prescription_id}>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>{row.patient_full_name}</td>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>{row.uhid ?? row.thid ?? "—"}</td>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>{row.item_count}</td>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>{row.dispense_status?.replaceAll("_", " ") ?? "Not dispensed"}</td>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>{formatDateTime(row.prescribed_at)}</td>
                  <td style={{ padding: "0.75rem", borderBottom: "1px solid #eef1f4" }}>
                    {!dispenseMode ? <Link href="/pharmacy/dispense">{t("pharmacy.openDispenseQueue")}</Link> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
