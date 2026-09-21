/**
 * Read shape for kpi_snapshots (migration 0025).
 * Labels/units/chart type are not in schema — hard-code in callers.
 */
export type KpiSnapshot = {
  facility_id: string;
  kpi_code: string;
  period_start: string;
  period_end: string;
  value: number;
  numerator: number | null;
  denominator: number | null;
  calculation_version?: string | null;
};

/** Point series for ChartWrapper children (value over period_start). */
export type KpiChartPoint = {
  period_start: string;
  value: number;
};
