"use client";

import { useId, useMemo } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { NameType, Payload, ValueType } from "recharts/types/component/DefaultTooltipContent";

import { ChartWrapper } from "@/components/ui/ChartWrapper";
import { useLocale } from "@/lib/i18n";
import { kpiLabel, kpiUnit } from "@/lib/kpi";
import { meridian } from "@/styles/theme";

import { KPI_SERIES_COLORS } from "../constants";
import type { ChartRow } from "../lib/kpiView";
import { formatPeriodShort } from "../lib/kpiView";
import type { CoreKpiCode } from "../types";

type Props = {
  data: ChartRow[];
  codes: readonly CoreKpiCode[];
  loading: boolean;
  title: string;
  description: string;
  /** Single-series uses filled area; multi uses lines for readability across units. */
  mode?: "auto" | "area" | "line";
};

type TipProps = {
  active?: boolean;
  payload?: Payload<ValueType, NameType>[];
  label?: string | number;
};

function CustomTooltip({ active, payload, label }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <Box
      sx={{
        px: 1.5,
        py: 1.25,
        minWidth: 160,
        borderRadius: "12px",
        border: `1px solid ${meridian.border}`,
        bgcolor: meridian.surface,
        boxShadow: "0 12px 32px rgb(0 31 84 / 0.14)",
      }}
    >
      <Typography
        sx={{
          m: 0,
          mb: 0.75,
          fontSize: "0.75rem",
          fontWeight: 700,
          color: meridian.textPrimary,
        }}
      >
        {typeof label === "string" ? formatPeriodShort(label) : String(label ?? "")}
      </Typography>
      {payload.map((entry) => {
        const code = String(entry.dataKey ?? "");
        const unit = kpiUnit(code);
        const color = (entry.color as string) ?? meridian.brandPrimary;
        return (
          <Box
            key={code}
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 2,
              py: 0.25,
            }}
          >
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
              <Box
                sx={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  bgcolor: color,
                  flexShrink: 0,
                }}
              />
              <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.textSecondary }}>
                {kpiLabel(code)}
              </Typography>
            </Box>
            <Typography
              sx={{ m: 0, fontSize: "0.8125rem", fontWeight: 700, color: meridian.textPrimary }}
            >
              {entry.value}
              {unit ? ` ${unit}` : ""}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}

export function KpiTrendChart({
  data,
  codes,
  loading,
  title,
  description,
  mode = "auto",
}: Props) {
  const { t } = useLocale();
  const uid = useId().replace(/:/g, "");
  const useArea = mode === "area" || (mode === "auto" && codes.length === 1);

  const gradients = useMemo(
    () =>
      codes.map((code) => ({
        code,
        id: `fill-${uid}-${code}`,
        color: KPI_SERIES_COLORS[code],
      })),
    [codes, uid],
  );

  return (
    <ChartWrapper
      title={title}
      description={description}
      height={360}
      loading={loading}
      empty={
        !loading && data.length === 0
          ? {
              title: t("reports.kpi.chart.noSnapshotsTitle"),
              description: t("reports.kpi.chart.noSnapshotsDesc"),
            }
          : false
      }
      sx={{
        "& .recharts-cartesian-grid-horizontal line": {
          stroke: "rgb(0 31 84 / 0.06)",
        },
        "& .recharts-cartesian-grid-vertical line": {
          stroke: "transparent",
        },
      }}
    >
      <ComposedChart
        data={data}
        margin={{ top: 12, right: 16, left: 4, bottom: 4 }}
      >
        <defs>
          {gradients.map((g) => (
            <linearGradient key={g.id} id={g.id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={g.color} stopOpacity={0.35} />
              <stop offset="55%" stopColor={g.color} stopOpacity={0.08} />
              <stop offset="100%" stopColor={g.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="4 8" />
        <XAxis
          dataKey="period_start"
          axisLine={false}
          tickLine={false}
          dy={6}
          tickFormatter={(v: string) => formatPeriodShort(v)}
          interval="preserveStartEnd"
          minTickGap={28}
        />
        <YAxis
          axisLine={false}
          tickLine={false}
          width={44}
          tickCount={5}
        />
        <Tooltip
          cursor={{ stroke: "rgb(0 31 84 / 0.18)", strokeWidth: 1, strokeDasharray: "4 4" }}
          content={<CustomTooltip />}
        />
        {codes.length > 1 ? (
          <Legend
            verticalAlign="top"
            align="right"
            height={28}
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ paddingBottom: 4 }}
          />
        ) : null}
        {codes.map((code) =>
          useArea ? (
            <Area
              key={code}
              type="monotone"
              dataKey={code}
              name={kpiLabel(code)}
              stroke={KPI_SERIES_COLORS[code]}
              strokeWidth={2.5}
              fill={`url(#fill-${uid}-${code})`}
              dot={false}
              activeDot={{
                r: 5,
                strokeWidth: 2,
                stroke: meridian.surface,
                fill: KPI_SERIES_COLORS[code],
              }}
              connectNulls
              animationDuration={650}
              animationEasing="ease-out"
            />
          ) : (
            <Line
              key={code}
              type="monotone"
              dataKey={code}
              name={kpiLabel(code)}
              stroke={KPI_SERIES_COLORS[code]}
              strokeWidth={2.25}
              dot={false}
              activeDot={{
                r: 4,
                strokeWidth: 2,
                stroke: meridian.surface,
                fill: KPI_SERIES_COLORS[code],
              }}
              connectNulls
              animationDuration={650}
              animationEasing="ease-out"
            />
          ),
        )}
      </ComposedChart>
    </ChartWrapper>
  );
}
