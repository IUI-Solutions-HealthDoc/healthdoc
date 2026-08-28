"use client";

import { useEffect, useMemo, useState } from "react";
import AccessTimeOutlinedIcon from "@mui/icons-material/AccessTimeOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import { ExportButton, type ExportFormat } from "@/components/ui/ExportButton";
import { MetricCard } from "@/components/ui/MetricCard";
import { toast } from "@/components/ui/toast";
import { getFacilityCapabilities } from "@/features/admin/api";
import type { FacilityCapabilities } from "@/features/admin/types";
import { kpiSnapshotToMetricCardProps, kpiLabel } from "@/lib/kpi";
import { meridian } from "@/styles/theme";

import { KPI_SERIES_COLORS, PERIOD_OPTIONS } from "../constants";
import { useKpis } from "../hooks";
import { visibleKpiCodes } from "../lib/capabilitiesFilter";
import {
  deltaVsPrior,
  downloadTextFile,
  latestByCode,
  periodWindowLabel,
  pivotForChart,
  snapshotsToCsv,
} from "../lib/kpiView";
import type { CoreKpiCode, KpiPeriod } from "../types";
import { BillingMisPanel } from "./BillingMisPanel";
import { KpiLatestTable } from "./KpiLatestTable";
import { KpiSparklineCard } from "./KpiSparklinePanel";
import { KpiSummaryBar } from "./KpiSummaryBar";
import { KpiTrendChart } from "./KpiTrendChart";
import "../mis-print.css";

const KPI_ICONS: Record<CoreKpiCode, React.ReactNode> = {
  avg_opd_wait_minutes: <AccessTimeOutlinedIcon />,
  sharp_injury_count: <WarningAmberOutlinedIcon />,
};

function formatDeltaLabel(diff: number, code: CoreKpiCode): string {
  const abs = Math.abs(diff);
  const unit = code === "avg_opd_wait_minutes" ? " min" : "";
  const sign = diff > 0 ? "+" : diff < 0 ? "−" : "";
  const formatted =
    code === "sharp_injury_count" ? String(abs) : abs.toFixed(abs >= 10 ? 0 : 1);
  return `${sign}${formatted}${unit} vs prior day`;
}

