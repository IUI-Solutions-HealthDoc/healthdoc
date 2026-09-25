"use client";

import Box from "@mui/material/Box";
import {
  Area,
  AreaChart,
} from "recharts";

import { ChartWrapper } from "@/components/ui/ChartWrapper";
import { useLocale } from "@/lib/i18n";
import { kpiLabel, kpiUnit } from "@/lib/kpi";

import { KPI_SERIES_COLORS } from "../constants";
import type { ChartRow } from "../lib/kpiView";
import type { CoreKpiCode } from "../types";

type Props = {
  code: CoreKpiCode;
  data: ChartRow[];
  loading: boolean;
};

export function KpiSparklineCard({ code, data, loading }: Props) {
  const { t } = useLocale();
  const color = KPI_SERIES_COLORS[code];
  const last = data.length ? data[data.length - 1]?.[code] : undefined;
  const unit = kpiUnit(code);
  const gradId = `spark-g-${code}`;

  return (
    <ChartWrapper
      title={kpiLabel(code)}
      description={
        last != null
          ? t("reports.kpi.spark.latest", { value: String(last), unit: unit ? ` ${unit}` : "" })
          : t("reports.kpi.spark.noPoints")
      }
      height={112}
      loading={loading}
      empty={
        !loading && data.length === 0
          ? { title: t("reports.kpi.spark.noDataTitle"), description: t("reports.kpi.spark.noDataDesc") }
          : false
      }
      actions={
        <Box
          sx={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            bgcolor: color,
            boxShadow: `0 0 0 3px ${color}22`,
          }}
        />
      }
    >
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.38} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey={code}
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradId})`}
          dot={false}
          connectNulls
          animationDuration={500}
        />
      </AreaChart>
    </ChartWrapper>
  );
}
