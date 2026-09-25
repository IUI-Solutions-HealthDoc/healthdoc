"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { doctorPanelSx } from "../panelSx";
import type { NoteStatus } from "../types";

export interface SoapNote {
  subjective: string;
  objective: string;
  assessment: string;
  plan: string;
}

const SOAP_FIELDS: { key: keyof SoapNote; labelKey: MessageKey; hintKey: MessageKey }[] = [
  { key: "subjective", labelKey: "doctor.soapSubjective", hintKey: "doctor.soapSubjectiveHint" },
  { key: "objective", labelKey: "doctor.soapObjective", hintKey: "doctor.soapObjectiveHint" },
  { key: "assessment", labelKey: "doctor.soapAssessment", hintKey: "doctor.soapAssessmentHint" },
  { key: "plan", labelKey: "doctor.soapPlan", hintKey: "doctor.soapPlanHint" },
];

export interface SoapNotePanelProps {
  value: SoapNote;
  noteStatus: NoteStatus;
  onChange: (patch: Partial<SoapNote>) => void;
}

/**
 * The SOAP note. Saved on PATCH /encounters/{id} — never on the POST, which
 * does not accept these fields.
 *
 * note_status is shown, not hidden: `failed` means the long-form note did not
 * reach its store, and a note that silently vanished is far worse than one the
 * clinician knows to re-enter.
 */
export function SoapNotePanel({ value, noteStatus, onChange }: SoapNotePanelProps) {
  const { t } = useLocale();

  const statusLabel =
    noteStatus === "stored"
      ? t("doctor.soapStatusStored")
      : noteStatus === "failed"
        ? t("doctor.soapStatusFailed")
        : t("doctor.soapStatusPending");

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 1 }}
      >
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.soapTitle")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {t("doctor.soapSubtitle")}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>{t("doctor.soapNoteLabel")}</Typography>
          <StatusChip status={noteStatus} label={statusLabel} />
        </Stack>
      </Stack>

      {noteStatus === "failed" && (
        <Box
          sx={{
            px: 1.5,
            py: 1.25,
            borderRadius: "12px",
            backgroundColor: "#fee2e2",
            border: "1px solid rgb(185 28 28 / 0.22)",
          }}
        >
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary }}>
            {t("doctor.soapFailedBanner")}
          </Typography>
        </Box>
      )}

      <Stack spacing={2}>
        {SOAP_FIELDS.map((b) => (
          <TextField
            key={b.key}
            label={t(b.labelKey)}
            helperText={t(b.hintKey)}
            value={value[b.key]}
            onChange={(e) => onChange({ [b.key]: e.target.value })}
            multiline
            minRows={2}
            fullWidth
          />
        ))}
      </Stack>
    </Box>
  );
}
