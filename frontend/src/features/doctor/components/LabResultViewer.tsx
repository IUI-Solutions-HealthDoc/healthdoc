"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import type { LabResult } from "../types";
import { useLocale } from "@/lib/i18n";

const headCellSx = {
  fontSize: "0.6875rem",
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: meridian.textSecondary,
  py: 1,
  px: 1.5,
  borderBottom: `1px solid ${meridian.border}`,
  textAlign: "left",
} as const;

const cellSx = {
  fontSize: "0.8125rem",
  py: 1.15,
  px: 1.5,
  borderBottom: `1px solid ${meridian.border}`,
} as const;

/** Nested objects/arrays are shown as JSON rather than guessed at. */
function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export interface LabResultViewerProps {
  result: LabResult;
}

/**
 * Renders whatever the lab actually sent.
 *
 * `result_data` is `jsonb` with no agreed inner shape, so this deliberately does
 * NOT parse values, compare them to reference ranges, or decide what is
 * critical. Deriving a critical flag from an unspecified payload would be a
 * guess presented as a clinical judgement.
 */
export function LabResultViewer({ result }: LabResultViewerProps) {
  const { t } = useLocale();
  const entries = Object.entries(result.result_data ?? {});

  return (
    <Stack spacing={2}>
      {entries.length === 0 ? (
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>{t("doctor.ui.theLabReturnedNoResultValues")}</Typography>
      ) : (
        <Box sx={{ overflowX: "auto" }}>
          <Box component="table" sx={{ width: "100%", borderCollapse: "collapse", minWidth: 420 }}>
            <Box component="thead">
              <Box component="tr">
                <Box component="th" sx={headCellSx}>{t("doctor.ui.analyte")}</Box>
                <Box component="th" sx={{ ...headCellSx, textAlign: "right" }}>{t("common.ui.result")}</Box>
              </Box>
            </Box>
            <Box component="tbody">
              {entries.map(([key, value]) => (
                <Box component="tr" key={key}>
                  <Box component="td" sx={{ ...cellSx, fontWeight: 500 }}>
                    {key}
                  </Box>
                  <Box
                    component="td"
                    sx={{ ...cellSx, textAlign: "right", fontVariantNumeric: "tabular-nums" }}
                  >
                    {renderValue(value)}
                  </Box>
                </Box>
              ))}
            </Box>
          </Box>
        </Box>
      )}

      {result.remarks && (
        <Box
          sx={{
            px: 1.5,
            py: 1.25,
            borderRadius: "12px",
            border: `1px solid ${meridian.border}`,
            backgroundColor: meridian.muted,
          }}
        >
          <Typography sx={{ ...headCellSx, px: 0, py: 0, borderBottom: "none", mb: 0.5 }}>{t("doctor.ui.labRemarks")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem" }}>{result.remarks}</Typography>
        </Box>
      )}
    </Stack>
  );
}
