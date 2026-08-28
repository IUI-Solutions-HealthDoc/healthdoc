"use client";

import { useEffect, useMemo, useState } from "react";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { formatINR } from "../lib/formatters";
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

  useEffect(() => {
    if (open) {
      setAmount(maxRefund);
      setReason("");
    }
  }, [open, maxRefund]);

  if (!payment) return null;

  const handleSave = async () => {
    if (!reason.trim() || amount <= 0 || amount > maxRefund + 0.001) return;
    await onSubmit({
      amount: toMoney(amount),
      reason: reason.trim(),
    });
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
            disabled={busy || !reason.trim() || amount <= 0 || amount > maxRefund + 0.001}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Confirm reversal
          </Button>
        </>
      }
    >
      <Stack spacing={2} sx={{ pt: 1 }}>
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>
          Original receipt <strong>{payment.receipt_number}</strong> stays immutable. A separate
          refund row (RFD-…) will be created.
        </Typography>
        <TextField
          type="number"
          label="Refund amount (₹)"
          size="small"
          value={amount}
          onChange={(e) => setAmount(Number(e.target.value) || 0)}
          slotProps={{ htmlInput: { min: 0, step: 1, max: maxRefund } }}
          helperText={`Max reversible: ${formatINR(maxRefund)}`}
          fullWidth
        />
        <TextField
          label="Reason"
          size="small"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
          fullWidth
          multiline
          minRows={2}
          helperText="Required — refunds.reason"
        />
      </Stack>
    </Modal>
  );
}
