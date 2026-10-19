"use client";

import type { ReactNode } from "react";
import Button, { type ButtonProps } from "@mui/material/Button";

import { Modal } from "@/components/ui/Modal";
import { translate } from "@/lib/i18n";

interface FormDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  maxWidth?: "xs" | "sm" | "md" | "lg" | "xl";
  loading?: boolean;
  saveText?: string;
  cancelText?: string;
  saveColor?: ButtonProps["color"];
  disableSave?: boolean;
  onClose: () => void;
  onSave: () => void;
}

export default function FormDialog({
  open,
  title,
  children,
  maxWidth = "sm",
  loading = false,
  saveText = translate("common.save"),
  cancelText = translate("common.cancel"),
  saveColor = "primary",
  disableSave = false,
  onClose,
  onSave,
}: FormDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size={maxWidth}
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
            color={saveColor}
            disabled={disableSave || loading}
            onClick={onSave}
            sx={{ textTransform: "none", borderRadius: "10px", fontWeight: 600 }}
          >
            {saveText}
          </Button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
