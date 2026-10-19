"use client";

import { useEffect, useState } from "react";
import Button, { type ButtonProps } from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

export interface ReasonOption {
  label: string;
  value: string;
}

interface ReasonSelectionDialogProps {
  open: boolean;
  title: string;
  label?: string;
  reasons: ReasonOption[];
  defaultValue?: string;
  loading?: boolean;
  confirmText?: string;
  cancelText?: string;
  confirmColor?: ButtonProps["color"];
  helperText?: string;
  showRemarks?: boolean;
  defaultRemarks?: string;
  remarksLabel?: string;
  onClose: () => void;
  onConfirm: (data: { reason: string; remarks?: string }) => void;
}

export default function ReasonSelectionDialog({
  open,
  title,
  label = translate("inventory.adjustment.reason"),
  reasons,
  defaultValue = "",
  loading = false,
  confirmText = translate("common.save"),
  cancelText = translate("common.cancel"),
  confirmColor = "primary",
  helperText,
  showRemarks = false,
  defaultRemarks = "",
  remarksLabel = translate("lab.ui.remarks"),
  onClose,
  onConfirm,
}: ReasonSelectionDialogProps) {
  const [reason, setReason] = useState(defaultValue);
  const [remarks, setRemarks] = useState(defaultRemarks);

  useEffect(() => {
    if (open) {
      setReason(defaultValue);
      setRemarks(defaultRemarks);
    }
  }, [open, defaultValue, defaultRemarks]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
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
            disabled={!reason || loading}
            onClick={() =>
              onConfirm({
                reason,
                remarks: showRemarks ? remarks : undefined,
              })
            }
            sx={{ textTransform: "none", borderRadius: "10px", fontWeight: 600 }}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      <TextField
        select
        fullWidth
        margin="normal"
        label={label}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      >
        {reasons.map((item) => (
          <MenuItem key={item.value} value={item.value}>
            {item.label}
          </MenuItem>
        ))}
      </TextField>

      {helperText ? (
        <Typography variant="caption" sx={{ color: meridian.textSecondary }}>
          {helperText}
        </Typography>
      ) : null}

      {showRemarks ? (
        <TextField
          fullWidth
          multiline
          minRows={3}
          margin="normal"
          label={remarksLabel}
          value={remarks}
          onChange={(e) => setRemarks(e.target.value)}
        />
      ) : null}
    </Modal>
  );
}
