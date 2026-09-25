"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { useLocale } from "@/lib/i18n";
import { paymentModeLabel } from "../lib/labels";
import { formatINR } from "../lib/formatters";
import type { InvoiceWithItems, PaymentWithRefunds } from "../types";
import { PaymentStatusChip } from "./PaymentStatusChip";

type Props = {
  payment: PaymentWithRefunds;
  invoice: InvoiceWithItems;
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Stack direction="row" sx={{ justifyContent: "space-between", gap: 2, py: 0.5 }}>
      <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{label}</Typography>
      <Typography sx={{ fontSize: "0.8125rem", fontWeight: 600, color: meridian.textPrimary, textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

export function ImmutableReceipt({ payment, invoice }: Props) {
  // The real facility, from GET /users/me. This used to render a hardcoded
  // mock hospital name — on a RECEIPT, which is a document the patient keeps
  // and may present for reimbursement. A wrong name here is worse than a
  // missing one, so it renders nothing rather than a placeholder while the
  // session loads.
  const { user: currentUser } = useCurrentUser();
  const { localizeField, t } = useLocale();

  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        p: 2.5,
      }}
    >
      <Stack direction="row" sx={{ justifyContent: "space-between", mb: 2, gap: 2 }}>
        <Box>
          <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
            {t("billing.receipt.immutableTitle")}
          </Typography>
          <Typography sx={{ m: 0, mt: 0.35, fontSize: "0.75rem", color: meridian.textSecondary }}>
            {t("billing.receipt.immutableHint")}
          </Typography>
        </Box>
        <PaymentStatusChip status={payment.status} />
      </Stack>

      <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary, mb: 1.5 }}>
        {localizeField(currentUser?.facility.name ?? "", currentUser?.facility.name_hi)}
      </Typography>

      <Row label={t("billing.receipt.receiptNo")} value={payment.receipt_number} />
      <Row label={t("billing.receipt.invoiceNo")} value={invoice.invoice_number} />
      <Row
        label={t("billing.receipt.patient")}
        value={`${invoice.patient?.full_name ?? invoice.patient_id} (${invoice.patient?.uhid ?? "—"})`}
      />
      <Row label={t("billing.receipt.amount")} value={formatINR(payment.amount)} />
      <Row label={t("billing.receipt.currency")} value={payment.currency} />
      <Row label={t("billing.receipt.mode")} value={paymentModeLabel(t, payment.mode)} />
      <Row label={t("billing.receipt.collectedBy")} value={payment.collected_by} />
      <Row
        label={t("billing.receipt.collectedAt")}
        value={new Intl.DateTimeFormat("en-IN", {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(payment.collected_at))}
      />

      {payment.refunds.length > 0 ? (
        <Box sx={{ mt: 2, pt: 1.5, borderTop: `1px solid ${meridian.border}` }}>
          <Typography sx={{ fontSize: "0.8125rem", fontWeight: 700, mb: 1 }}>{t("billing.receipt.refunds")}</Typography>
          {payment.refunds.map((r) => (
            <Typography key={r.id} sx={{ fontSize: "0.75rem", color: meridian.textSecondary, mb: 0.5 }}>
              {r.refund_number} · {formatINR(r.amount)} · {r.reason}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}
