import type { MetricCardProps } from "@/components/ui/MetricCard";
import type { KpiChartPoint, KpiSnapshot } from "@/types/kpi";
import { translate } from "@/lib/i18n";

/**
 * Hard-coded labels/units for known kpi_code values.
 * No kpi_code catalogue table exists in schema.
 */
const KPI_DISPLAY: Record<string, { label: string; unit?: string }> = {
  avg_opd_wait_minutes: { get label() { return translate("common.msg.avgOpdWait"); }, unit: "min" },
  sharp_injury_count: { get label() { return translate("common.msg.sharpInjuries"); } },
};

export function kpiLabel(kpi_code: string): string {
  return KPI_DISPLAY[kpi_code]?.label ?? kpi_code;
}

export function kpiUnit(kpi_code: string): string | undefined {
  return KPI_DISPLAY[kpi_code]?.unit;
}

/** Map a kpi_snapshots row to MetricCard presentation props. */
export function kpiSnapshotToMetricCardProps(
  snapshot: KpiSnapshot,
): Pick<MetricCardProps, "label" | "value" | "unit"> {
  return {
    label: kpiLabel(snapshot.kpi_code),
    value: formatKpiValue(snapshot.value, snapshot.kpi_code),
    unit: kpiUnit(snapshot.kpi_code),
  };
}

/** Collapse snapshot rows (same kpi_code) into chart points by period_start. */
export function kpiSnapshotsToChartPoints(rows: KpiSnapshot[]): KpiChartPoint[] {
  return [...rows]
    .sort((a, b) => a.period_start.localeCompare(b.period_start))
    .map((r) => ({ period_start: r.period_start, value: Number(r.value) }));
}

function formatKpiValue(value: number, kpi_code: string): string {
  if (kpi_code.endsWith("_pct")) {
    return Number(value).toFixed(1);
  }
  if (Number.isInteger(value)) return String(value);
  return Number(value).toFixed(2);
}
