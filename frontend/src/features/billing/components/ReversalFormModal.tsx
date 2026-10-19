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
import { useLocale, translate } from "@/lib/i18n";

type Props = {
  open: boolean;
  payment: PaymentWithRefunds | null;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (body: CreateRefundInput) => Promise<void> | void;
};

export function ReversalFormModal({ open, payment, busy, onClose, onSubmit }: Props) {
  const { t } = useLocale();
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
      setFieldErrors((prev) => ({ ...prev, reason: translate("billing.msg.reversalReasonRequired") }));
      setErrorMessage(translate("billing.msg.pleaseEnterAReasonForThe"));
      return;
    }
    if (amount <= 0) {
      setFieldErrors((prev) => ({ ...prev, amount: translate("billing.msg.refundAmountMustBeGreaterThan") }));
      setErrorMessage(translate("billing.collect.errEnterAmount"));
      return;
    }
    if (amount > maxRefund + 0.001) {
      setFieldErrors((prev) => ({ ...prev, amount: translate("billing.msg.refundCannotExceedMaxrefund", undefined, { maxRefund: formatINR(maxRefund) }) }));
      setErrorMessage(translate("billing.msg.refundAmountCannotExceedTheMaximum", undefined, { maxRefund: formatINR(maxRefund) }));
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
      setErrorMessage(extracted.summary || (err instanceof Error ? err.message : translate("billing.msg.reversalFailed")));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("billing.ui.reversePayment")}
      size="sm"
      loading={busy}
      actions={
        <>
          <Button onClick={onClose} sx={{ textTransform: "none" }} disabled={busy}>{t("common.cancel")}</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleSave()}
            disabled={busy}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >{t("billing.ui.confirmReversal")}</Button>
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
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>{t("billing.ui.originalReceipt")}{" "}<strong>{payment.receipt_number}</strong>{" "}{t("billing.ui.staysImmutableASeparateRefundRow")}</Typography>
        <TextField
          type="number"
          label={t("billing.ui.refundAmount")}
          size="small"
          value={amount}
          error={Boolean(fieldErrors.amount)}
          helperText={fieldErrors.amount || translate("billing.msg.maxReversibleMaxrefund", undefined, { maxRefund: formatINR(maxRefund) })}
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
          label={t("inventory.adjustment.reason")}
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
          helperText={fieldErrors.reason || t("billing.ui.requiredRefundsReason")}
        />
      </Stack>
    </Modal>
  );
}
