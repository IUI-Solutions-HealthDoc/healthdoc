"use client";

/**
 * Diagnoses this week against last week, by district. Counts below the
 * server's small-cell threshold arrive as "<5" and are shown exactly so: a
 * rare diagnosis in one block must not point at a person. Refreshes with the
 * board's district filter.
 */
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import { getMonitorTrends, type MonitorTrends } from "./api";

export function DiseaseTrends({ district }: { district: string | null }) {
  const { t } = useLocale();
  const [data, setData] = useState<MonitorTrends | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getMonitorTrends(district)
      .then((loaded) => {
        if (!current) return;
        setData(loaded);
        setError(null);
      })
      .catch((reason) => current && setError(reason instanceof ApiError ? reason.message : t("monitor.errLoadTrends")));
    return () => {
      current = false;
    };
  }, [district, t]);

  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t("monitor.trendsTitle")}</h2>
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="text-xs text-muted-foreground">
            {t("monitor.trendsWeek", { date: data.week_ending })} · {data.spike_rule}
          </p>
          {data.trends.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("monitor.noTrends")}</p>
          ) : (
            <div className="overflow-x-auto rounded border border-border">
              <table className="min-w-full text-sm">
                <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">{t("monitor.district")}</th>
                    <th className="px-3 py-2">{t("monitor.diagnosis")}</th>
                    <th className="px-3 py-2 text-right">{t("monitor.thisWeek")}</th>
                    <th className="px-3 py-2 text-right">{t("monitor.lastWeek")}</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {data.trends.map((row) => (
                    <tr key={`${row.district ?? ""}-${row.icd_version}-${row.icd_code}`} className="border-t border-border">
                      <td className="px-3 py-2">{row.district ?? "—"}</td>
                      <td className="px-3 py-2">
                        <span className="font-mono text-xs">{row.icd_code}</span> {row.title ?? ""}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.this_week}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.last_week}</td>
                      <td className="px-3 py-2">
                        {row.spike ? (
                          <span className="rounded border border-red-300 bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                            {t("monitor.spike")}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">{t("monitor.smallCell", { n: data.small_cell_below })}</p>
        </>
      ) : null}
    </section>
  );
}
