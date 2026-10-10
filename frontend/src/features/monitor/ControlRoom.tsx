"use client";

/**
 * State / district control room.
 *
 * Reads 15-minute captures, so the page refreshes every minute to pick up the
 * next capture without hammering anything: the board query never touches the
 * hospitals' clinical tables. A failed refresh keeps the last good board on
 * screen and says it is stale, rather than blanking a wall display.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import { DiseaseTrends } from "./DiseaseTrends";
import { FacilityDetail } from "./FacilityDetail";
import { getMonitorBoard, type MonitorBoard, type MonitorFacilityRow, type MonitorStatus } from "./api";

const REFRESH_MS = 60_000;

const STATUS_STYLE: Record<MonitorStatus, string> = {
  red: "bg-red-100 text-red-800 border-red-300",
  amber: "bg-amber-100 text-amber-900 border-amber-300",
  green: "bg-emerald-100 text-emerald-800 border-emerald-300",
  grey: "bg-slate-100 text-slate-600 border-slate-300",
};

const STATUS_ORDER: Record<MonitorStatus, number> = { red: 0, amber: 1, grey: 2, green: 3 };

const STATUS_LABEL = {
  red: "monitor.status.red",
  amber: "monitor.status.amber",
  green: "monitor.status.green",
  grey: "monitor.status.grey",
} as const satisfies Record<MonitorStatus, string>;

function Tile({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</p>
    </div>
  );
}

function n(value: number | null): string {
  return value === null ? "—" : String(value);
}

export function ControlRoom() {
  const { t } = useLocale();
  const [district, setDistrict] = useState<string | null>(null);
  const [board, setBoard] = useState<MonitorBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBoard(await getMonitorBoard(district));
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("monitor.errLoad"));
    }
  }, [district, t]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const rows = useMemo(() => {
    const all = board?.facilities ?? [];
    const shown = onlyProblems ? all.filter((row) => row.status !== "green") : all;
    return [...shown].sort(
      (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || a.name.localeCompare(b.name),
    );
  }, [board, onlyProblems]);

  if (!board) {
    return (
      <div className="space-y-2 p-6">
        <h1 className="text-xl font-semibold">{t("monitor.title")}</h1>
        <p className={error ? "text-sm text-danger" : "text-sm text-muted-foreground"} role={error ? "alert" : undefined}>
          {error ?? t("common.loading")}
        </p>
      </div>
    );
  }

  const area = board.areas
    .map((a) => (a.district ? `${a.district}, ${a.state_code}` : `${a.state_code} (${t("monitor.wholeState")})`))
    .join(" · ");
  const totals = board.totals;

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("monitor.title")}</h1>
          <p className="text-sm text-muted-foreground">
            {area} · {t("monitor.updated")} {formatDateTime(board.generated_at)}
          </p>
          {error ? (
            <p className="text-sm text-danger" role="alert">
              {t("monitor.stale")} {error}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm">
            <span className="mr-2 text-muted-foreground">{t("monitor.district")}</span>
            <select
              value={district ?? ""}
              onChange={(event) => setDistrict(event.target.value || null)}
              className="rounded-md border border-border px-2 py-1.5 text-sm"
            >
              <option value="">{t("monitor.allDistricts")}</option>
              {board.districts.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={onlyProblems} onChange={(event) => setOnlyProblems(event.target.checked)} />
            {t("monitor.onlyProblems")}
          </label>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5 lg:grid-cols-9">
        <Tile label={t("monitor.facilities")} value={`${totals.reporting}/${totals.facilities}`} />
        <Tile label={t("monitor.red")} value={totals.red} tone="text-red-700" />
        <Tile label={t("monitor.amber")} value={totals.amber} tone="text-amber-700" />
        <Tile label={t("monitor.notReporting")} value={totals.grey} tone="text-slate-600" />
        <Tile label={t("monitor.opdToday")} value={totals.opd_today} />
        <Tile label={t("monitor.emergencyNow")} value={totals.emergency_open} />
        <Tile label={t("monitor.admittedBeds")} value={`${totals.admitted_now}/${totals.beds_total}`} />
        <Tile label={t("monitor.stockShort")} value={totals.stock_below_reorder} />
        <Tile label={t("monitor.machinesDown")} value={totals.equipment_down} />
      </div>

      <div className="overflow-x-auto rounded border border-border">
        <table className="min-w-full text-sm">
          <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2">{t("monitor.colStatus")}</th>
              <th className="px-3 py-2">{t("monitor.colFacility")}</th>
              <th className="px-3 py-2">{t("monitor.district")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.opdToday")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.colWaiting")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.emergencyNow")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.colBeds")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.colLab")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.stockShort")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.colExpiring")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.colStaff")}</th>
              <th className="px-3 py-2 text-right">{t("monitor.machinesDown")}</th>
              <th className="px-3 py-2">{t("monitor.colLastReport")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={13} className="px-3 py-6 text-center text-muted-foreground">
                  {onlyProblems ? t("monitor.noProblems") : t("monitor.noFacilities")}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <FacilityRow key={row.facility_id} row={row} onOpen={() => setSelected(row.facility_id)} />
              ))
            )}
          </tbody>
        </table>
      </div>

      {selected ? <FacilityDetail facilityId={selected} onClose={() => setSelected(null)} /> : null}

      <DiseaseTrends district={district} />

      <p className="text-xs text-muted-foreground">
        {t("monitor.thresholds", {
          bedAmber: board.thresholds.bed_amber_percent,
          bedRed: board.thresholds.bed_red_percent,
          stockRed: board.thresholds.stock_red_items,
          minutes: board.thresholds.not_reporting_after_minutes,
        })}
      </p>
    </div>
  );
}

function FacilityRow({ row, onOpen }: { row: MonitorFacilityRow; onOpen: () => void }) {
  const { t } = useLocale();
  const beds =
    row.beds_total === null
      ? "—"
      : `${row.admitted_now}/${row.beds_total}${row.bed_occupancy_percent === null ? "" : ` (${row.bed_occupancy_percent}%)`}`;
  return (
    <tr className="border-t border-border align-top">
      <td className="px-3 py-2">
        <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[row.status]}`}>
          {t(STATUS_LABEL[row.status])}
        </span>
        {row.reasons.length ? <p className="mt-1 max-w-48 text-xs text-muted-foreground">{row.reasons.join("; ")}</p> : null}
      </td>
      <td className="px-3 py-2">
        <button type="button" onClick={onOpen} className="text-left font-medium underline-offset-2 hover:underline">
          {row.name}
        </button>
        <p className="text-xs text-muted-foreground">{[row.code, row.facility_type].filter(Boolean).join(" · ")}</p>
      </td>
      <td className="px-3 py-2">{row.district ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.opd_today)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.queue_waiting)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.emergency_open)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{beds}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.lab_pending)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.stock_below_reorder)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.batches_expiring_30d)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{n(row.staff_rostered_today)}</td>
      <td className={`px-3 py-2 text-right tabular-nums ${row.critical_equipment_down ? "font-semibold text-red-700" : ""}`}>
        {n(row.equipment_down)}
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {row.captured_at ? formatDateTime(row.captured_at) : t("monitor.never")}
      </td>
    </tr>
  );
}
