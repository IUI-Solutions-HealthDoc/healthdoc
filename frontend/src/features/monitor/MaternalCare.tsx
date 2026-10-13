"use client";

/**
 * Maternal care counts per facility, from the 15-minute captures. High risk
 * is the clinician's flag, never computed; no names reach the control room.
 */
import { useLocale } from "@/lib/i18n";

import type { MonitorBoard } from "./api";

export function MaternalCare({ board }: { board: MonitorBoard }) {
  const { t } = useLocale();
  const rows = board.facilities.filter((row) => row.mch && Object.values(row.mch).some((n) => (n ?? 0) > 0));
  const totals = board.totals.mch;
  if (!totals || rows.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t("monitor.mchTitle")}</h2>
      <div className="overflow-x-auto rounded border border-border">
        <table className="min-w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2">{t("monitor.colFacility")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.mchActive")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.mchHighRisk")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.mchAncToday")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.mchDeliveriesToday")}</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-border font-semibold">
              <td className="px-3 py-2">{t("monitor.adoptAllReporting")}</td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.active_pregnancies ?? 0}</td>
              <td className="px-3 py-2 text-right tabular-nums text-red-700">{totals.high_risk ?? 0}</td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.anc_visits_today ?? 0}</td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.deliveries_today ?? 0}</td>
            </tr>
            {rows.map((row) => (
              <tr key={row.facility_id} className="border-t border-border">
                <td className="px-3 py-2">{row.name}</td>
                <td className="px-3 py-2 text-right tabular-nums">{row.mch?.active_pregnancies ?? 0}</td>
                <td className="px-3 py-2 text-right tabular-nums">{row.mch?.high_risk ?? 0}</td>
                <td className="px-3 py-2 text-right tabular-nums">{row.mch?.anc_visits_today ?? 0}</td>
                <td className="px-3 py-2 text-right tabular-nums">{row.mch?.deliveries_today ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
