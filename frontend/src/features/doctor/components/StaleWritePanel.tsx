"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import type { SoapNote } from "./SoapNotePanel";
import type { UpdateEncounterInput } from "../types";
import { useLocale, translate } from "@/lib/i18n";

const FIELDS: { key: keyof SoapNote; label: string }[] = [
  { key: "subjective", get label() { return translate("doctor.soapSubjective"); } },
  { key: "objective", get label() { return translate("doctor.soapObjective"); } },
  { key: "assessment", get label() { return translate("doctor.soapAssessment"); } },
  { key: "plan", get label() { return translate("doctor.soapPlan"); } },
];

export interface StaleWritePanelProps {
  yours: SoapNote;
  theirs: UpdateEncounterInput;
}

/**
 * Shown when a save is refused because someone else wrote first (409
 * stale_write). Both versions are displayed side by side and NOTHING is
 * overwritten — the clinician decides what survives. Silently keeping either
 * copy would destroy a colleague's clinical note.
 */
export function StaleWritePanel({ yours, theirs }: StaleWritePanelProps) {
  const { t } = useLocale();
  const changed = FIELDS.filter((f) => (yours[f.key] ?? "") !== (theirs[f.key] ?? ""));

  return (
    <Box
      sx={{
        px: 2,
        py: 1.75,
        borderRadius: "16px",
        backgroundColor: "#fee2e2",
        border: "1px solid rgb(185 28 28 / 0.22)",
      }}
    >
      <Typography
        sx={{
          fontSize: "0.6875rem",
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: meridian.danger,
          mb: 0.75,
        }}
      >{t("doctor.ui.notSavedThisEncounterChangedWhile")}</Typography>
      <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary, mb: 1.5 }}>{t("doctor.ui.yourNoteWas")}{" "}<strong>{t("doctor.ui.not")}</strong>{" "}{t("doctor.ui.storedAndNothingOfTheirsWas")}</Typography>

      {changed.length === 0 ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("doctor.ui.theTextIsIdenticalOnlyThe")}</Typography>
      ) : (
        <Stack spacing={1.25}>
          {changed.map((f) => (
            <Box key={f.key}>
              <Typography
                sx={{
                  fontSize: "0.6875rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: meridian.textSecondary,
                  mb: 0.5,
                }}
              >
                {f.label}
              </Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
                <Box
                  sx={{
                    p: 1,
                    borderRadius: "8px",
                    backgroundColor: meridian.surface,
                    border: `1px solid ${meridian.border}`,
                  }}
                >
                  <Typography sx={{ fontSize: "0.6875rem", color: meridian.textSecondary }}>{t("doctor.ui.yours")}</Typography>
                  <Typography sx={{ fontSize: "0.8125rem", whiteSpace: "pre-wrap" }}>
                    {yours[f.key] || "—"}
                  </Typography>
                </Box>
                <Box
                  sx={{
                    p: 1,
                    borderRadius: "8px",
                    backgroundColor: meridian.surface,
                    border: `1px solid ${meridian.border}`,
                  }}
                >
                  <Typography sx={{ fontSize: "0.6875rem", color: meridian.textSecondary }}>{t("doctor.ui.onTheServer")}</Typography>
                  <Typography sx={{ fontSize: "0.8125rem", whiteSpace: "pre-wrap" }}>
                    {theirs[f.key] || "—"}
                  </Typography>
                </Box>
              </Box>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}
