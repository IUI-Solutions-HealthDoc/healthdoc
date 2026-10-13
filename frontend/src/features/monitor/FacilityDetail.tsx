"use client";

/**
 * What lies behind one hospital's status: beds by ward, the medicines below
 * reorder level and the batches about to expire. Read from the same capture
 * as the board, so the numbers here always add up to the row the officer
 * clicked. Quantities are decimal strings and are shown as sent.
 */
import { useEffect, useState } from "react";

import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import { ActivityTrail } from "./ActivityTrail";
import { getMonitorFacility, type MonitorFacilityDetail } from "./api";

export function FacilityDetail({ facilityId, onClose }: { facilityId: string; onClose: () => void }) {
  const { t } = useLocale();
  const [detail, setDetail] = useState<MonitorFacilityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setDetail(null);
    setError(null);
    getMonitorFacility(facilityId)
      .then((loaded) => current && setDetail(loaded))
      .catch((reason) => current && setError(reason instanceof ApiError ? reason.message : t("monitor.errLoadFacility")));
    return () => {
      current = false;
    };
  }, [facilityId, t]);

  return (
    <section className="space-y-4 rounded border border-border p-4" aria-live="polite">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{detail?.facility.name ?? t("common.loading")}</h2>
          {detail ? (
            <p className="text-sm text-muted-foreground">
              {[detail.facility.district, detail.facility.code].filter(Boolean).join(" · ")}
              {detail.facility.captured_at ? ` · ${t("monitor.updated")} ${formatDateTime(detail.facility.captured_at)}` : ""}
            </p>
          ) : null}
        </div>
        <button type="button" onClick={onClose} className="text-sm underline">
          {t("common.close")}
        </button>
      </div>
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {detail && detail.facility.status === "grey" ? <p className="text-sm text-muted-foreground">{t("monitor.detailNotReporting")}</p> : null}
      {detail && detail.facility.status !== "grey" ? (
        <div className="space-y-4">
        <div>
          <h3 className="mb-2 text-sm font-medium">{t("monitor.machinesNotWorking")}</h3>
          {detail.equipment.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("monitor.allMachinesWorking")}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {detail.equipment.map((machine, index) => (
                <li key={`${machine.name}-${index}`} className="flex flex-wrap justify-between gap-2 border-t border-border py-1">
                  <span>
                    <span className={machine.critical ? "font-semibold text-red-700" : ""}>{machine.name}</span>
                    {machine.location ? <span className="text-xs text-muted-foreground"> · {machine.location}</span> : null}
                    {machine.reason ? <span className="block text-xs text-muted-foreground">{machine.reason}</span> : null}
                  </span>
                  <span className="text-xs">
                    {machine.status} · {t("monitor.since")} {formatDateTime(machine.since)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-medium">{t("monitor.staffToday")}</h3>
          {detail.staff.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("monitor.noStaff")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1">{t("monitor.staffName")}</th>
                  <th className="py-1">{t("monitor.department")}</th>
                  <th className="py-1">{t("monitor.shift")}</th>
                  <th className="py-1">{t("monitor.activity")}</th>
                  <th className="py-1 text-right">{t("monitor.colWaiting")}</th>
                </tr>
              </thead>
              <tbody>
                {detail.staff.map((person) => (
                  <tr key={`${person.name}-${person.department ?? ""}`} className="border-t border-border">
                    <td className="py-1">
                      {person.name}
                      {person.designation ? <span className="block text-xs text-muted-foreground">{person.designation}</span> : null}
                    </td>
                    <td className="py-1">{person.department ?? "—"}</td>
                    <td className="py-1">{person.shift ?? "—"}</td>
                    <td className={`py-1 ${!person.active_today && person.waiting > 0 ? "font-medium text-amber-800" : ""}`}>
                      {person.active_today ? t("monitor.activeToday") : t("monitor.noActivityYet")}
                    </td>
                    <td className="py-1 text-right tabular-nums">{person.waiting}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <div>
            <h3 className="mb-2 text-sm font-medium">{t("monitor.wards")}</h3>
            {detail.wards.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("monitor.noWards")}</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1">{t("monitor.ward")}</th>
                    <th className="py-1 text-right">{t("monitor.free")}</th>
                    <th className="py-1 text-right">{t("monitor.occupied")}</th>
                    <th className="py-1 text-right">{t("monitor.maintenance")}</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.wards.map((ward) => (
                    <tr key={`${ward.ward}-${ward.department ?? ""}`} className="border-t border-border">
                      <td className="py-1">
                        {ward.ward}
                        {ward.department ? <span className="block text-xs text-muted-foreground">{ward.department}</span> : null}
                      </td>
                      <td className={`py-1 text-right tabular-nums ${ward.free === 0 ? "font-semibold text-red-700" : ""}`}>
                        {ward.free}/{ward.beds}
                      </td>
                      <td className="py-1 text-right tabular-nums">{ward.occupied}</td>
                      <td className="py-1 text-right tabular-nums">{ward.maintenance}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium">{t("monitor.stockShortList")}</h3>
            {detail.stock_short.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("monitor.noStockShort")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {detail.stock_short.map((item) => (
                  <li key={`${item.item}-${item.strength ?? ""}`} className="flex justify-between gap-2 border-t border-border py-1">
                    <span>
                      {item.item}
                      {item.strength ? ` ${item.strength}` : ""}
                    </span>
                    <span className="tabular-nums text-red-700">
                      {item.available} / {item.reorder_level}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium">{t("monitor.expiringList")}</h3>
            {detail.expiring.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("monitor.noExpiring")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {detail.expiring.map((batch) => (
                  <li key={`${batch.item}-${batch.batch}`} className="flex justify-between gap-2 border-t border-border py-1">
                    <span>
                      {batch.item} <span className="text-xs text-muted-foreground">{batch.batch}</span>
                    </span>
                    <span className="tabular-nums">
                      {batch.expiry} · {batch.quantity}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        </div>
      ) : null}
      {detail ? <ActivityTrail facilityId={facilityId} /> : null}
      {detail ? <p className="text-xs text-muted-foreground">{t("monitor.listLimit", { limit: detail.list_limit })}</p> : null}
    </section>
  );
}
