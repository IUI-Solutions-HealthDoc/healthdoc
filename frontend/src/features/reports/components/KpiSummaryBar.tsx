"use client";

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";

import { PERIOD_OPTIONS } from "../constants";
import { KPI_PERIOD_MESSAGE_KEYS } from "../lib/periodLabels";
import type { CoreKpiCode, KpiPeriod } from "../types";
import { kpiLabel } from "@/lib/kpi";

type Props = {
  period: KpiPeriod;
  windowLabel: string | null;
  snapshotCount: number;
  dayCount: number;
  focusCode: CoreKpiCode | null;
  onClearFocus: () => void;
};

export function KpiSummaryBar({
  period,
  windowLabel,
  snapshotCount,
  dayCount,
  focusCode,
  onClearFocus,
}: Props) {
  const { t } = useLocale();
  const periodLabel = t(KPI_PERIOD_MESSAGE_KEYS[period]);

  const pills = [
    { key: "period", label: periodLabel },
    windowLabel ? { key: "window", label: windowLabel } : null,
    { key: "days", label: t("reports.kpi.days", { count: dayCount }) },
    { key: "rows", label: t("reports.kpi.snapshots", { count: snapshotCount }) },
  ].filter(Boolean) as { key: string; label: string }[];

  return (
    <Box
      sx={{
        display: "flex",
        flexWrap: "wrap",
        gap: 1,
        alignItems: "center",
        justifyContent: "space-between",
        px: 2,
        py: 1.5,
        borderRadius: "14px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(110deg, ${meridian.muted} 0%, ${meridian.surface} 55%, #eef4fb 100%)`,
      }}
    >
      <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: "wrap", alignItems: "center" }}>
        <Typography
          sx={{
            m: 0,
            mr: 0.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: meridian.textSecondary,
          }}
        >
          {t("reports.kpi.window")}
        </Typography>
        {pills.map((p) => (
          <Chip
            key={p.key}
            size="small"
            label={p.label}
            sx={{
              height: 26,
              fontWeight: 600,
              fontSize: "0.75rem",
              bgcolor: meridian.surface,
              border: `1px solid ${meridian.border}`,
              color: meridian.textPrimary,
            }}
          />
        ))}
      </Stack>

      {focusCode ? (
        <Chip
          size="small"
          color="primary"
          variant="outlined"
          label={t("reports.kpi.focus", { label: kpiLabel(focusCode) })}
          onDelete={onClearFocus}
          sx={{ fontWeight: 600 }}
        />
      ) : (
        <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.textSecondary }}>
          {t("reports.kpi.showingBoth")}
        </Typography>
      )}
    </Box>
  );
}
