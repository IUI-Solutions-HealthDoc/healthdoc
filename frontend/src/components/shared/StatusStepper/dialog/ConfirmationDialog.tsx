"use client";

import Button, { type ButtonProps } from "@mui/material/Button";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

interface ConfirmationDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  confirmColor?: ButtonProps["color"];
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export default function ConfirmationDialog({
  open,
  title,
  description,
  confirmText = translate("receptionist.confirmAppointment"),
  cancelText = translate("common.cancel"),
  confirmColor = "primary",
  loading = false,
  onConfirm,
  onClose,
}: ConfirmationDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="xs"
      loading={loading}
      actions={
        <>
          <Button
            variant="outlined"
            onClick={onClose}
            disabled={loading}
            sx={{ textTransform: "none", borderRadius: "10px" }}
          >
            {cancelText}
          </Button>
          <Button
            variant="contained"
            color={confirmColor}
            onClick={onConfirm}
            disabled={loading}
            sx={{ textTransform: "none", borderRadius: "10px", fontWeight: 600 }}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      {description ? (
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary, lineHeight: 1.5 }}>
          {description}
        </Typography>
      ) : null}
    </Modal>
  );
}