export function MisDashboard() {
  const { items, loading, error, period, setPeriod, customFrom, customTo, setCustomFrom, setCustomTo } = useKpis("7d");
  const [focusCode, setFocusCode] = useState<CoreKpiCode | null>(null);
  const [capabilities, setCapabilities] = useState<FacilityCapabilities | null>(null);
  const customRangeInvalid = Boolean(customFrom && customTo && customFrom > customTo);

  useEffect(() => {
    let cancelled = false;
    // No argument: capabilities are the caller's own facility, from the token.
    void getFacilityCapabilities().then((caps) => {
      if (!cancelled) setCapabilities(caps);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const tileCodes = useMemo(() => visibleKpiCodes(capabilities), [capabilities]);

  const latest = useMemo(() => latestByCode(items), [items]);
  const chartCodes = useMemo(
    () => (focusCode ? ([focusCode] as const) : tileCodes),
    [focusCode, tileCodes],
  );
  const chartData = useMemo(
    () => pivotForChart(items, chartCodes),
    [items, chartCodes],
  );
  const sparkDataAll = useMemo(() => pivotForChart(items, tileCodes), [items, tileCodes]);
  const windowLabel = useMemo(() => periodWindowLabel(items), [items]);
  const dayCount = useMemo(() => {
    const days = new Set(items.map((r) => r.period_start));
    return days.size;
  }, [items]);

  const handlePeriod = (_: React.MouseEvent<HTMLElement>, next: KpiPeriod | null) => {
    if (next) setPeriod(next);
  };

  const handleExport = async (format: ExportFormat) => {
    if (items.length === 0) {
      toast.error("Nothing to export for this period");
      return;
    }
    if (format === "pdf") {
      window.print();
      return;
    }
    const csv = snapshotsToCsv(items);
    const stamp = new Date().toISOString().slice(0, 10);
    downloadTextFile(
      `kpi_snapshots_${period}_${stamp}.csv`,
      csv,
      "text/csv;charset=utf-8",
    );
    if (format === "csv") toast.success("CSV downloaded");
    else toast.success("Downloaded as CSV (Excel-compatible)");
  };

  return (
    <Box
      id="mis-print-root"
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: 2.5,
        pb: 2,
      }}
    >
      {/* Hero header */}
      <Box
        sx={{
          position: "relative",
          overflow: "hidden",
          borderRadius: "20px",
          border: `1px solid ${meridian.border}`,
          background: `linear-gradient(135deg, #001f54 0%, #0a3a6e 48%, #1a5678 100%)`,
          boxShadow: "0 12px 40px rgb(0 31 84 / 0.18)",
          px: { xs: 2.5, md: 3.5 },
          py: { xs: 2.5, md: 3 },
          color: "#fff",
        }}
      >
        <Box
          aria-hidden
          sx={{
            position: "absolute",
            right: -40,
            top: -60,
            width: 220,
            height: 220,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgb(255 255 255 / 0.12) 0%, transparent 70%)",
            pointerEvents: "none",
          }}
        />
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          sx={{
            position: "relative",
            justifyContent: "space-between",
            alignItems: { xs: "stretch", md: "flex-end" },
          }}
        >
          <Box sx={{ position: "relative", zIndex: 1, minWidth: 0 }}>
            <Typography
              sx={{
                m: 0,
                mb: 0.75,
                fontSize: "0.6875rem",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "rgba(255, 255, 255, 0.8)",
              }}
            >
              Reports · MIS
            </Typography>
            <Typography
              component="h1"
              sx={{
                m: 0,
                fontSize: { xs: "1.625rem", md: "1.875rem" },
                fontWeight: 700,
                letterSpacing: "-0.03em",
                lineHeight: 1.2,
                color: "#ffffff",
              }}
            >
              Facility KPIs
            </Typography>
            <Typography
              sx={{
                m: 0,
                mt: 0.75,
                maxWidth: 480,
                fontSize: "0.875rem",
                lineHeight: 1.5,
                color: "rgba(255, 255, 255, 0.88)",
              }}
            >
              Daily kpi_snapshots for OPD wait and sharp injuries (schema
              examples · GET /reports/kpis when BE lands). Billing finance MIS
              uses /billing/mis/* below.
            </Typography>
          </Box>

          <Stack
            direction="row"
            useFlexGap
            sx={{ gap: 1.25, alignItems: "center", flexWrap: "wrap" }}
          >
            <ToggleButtonGroup
              exclusive
              size="small"
              value={period}
              onChange={handlePeriod}
              aria-label="KPI period"
              sx={{
                bgcolor: "rgb(255 255 255 / 0.1)",
                border: "1px solid rgb(255 255 255 / 0.22)",
                borderRadius: "12px",
                backdropFilter: "blur(8px)",
                "& .MuiToggleButton-root": {
                  border: 0,
                  px: 1.75,
                  color: "rgb(255 255 255 / 0.78)",
                  textTransform: "none",
                  fontWeight: 600,
                  fontSize: "0.8125rem",
                  "&.Mui-selected": {
                    bgcolor: "rgb(255 255 255 / 0.95)",
                    color: meridian.brandPrimary,
                    "&:hover": { bgcolor: "#fff" },
                  },
                  "&:hover": { bgcolor: "rgb(255 255 255 / 0.14)" },
                },
              }}
            >
              {PERIOD_OPTIONS.map((opt) => (
                <ToggleButton key={opt.value} value={opt.value}>
                  {opt.label}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
            {period === "custom" ? (
              <Stack
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                sx={{ width: { xs: "100%", sm: "auto" }, minWidth: 0 }}
              >
                <TextField
                  size="small"
                  type="date"
                  label="From"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  slotProps={{ inputLabel: { shrink: true } }}
                  sx={{
                    minWidth: { xs: 0, sm: 150 },
                    flex: { xs: "1 1 auto", sm: "0 1 170px" },
                    "& .MuiInputBase-root": {
                      bgcolor: "rgb(255 255 255 / 0.95)",
                      borderRadius: "10px",
                      fontSize: "0.8125rem",
                    },
                    "& .MuiInputLabel-root": {
                      color: "rgb(255 255 255 / 0.7)",
                      "&.Mui-focused": { color: "#fff" },
                    },
                  }}
                />
                <TextField
                  size="small"
                  type="date"
                  label="To"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  error={customRangeInvalid}
                  helperText={customRangeInvalid ? "Must be on or after From" : undefined}
                  slotProps={{ inputLabel: { shrink: true } }}
                  sx={{
                    minWidth: { xs: 0, sm: 150 },
                    flex: { xs: "1 1 auto", sm: "0 1 170px" },
                    "& .MuiInputBase-root": {
                      bgcolor: "rgb(255 255 255 / 0.95)",
                      borderRadius: "10px",
                      fontSize: "0.8125rem",
                    },
                    "& .MuiInputLabel-root": {
                      color: "rgb(255 255 255 / 0.7)",
                      "&.Mui-focused": { color: "#fff" },
                    },
                  }}
                />
              </Stack>
            ) : null}
            <ExportButton
              onExport={handleExport}
              formats={["csv", "pdf"]}
              size="small"
              disabled={loading || items.length === 0}
              sx={{
                bgcolor: "rgb(255 255 255 / 0.95)",
                color: meridian.brandPrimary,
                borderColor: "transparent",
                fontWeight: 700,
                "&:hover": { bgcolor: "#fff", borderColor: "transparent" },
              }}
            />
          </Stack>
        </Stack>
      </Box>

      {error ? (
        <Typography sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
          {error}
        </Typography>
      ) : null}

      <KpiSummaryBar
        period={period}
        windowLabel={windowLabel}
        snapshotCount={items.length}
        dayCount={dayCount}
        focusCode={focusCode}
        onClearFocus={() => setFocusCode(null)}
      />

      {/* Metric tiles */}
      <Box
        sx={{
          display: "grid",
          gap: 2,
          gridTemplateColumns: {
            xs: "1fr",
            sm: "repeat(2, 1fr)",
          },
        }}
      >
        {tileCodes.map((code) => {
          const snap = latest[code];
          const selected = focusCode === code;
          const muted = focusCode != null && !selected;
          const accent = KPI_SERIES_COLORS[code];
          const props = snap
            ? kpiSnapshotToMetricCardProps(snap)
            : { label: kpiLabel(code), value: "—", unit: undefined };
          const delta = deltaVsPrior(items, code);
          return (
            <MetricCard
              key={code}
              {...props}
              icon={KPI_ICONS[code]}
              delta={
                delta
                  ? {
                      value: formatDeltaLabel(delta.value, code),
                      direction: delta.direction,
                      label: "in window",
                    }
                  : undefined
              }
              loading={loading}
              onClick={() =>
                setFocusCode((prev) => (prev === code ? null : code))
              }
              aria-pressed={selected}
              sx={{
                cursor: "pointer",
                opacity: muted ? 0.55 : 1,
                transform: selected ? "translateY(-3px)" : "none",
                borderColor: selected ? `${accent}55` : undefined,
                background: selected
                  ? `linear-gradient(165deg, #ffffff 0%, ${accent}10 100%)`
                  : undefined,
                boxShadow: selected
                  ? `0 0 0 1px ${accent}40, 0 8px 20px ${accent}22, 0 16px 36px rgb(0 31 84 / 0.08)`
                  : undefined,
                transition:
                  "opacity 180ms ease, transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease, background 180ms ease",
                "&::before": {
                  width: selected ? 4 : 3,
                  opacity: selected ? 1 : muted ? 0.35 : 0.85,
                  background: selected
                    ? `linear-gradient(180deg, ${accent} 0%, ${accent}99 100%)`
                    : undefined,
                },
                "&:hover": {
                  opacity: 1,
                  transform: selected ? "translateY(-3px)" : "translateY(-2px)",
                  borderColor: selected ? `${accent}66` : "rgb(0 31 84 / 0.28)",
                  boxShadow: selected
                    ? `0 0 0 1px ${accent}50, 0 10px 24px ${accent}28, 0 18px 40px rgb(0 31 84 / 0.1)`
                    : "0 4px 12px rgb(0 31 84 / 0.08), 0 16px 32px rgb(0 31 84 / 0.08)",
                },
              }}
            />
          );
        })}
      </Box>

      <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.textSecondary }}>
        Click a tile to focus its trend; click again to show both. Values come from
        kpi_snapshots (computed daily).
      </Typography>

      <KpiTrendChart
        data={chartData}
        codes={chartCodes}
        loading={loading}
        title={
          focusCode ? `${kpiLabel(focusCode)} trend` : "Core KPI trends"
        }
        description={
          focusCode
            ? "Filled area for the selected series · hover for daily values"
            : "Multi-series line view (different units) · select a tile for a focused area chart"
        }
      />

      {/* Per-KPI sparklines when viewing all */}
      {!focusCode ? (
        <Box
          sx={{
            display: "grid",
            gap: 2,
            gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" },
          }}
        >
          {tileCodes.map((code) => (
            <Box
              key={code}
              onClick={() => setFocusCode(code)}
              sx={{ cursor: "pointer", "&:hover": { opacity: 0.95 } }}
            >
              <KpiSparklineCard
                code={code}
                data={sparkDataAll}
                loading={loading}
              />
            </Box>
          ))}
        </Box>
      ) : null}

      <KpiLatestTable latest={latest} loading={loading} />

      <BillingMisPanel />
    </Box>
  );
}
