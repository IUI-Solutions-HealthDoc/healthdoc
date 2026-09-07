"use client";

import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { PAYMENT_MODE_LABELS } from "../constants";
import { extractValidationErrors } from "../lib/errors";
import { toMoney } from "../lib/money";
import type { CollectPaymentInput, PaymentMode } from "../types";

type Props = {
  open: boolean;
  balanceDue: number;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (body: CollectPaymentInput) => Promise<void> | void;
};

const MODES = Object.keys(PAYMENT_MODE_LABELS) as PaymentMode[];

export function CollectPaymentModal({
  open,
  balanceDue,
  busy,
  onClose,
  onSubmit,
}: Props) {
  const [amount, setAmount] = useState(balanceDue);
  const [mode, setMode] = useState<PaymentMode>("cash");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAmount(balanceDue);
      setMode("cash");
      setFieldErrors({});
      setErrorMessage(null);
    }
  }, [open, balanceDue]);

  const handleSave = async () => {
    setFieldErrors({});
    setErrorMessage(null);

    if (amount <= 0) {
      setFieldErrors({ amount: "Amount must be greater than ₹0.00" });
      setErrorMessage("Please enter an amount greater than ₹0.00");
      return;
    }
    if (amount > balanceDue + 0.001) {
      setFieldErrors({ amount: `Amount cannot exceed balance due of ₹${balanceDue.toFixed(2)}` });
      setErrorMessage(`Amount cannot exceed the remaining balance of ₹${balanceDue.toFixed(2)}`);
      return;
    }

    try {
      await onSubmit({
        amount: toMoney(amount),
        mode,
        currency: "INR",
      });
      onClose();
    } catch (err) {
      const extracted = extractValidationErrors(err);
      setFieldErrors(extracted.fieldErrors);
      setErrorMessage(extracted.summary || (err instanceof Error ? err.message : "Payment failed"));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Collect payment"
      size="sm"
      loading={busy}
      actions={
        <>
          <Button onClick={onClose} sx={{ textTransform: "none" }} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleSave()}
            disabled={busy}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Collect
          </Button>
        </>
      }
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        {errorMessage ? (
          <Typography
            role="alert"
            sx={{
              p: 1.25,
              borderRadius: "10px",
              backgroundColor: "rgb(239 68 68 / 0.08)",
              border: `1px solid rgb(239 68 68 / 0.25)`,
              color: meridian.danger,
              fontSize: "0.8125rem",
              fontWeight: 500,
            }}
          >
            {errorMessage}
          </Typography>
        ) : null}
        <TextField
          type="number"
          label="Amount (₹)"
          size="small"
          value={amount}
          error={Boolean(fieldErrors.amount)}
          helperText={fieldErrors.amount || `Balance due: ₹${balanceDue.toFixed(2)}`}
          onChange={(e) => {
            setAmount(Number(e.target.value) || 0);
            if (fieldErrors.amount) {
              setFieldErrors((prev) => ({ ...prev, amount: "" }));
            }
          }}
          slotProps={{ htmlInput: { min: 0, step: 1, max: balanceDue } }}
          fullWidth
        />
        <TextField
          select
          label="Mode"
          size="small"
          value={mode}
          error={Boolean(fieldErrors.mode)}
          helperText={fieldErrors.mode}
          onChange={(e) => {
            setMode(e.target.value as PaymentMode);
            if (fieldErrors.mode) {
              setFieldErrors((prev) => ({ ...prev, mode: "" }));
            }
          }}
          fullWidth
        >
          {MODES.map((m) => (
            <MenuItem key={m} value={m}>
              {PAYMENT_MODE_LABELS[m]}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
    </Modal>
  );
}
