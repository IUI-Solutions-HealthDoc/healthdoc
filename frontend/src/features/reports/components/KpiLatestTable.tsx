"use client";

import Box from "@mui/material/Box";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { useLocale, type MessageKey } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { kpiLabel, kpiUnit } from "@/lib/kpi";
import type { KpiSnapshot } from "@/types/kpi";

import { CORE_KPI_CODES, KPI_SERIES_COLORS } from "../constants";
import type { CoreKpiCode } from "../types";
import { formatPeriodShort } from "../lib/kpiView";

type Props = {
  latest: Partial<Record<CoreKpiCode, KpiSnapshot>>;
  loading: boolean;
};

const COLUMN_KEYS: MessageKey[] = [
  "reports.kpi.col.kpi",
  "reports.kpi.col.period",
  "reports.kpi.col.value",
  "reports.kpi.col.numerator",
  "reports.kpi.col.denominator",
];

export function KpiLatestTable({ latest, loading }: Props) {
  const { t } = useLocale();
  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        overflow: "hidden",
      }}
    >
      <Box sx={{ px: 3, pt: 2.5, pb: 1.75 }}>
        <Typography
          component="h3"
          sx={{
            m: 0,
            fontSize: "1.0625rem",
            fontWeight: 700,
            letterSpacing: "-0.02em",
            color: meridian.textPrimary,
          }}
        >
          {t("reports.kpi.table.title")}
        </Typography>
        <Typography sx={{ m: 0, mt: 0.5, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("reports.kpi.table.subtitle")}
        </Typography>
      </Box>

      <Table size="small" sx={{ "& th, & td": { borderColor: "rgb(0 31 84 / 0.08)" } }}>
        <TableHead>
          <TableRow sx={{ bgcolor: meridian.muted }}>
            {COLUMN_KEYS.map((key) => (
              <TableCell
                key={key}
                sx={{
                  fontWeight: 700,
                  fontSize: "0.6875rem",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  color: meridian.textSecondary,
                  py: 1.25,
                }}
              >
                {t(key)}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {CORE_KPI_CODES.map((code) => {
            const row = latest[code];
            const unit = kpiUnit(code);
            return (
              <TableRow
                key={code}
                hover
                sx={{ "&:last-child td": { borderBottom: 0 } }}
              >
                <TableCell sx={{ py: 1.5 }}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                    <Box
                      sx={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        bgcolor: KPI_SERIES_COLORS[code],
                        flexShrink: 0,
                      }}
                    />
                    <Typography sx={{ m: 0, fontSize: "0.875rem", fontWeight: 600, color: meridian.textPrimary }}>
                      {kpiLabel(code)}
                    </Typography>
                  </Box>
                  <Typography sx={{ m: 0, ml: 2.25, fontSize: "0.6875rem", color: meridian.textSecondary, fontFamily: "ui-monospace, monospace" }}>
                    {code}
                  </Typography>
                </TableCell>
                <TableCell sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
                  {loading ? "…" : row ? formatPeriodShort(row.period_start) : "—"}
                </TableCell>
                <TableCell sx={{ fontSize: "0.875rem", fontWeight: 700, color: meridian.textPrimary }}>
                  {loading || !row
                    ? "—"
                    : `${row.value}${unit ? ` ${unit}` : ""}`}
                </TableCell>
                <TableCell sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
                  {row?.numerator ?? "—"}
                </TableCell>
                <TableCell sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
                  {row?.denominator ?? "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
