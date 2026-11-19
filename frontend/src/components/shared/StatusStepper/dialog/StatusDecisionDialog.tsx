"use client";

import { useEffect, useState } from "react";
import Button, { type ButtonProps } from "@mui/material/Button";
import FormControlLabel from "@mui/material/FormControlLabel";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

export interface DecisionOption {
  label: string;
  value: string;
}

interface StatusDecisionDialogProps {
  open: boolean;
  title: string;
  description?: string;
  options: DecisionOption[];
  defaultValue?: string;
  loading?: boolean;
  confirmText?: string;
  cancelText?: string;
  confirmColor?: ButtonProps["color"];
  onClose: () => void;
  onConfirm: (value: string) => void;
}

export default function StatusDecisionDialog({
  open,
  title,
  description,
  options,
  defaultValue = "",
  loading = false,
  confirmText = translate("doctor.queueContinue"),
  cancelText = translate("common.cancel"),
  confirmColor = "primary",
  onClose,
  onConfirm,
}: StatusDecisionDialogProps) {
  const [selected, setSelected] = useState(defaultValue);

  useEffect(() => {
    if (open) {
      setSelected(defaultValue);
    }
  }, [open, defaultValue]);

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
            disabled={!selected || loading}
            onClick={() => onConfirm(selected)}
            sx={{ textTransform: "none", borderRadius: "10px", fontWeight: 600 }}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      {description ? (
        <Typography
          sx={{ mb: 2, fontSize: "0.875rem", color: meridian.textSecondary }}
        >
          {description}
        </Typography>
      ) : null}

      <RadioGroup value={selected} onChange={(e) => setSelected(e.target.value)}>
        {options.map((option) => (
          <FormControlLabel
            key={option.value}
            value={option.value}
            control={<Radio />}
            label={option.label}
          />
        ))}
      </RadioGroup>
    </Modal>
  );
}
