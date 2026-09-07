"use client";

import { useEffect, useMemo, useState } from "react";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { formatINR } from "../lib/formatters";
import { extractValidationErrors } from "../lib/errors";
import { fromMoney, round2, toMoney } from "../lib/money";
import type { CreateRefundInput, PaymentWithRefunds } from "../types";

type Props = {
  open: boolean;
  payment: PaymentWithRefunds | null;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (body: CreateRefundInput) => Promise<void> | void;
};

export function ReversalFormModal({ open, payment, busy, onClose, onSubmit }: Props) {
  const maxRefund = useMemo(() => {
    if (!payment) return 0;
    const already = payment.refunds.reduce((s, r) => s + fromMoney(r.amount), 0);
    return round2(Math.max(0, fromMoney(payment.amount) - already));
  }, [payment]);

  const [amount, setAmount] = useState(maxRefund);
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAmount(maxRefund);
      setReason("");
      setFieldErrors({});
      setErrorMessage(null);
    }
  }, [open, maxRefund]);

  if (!payment) return null;

  const handleSave = async () => {
    setFieldErrors({});
    setErrorMessage(null);

    const trimmedReason = reason.trim();
    if (!trimmedReason) {
      setFieldErrors((prev) => ({ ...prev, reason: "A reversal reason is required." }));
      setErrorMessage("Please enter a reason for the reversal.");
      return;
    }
    if (amount <= 0) {
      setFieldErrors((prev) => ({ ...prev, amount: "Refund amount must be greater than ₹0.00" }));
      setErrorMessage("Please enter an amount greater than ₹0.00");
      return;
    }
    if (amount > maxRefund + 0.001) {
      setFieldErrors((prev) => ({ ...prev, amount: `Refund cannot exceed ${formatINR(maxRefund)}` }));
      setErrorMessage(`Refund amount cannot exceed the maximum reversible amount of ${formatINR(maxRefund)}`);
      return;
    }

    try {
      await onSubmit({
        amount: toMoney(amount),
        reason: trimmedReason,
      });
      onClose();
    } catch (err) {
      const extracted = extractValidationErrors(err);
      setFieldErrors(extracted.fieldErrors);
      setErrorMessage(extracted.summary || (err instanceof Error ? err.message : "Reversal failed"));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reverse payment"
      size="sm"
      loading={busy}
      actions={
        <>
          <Button onClick={onClose} sx={{ textTransform: "none" }} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleSave()}
            disabled={busy}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Confirm reversal
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
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>
          Original receipt <strong>{payment.receipt_number}</strong> stays immutable. A separate
          refund row (RFD-…) will be created.
        </Typography>
        <TextField
          type="number"
          label="Refund amount (₹)"
          size="small"
          value={amount}
          error={Boolean(fieldErrors.amount)}
          helperText={fieldErrors.amount || `Max reversible: ${formatINR(maxRefund)}`}
          onChange={(e) => {
            setAmount(Number(e.target.value) || 0);
            if (fieldErrors.amount) {
              setFieldErrors((prev) => ({ ...prev, amount: "" }));
            }
          }}
          slotProps={{ htmlInput: { min: 0, step: 1, max: maxRefund } }}
          fullWidth
        />
        <TextField
          label="Reason"
          size="small"
          value={reason}
          error={Boolean(fieldErrors.reason)}
          onChange={(e) => {
            setReason(e.target.value);
            if (fieldErrors.reason) {
              setFieldErrors((prev) => ({ ...prev, reason: "" }));
            }
          }}
          required
          fullWidth
          multiline
          minRows={2}
          helperText={fieldErrors.reason || "Required — refunds.reason"}
        />
      </Stack>
    </Modal>
  );
}
