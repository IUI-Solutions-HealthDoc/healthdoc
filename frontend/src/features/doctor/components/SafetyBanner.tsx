"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import type { AllergyAlert, AllergyAlertKind } from "../types";
import { useLocale } from "@/lib/i18n";

const TONE: Record<AllergyAlertKind, { bg: string; fg: string; border: string; label: string }> = {
  block: { bg: "#fee2e2", fg: meridian.danger, border: "rgb(185 28 28 / 0.22)", label: "Do not prescribe" },
  override_required: { bg: "#fef3c7", fg: meridian.warning, border: "rgb(180 83 9 / 0.22)", label: "Reason required" },
  uncheckable: { bg: "#e8eef5", fg: meridian.info, border: "rgb(0 31 84 / 0.16)", label: "Not checked" },
};

const ORDER: AllergyAlertKind[] = ["block", "override_required", "uncheckable"];

export interface SafetyBannerProps {
  alerts: AllergyAlert[];
  checking?: boolean;
}

/**
 * Allergy alerts, most severe first.
 *
 * There are no drug-interaction warnings here on purpose: interaction checking
 * is out of scope until a licensed database is available (schema v3.14). A
 * partial interaction list is more dangerous than none, because a clinician
 * reads silence as "checked and clear".
 */
export function SafetyBanner({ alerts, checking }: SafetyBannerProps) {
  const { t } = useLocale();
  if (checking && alerts.length === 0) {
    return (
      <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>{t("doctor.ui.checkingAllergies")}</Typography>
    );
  }
  if (alerts.length === 0) return null;

  const sorted = [...alerts].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));

  return (
    <Stack spacing={1}>
      {sorted.map((alert, i) => {
        const tone = TONE[alert.kind];
        return (
          <Box
            key={`${alert.medicine_name}-${i}`}
            sx={{
              display: "flex",
              gap: 1,
              alignItems: "baseline",
              flexWrap: "wrap",
              px: 1.5,
              py: 1,
              borderRadius: "12px",
              backgroundColor: tone.bg,
              border: `1px solid ${tone.border}`,
            }}
          >
            <Typography
              sx={{
                fontSize: "0.6875rem",
                fontWeight: 700,
                color: tone.fg,
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              {alert.medicine_name} · {tone.label}
            </Typography>
            <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary }}>
              {alert.message}
            </Typography>
          </Box>
        );
      })}
    </Stack>
  );
}
