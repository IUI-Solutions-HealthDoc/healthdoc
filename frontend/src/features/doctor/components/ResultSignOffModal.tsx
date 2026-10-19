"use client";

import * as React from "react";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { doctorButtonSx } from "../panelSx";
import { useLocale } from "@/lib/i18n";

export interface ResultSignOffModalProps {
  open: boolean;
  busy: boolean;
  /** What is being signed, e.g. "CBC · LAB-20260731-00042". */
  subject: string;
  onClose: () => void;
  onConfirm: (note?: string) => void;
}

/**
 * Doctor sign-off confirmation. The note is optional and free-text — there is
 * no coded review-outcome vocabulary in the schema.
 */
export function ResultSignOffModal({
  open,
  busy,
  subject,
  onClose,
  onConfirm,
}: ResultSignOffModalProps) {
  const { t } = useLocale();
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    if (open) setNote("");
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("doctor.ui.signOffResult")}
      size="sm"
      disableClose={busy}
      actions={
        <>
          <Button variant="outlined" sx={doctorButtonSx} onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="contained"
            sx={doctorButtonSx}
            loading={busy}
            onClick={() => onConfirm(note.trim() || undefined)}
          >{t("doctor.ui.confirmSignOff")}</Button>
        </>
      }
    >
      <Stack spacing={2}>
        <Typography sx={{ fontSize: "0.875rem" }}>{t("doctor.ui.youAreRecordingThatYouHave")}{" "}<strong>{subject}</strong>.
        </Typography>
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("doctor.ui.signOffIsRecordedAgainstThe")}</Typography>
        <TextField
          label={t("doctor.ui.reviewNoteOptional")}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          multiline
          minRows={3}
          fullWidth
          placeholder={t("doctor.ui.eGPotassiumCriticalPatientRecalled")}
        />
      </Stack>
    </Modal>
  );
}
