"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

import { meridian } from "@/styles/theme";
import type { VitalRecord } from "./VitalsTimeline.types";
import { useLocale } from "@/lib/i18n";

export type VitalsChartProps = {
  records: VitalRecord[];
};

type ChartPoint = {
  recordedAt: string;
  // Nullable throughout: a nurse who took a pulse and SpO2 did not necessarily
  // take a temperature, and Recharts draws a gap for null. Typed as non-null
  // before, these would have plotted as zero — a line dropping to 0 °C reads
  // as a crashing patient rather than a measurement nobody took.
  pulse: number | null;
  respiratoryRate: number | null;
  oxygenSaturation: number | null;
  temperature: number | null;
  bpSystolic: number | null;
  bpDiastolic: number | null;
};

function formatTick(recordedAt: string): string {
  const date = new Date(recordedAt);
  if (Number.isNaN(date.getTime())) return recordedAt;
  return date.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** Decimal columns arrive as strings over JSON; null stays null. */
function num(value: string | number | null): number | null {
  if (value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Shared vitals trend chart — consumes the same VitalRecord shape as VitalsTimeline.
 */
export default function VitalsChart({ records }: VitalsChartProps) {
  const { t } = useLocale();
  if (records.length === 0) {
    return (
      <div
        style={{
          padding: 24,
          borderRadius: 16,
          border: `1px solid ${meridian.border}`,
          background: meridian.surface,
        }}
      >
        <p style={{ margin: 0, fontSize: 14, color: meridian.textSecondary }}>{t("common.ui.noVitalRecordsAvailable")}</p>
      </div>
    );
  }

  const chartData: ChartPoint[] = records
    .slice()
    .sort(
      (a, b) =>
        new Date(a.measured_at).getTime() - new Date(b.measured_at).getTime(),
    )
    .map((row) => ({
      recordedAt: row.measured_at,
      pulse: row.pulse_bpm,
      respiratoryRate: row.resp_rate,
      oxygenSaturation: row.spo2_pct,
      temperature: num(row.temp_c),
      bpSystolic: row.bp_systolic,
      bpDiastolic: row.bp_diastolic,
    }));

  return (
    <div
      style={{
        padding: 24,
        borderRadius: 16,
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow:
          "0 1px 2px rgb(0 31 84 / 0.04), 0 8px 24px rgb(0 31 84 / 0.06)",
      }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: "1.125rem",
          fontWeight: 700,
          color: meridian.textPrimary,
        }}
      >{t("common.ui.vitalsChart")}</h2>
      <p
        style={{
          margin: "4px 0 0",
          fontSize: 14,
          color: meridian.textSecondary,
        }}
      >{t("common.ui.timeSeriesTrendOfPatientVitals")}</p>

      <div style={{ marginTop: 24, height: 320, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 8, right: 24, left: 8, bottom: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgb(0 31 84 / 0.08)" />

            <XAxis
              dataKey="recordedAt"
              tickFormatter={formatTick}
              tick={{ fontSize: 12, fill: meridian.textSecondary }}
            />

            <YAxis
              yAxisId="left"
              tick={{ fontSize: 12, fill: meridian.textSecondary }}
              width={40}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fontSize: 12, fill: meridian.textSecondary }}
              width={40}
            />

            <Tooltip labelFormatter={(label) => formatTick(String(label))} />
            <Legend />

            <Line
              yAxisId="left"
              type="monotone"
              dataKey="pulse"
              name="Pulse (bpm)"
              stroke={meridian.danger}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="respiratoryRate"
              name="Resp. Rate (rpm)"
              stroke={meridian.success}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="oxygenSaturation"
              name="SpO₂ (%)"
              stroke={meridian.brandPrimary}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="bpSystolic"
              name="BP Systolic"
              stroke="#7c3aed"
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="bpDiastolic"
              name="BP Diastolic"
              stroke="#3d8bfd"
              connectNulls
              isAnimationActive={false}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="temperature"
              name="Temp (°C)"
              stroke={meridian.warning}
              connectNulls
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
