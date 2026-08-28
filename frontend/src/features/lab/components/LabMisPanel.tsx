"use client";

import { useCallback, useEffect, useState } from "react";

import { getLabMisSummary } from "@/features/lab/api";
import type { LabMisSummary } from "@/features/lab/types";
import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/AsyncState";

function defaultRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 30);
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

export function LabMisPanel() {
  const initial = defaultRange();
  const [dateFrom, setDateFrom] = useState(initial.from);
  const [dateTo, setDateTo] = useState(initial.to);
  const [summary, setSummary] = useState<LabMisSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fromIso = `${dateFrom}T00:00:00.000Z`;
      const toIso = `${dateTo}T23:59:59.999Z`;
      setSummary(await getLabMisSummary(fromIso, toIso));
      setError(null);
    } catch (reason) {
      setSummary(null);
      setError(reason instanceof ApiError ? reason.message : "Could not load lab MIS summary");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">From</span>
          <input
            type="date"
            className="block rounded-md border border-border px-3 py-2"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">To</span>
          <input
            type="date"
            className="block rounded-md border border-border px-3 py-2"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="rounded-md border border-border px-4 py-2 text-sm"
          onClick={() => void load()}
        >
          Refresh
        </button>
      </div>

      {loading && !summary ? <LoadingState label="Loading MIS summary" /> : null}
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      {summary ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Orders in range" value={String(summary.total_orders)} />
            <MetricCard label="Final results" value={String(summary.total_results)} />
            <MetricCard
              label="Statuses tracked"
              value={String(summary.order_counts_by_status.length)}
            />
            <MetricCard
              label="Tests with panic data"
              value={String(summary.panic_frequency.length)}
            />
          </div>

          <section className="surface-card overflow-hidden">
            <h3 className="border-b border-border px-4 py-3 font-medium">Turnaround by test</h3>
            {summary.tat_by_test.length === 0 ? (
              <EmptyState
                title="No TAT data"
                description="No finalized results in this date range."
              />
            ) : (
              <table className="min-w-full border-collapse text-sm">
                <thead className="bg-muted">
                  <tr>
                    {["Test", "Samples", "Avg TAT (min)", "Median TAT (min)"].map((label) => (
                      <th key={label} className="px-4 py-2 text-left">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {summary.tat_by_test.map((row) => (
                    <tr key={row.test_name} className="border-b border-border last:border-none">
                      <td className="px-4 py-2 font-medium">{row.test_name}</td>
                      <td className="px-4 py-2 tabular-nums">{row.sample_count}</td>
                      <td className="px-4 py-2 tabular-nums">
                        {row.avg_tat_minutes != null ? row.avg_tat_minutes.toFixed(1) : "—"}
                      </td>
                      <td className="px-4 py-2 tabular-nums">
                        {row.median_tat_minutes != null ? row.median_tat_minutes.toFixed(1) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="surface-card overflow-hidden">
              <h3 className="border-b border-border px-4 py-3 font-medium">Orders by status</h3>
              {summary.order_counts_by_status.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No orders in range.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {summary.order_counts_by_status.map((row) => (
                    <li
                      key={row.status}
                      className="flex items-center justify-between px-4 py-2 text-sm"
                    >
                      <span>{row.status.replaceAll("_", " ")}</span>
                      <span className="font-medium tabular-nums">{row.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="surface-card overflow-hidden">
              <h3 className="border-b border-border px-4 py-3 font-medium">Critical frequency</h3>
              {summary.panic_frequency.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No panic events in range.</p>
              ) : (
                <table className="min-w-full border-collapse text-sm">
                  <thead className="bg-muted">
                    <tr>
                      {["Test", "Critical", "Total", "Rate %"].map((label) => (
                        <th key={label} className="px-4 py-2 text-left">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {summary.panic_frequency.map((row) => (
                      <tr key={row.test_name} className="border-b border-border last:border-none">
                        <td className="px-4 py-2">{row.test_name}</td>
                        <td className="px-4 py-2 tabular-nums text-danger">{row.critical_count}</td>
                        <td className="px-4 py-2 tabular-nums">{row.total_count}</td>
                        <td className="px-4 py-2 tabular-nums">{row.panic_rate_pct.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
