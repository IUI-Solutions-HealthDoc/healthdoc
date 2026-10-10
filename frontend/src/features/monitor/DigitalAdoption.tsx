"use client";

/**
 * Today's digital-health adoption per facility: the figures a state reports
 * under ABDM's Digital Health Incentive Scheme. Read from the same board data
 * (15-minute captures); facilities not reporting are left out of the totals.
 */
import { useLocale } from "@/lib/i18n";

import type { MonitorBoard } from "./api";

function percent(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((100 * part) / whole)}%` : "—";
}

export function DigitalAdoption({ board }: { board: MonitorBoard }) {
  const { t } = useLocale();
  const totals = board.totals.adoption;
  const rows = board.facilities.filter((row) => row.adoption);
  if (!totals || rows.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t("monitor.adoptionTitle")}</h2>
      <p className="text-xs text-muted-foreground">{t("monitor.adoptionIntro")}</p>
      <div className="overflow-x-auto rounded border border-border">
        <table className="min-w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2">{t("monitor.colFacility")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.adoptRegistrations")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.adoptAbha")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.adoptScanShare")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.adoptPrescriptions")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.adoptAbdmRecords")}</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-border font-semibold">
              <td className="px-3 py-2">{t("monitor.adoptAllReporting")}</td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.registrations ?? 0}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {totals.abha_linked ?? 0} ({percent(totals.abha_linked ?? 0, totals.registrations ?? 0)})
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {totals.scan_share ?? 0} ({percent(totals.scan_share ?? 0, totals.registrations ?? 0)})
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.prescriptions ?? 0}</td>
              <td className="px-3 py-2 text-right tabular-nums">{totals.abdm_records ?? 0}</td>
            </tr>
            {rows.map((row) => {
              const a = row.adoption ?? {};
              return (
                <tr key={row.facility_id} className="border-t border-border">
                  <td className="px-3 py-2">{row.name}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{a.registrations ?? 0}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {a.abha_linked ?? 0} ({percent(a.abha_linked ?? 0, a.registrations ?? 0)})
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {a.scan_share ?? 0} ({percent(a.scan_share ?? 0, a.registrations ?? 0)})
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{a.prescriptions ?? 0}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{a.abdm_records ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
