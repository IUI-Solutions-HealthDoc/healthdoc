"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { BREAK_GLASS_JUSTIFICATION_MIN } from "../constants";
import { doctorButtonSx } from "../panelSx";

export interface BreakGlassWarningModalProps {
  open: boolean;
  busy: boolean;
  patientName: string;
  onClose: () => void;
  /** Resolves to an error message to show inline, or null on success. */
  onConfirm: (justification: string) => Promise<string | null>;
}

/**
 * Final warning and justification after Keycloak has completed MFA. TOTP is
 * never collected by this application; only Keycloak sees the credential.
 */
export function BreakGlassWarningModal({
  open,
  busy,
  patientName,
  onClose,
  onConfirm,
}: BreakGlassWarningModalProps) {
  const { t } = useLocale();
  const [justification, setJustification] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setJustification("");
    setError(null);
  }, [open]);

  const remaining = BREAK_GLASS_JUSTIFICATION_MIN - justification.trim().length;
  const justificationReady = remaining <= 0;

  const submit = async () => {
    const message = await onConfirm(justification.trim());
    if (message) {
      setError(message);
      return;
    }
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("doctor.breakGlassModalTitle")}
      size="sm"
      disableClose={busy}
      actions={
        <>
          <Button variant="outlined" sx={doctorButtonSx} disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="contained"
            color="error"
            sx={doctorButtonSx}
            loading={busy}
            disabled={!justificationReady}
            onClick={() => void submit()}
          >
            {t("doctor.breakGlassOpenAccess")}
          </Button>
        </>
      }
    >
      <Stack spacing={2}>
        <Box
          sx={{
            px: 1.75,
            py: 1.5,
            borderRadius: "12px",
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
              mb: 0.5,
            }}
          >
            {t("doctor.breakGlassEmergencyOverride")}
          </Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary, lineHeight: 1.55 }}>
            {t("doctor.breakGlassConfirmBody", { patientName })}
          </Typography>
        </Box>

        <TextField
          label={t("doctor.breakGlassJustificationLabel")}
          value={justification}
          onChange={(event) => {
            setError(null);
            setJustification(event.target.value);
          }}
          multiline
          minRows={3}
          fullWidth
          autoFocus
          error={Boolean(error)}
          placeholder="e.g. Unconscious trauma patient, need allergy and current medication history before surgery."
          helperText={
            error ??
            (justificationReady
              ? t("doctor.breakGlassJustificationStored")
              : remaining === 1
                ? t("doctor.breakGlassCharsRequired", { count: remaining })
                : t("doctor.breakGlassCharsRequiredPlural", { count: remaining }))
          }
        />
      </Stack>
    </Modal>
  );
}
