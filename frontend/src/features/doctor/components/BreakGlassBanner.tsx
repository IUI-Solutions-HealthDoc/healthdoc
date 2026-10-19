"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { formatCountdown, formatDateTime } from "../lib/formatters";
import { doctorButtonSx } from "../panelSx";
import type { BreakGlassGrant } from "../types";
import { useLocale } from "@/lib/i18n";

export interface BreakGlassBannerProps {
  grant: BreakGlassGrant;
  msRemaining: number;
  busy: boolean;
  onRevoke: () => void;
}

/**
 * Sits above the record for as long as the grant is open, so the clinician can
 * never forget they are working under an emergency override. The clock counts
 * to the grant's own expires_at (see useBreakGlass).
 */
export function BreakGlassBanner({ grant, msRemaining, busy, onRevoke }: BreakGlassBannerProps) {
  const { t } = useLocale();
  return (
    <Box
      sx={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 1.5,
        px: 2,
        py: 1.5,
        borderRadius: "16px",
        backgroundColor: "#fee2e2",
        border: "1px solid rgb(185 28 28 / 0.22)",
      }}
    >
      <Stack spacing={0.5}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", gap: 0.75 }}>
          <StatusChip status="emergency" />
          <Typography
            sx={{
              fontSize: "0.9375rem",
              fontWeight: 700,
              color: meridian.danger,
              fontVariantNumeric: "tabular-nums",
            }}
          >{t("doctor.ui.msremainingLeft", { msRemaining: formatCountdown(msRemaining) })}</Typography>
        </Stack>
        <Typography sx={{ fontSize: "0.75rem", color: meridian.textPrimary }}>{t("doctor.ui.emergencyAccessIsOpenAndBeing", { expires_at: formatDateTime(grant.expires_at) })}</Typography>
      </Stack>

      <Button variant="outlined" color="error" sx={doctorButtonSx} loading={busy} onClick={onRevoke}>{t("doctor.ui.endAccessNow")}</Button>
    </Box>
  );
}
