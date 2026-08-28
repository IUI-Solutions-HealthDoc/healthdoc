"use client";

import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { PAYMENT_MODE_LABELS } from "../constants";
import { formatINR } from "../lib/formatters";
import { fromMoney, type Money } from "../lib/money";
import type {
  CollectPaymentInput,
  CreateRefundInput,
  InvoiceWithItems,
  PaymentWithRefunds,
} from "../types";
import { CollectPaymentModal } from "./CollectPaymentModal";
import { ImmutableReceipt } from "./ImmutableReceipt";
import { PaymentStatusChip } from "./PaymentStatusChip";
import { ReceiptPrintView } from "./ReceiptPrintView";
import { ReversalFormModal } from "./ReversalFormModal";

type Props = {
  invoice: InvoiceWithItems;
  payments: PaymentWithRefunds[];
  loading?: boolean;
  busy?: boolean;
  balanceDue: Money;
  paidTotal: Money;
  refundedTotal: Money;
  canCollect: boolean;
  onCollect: (body: CollectPaymentInput) => Promise<void>;
  onRefund: (paymentId: string, body: CreateRefundInput) => Promise<void>;
};

export function PaymentsPanel({
  invoice,
  payments,
  loading,
  busy,
  balanceDue,
  paidTotal,
  refundedTotal,
  canCollect,
  onCollect,
  onRefund,
}: Props) {
  const [collectOpen, setCollectOpen] = useState(false);
  const [selected, setSelected] = useState<PaymentWithRefunds | null>(null);
  const [reverseTarget, setReverseTarget] = useState<PaymentWithRefunds | null>(null);
  const [printTarget, setPrintTarget] = useState<PaymentWithRefunds | null>(null);

  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        p: 2.5,
      }}
    >
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{ justifyContent: "space-between", alignItems: { sm: "center" }, gap: 2, mb: 2 }}
      >
        <Box>
          <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
            Payments
          </Typography>
          <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
            Immutable receipts · print · reversal (migration 0014)
          </Typography>
        </Box>
        <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: "wrap" }}>
          <Button
            size="small"
            variant="contained"
            disabled={!canCollect || busy || fromMoney(balanceDue) <= 0}
            onClick={() => setCollectOpen(true)}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Collect payment
          </Button>
        </Stack>
      </Stack>

      <Stack
        direction={{ xs: "column", sm: "row" }}
        useFlexGap
        sx={{ gap: 2, mb: 2.5, flexWrap: "wrap" }}
      >
        <Stat label="Net amount" value={formatINR(invoice.net_amount)} />
        <Stat label="Paid" value={formatINR(paidTotal)} />
        <Stat label="Refunded" value={formatINR(refundedTotal)} />
        <Stat label="Balance due" value={formatINR(balanceDue)} emphasize />
      </Stack>

      {loading ? (
        <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>
          Loading payments…
        </Typography>
      ) : payments.length === 0 ? (
        <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>
          No payments yet. Collect to mint an RCP-… receipt.
        </Typography>
      ) : (
        <Stack spacing={1.25}>
          {payments.map((p) => {
            const active = selected?.id === p.id;
            return (
              <Box
                key={p.id}
                sx={{
                  borderRadius: "12px",
                  border: `1px solid ${active ? meridian.brandPrimary : meridian.border}`,
                  bgcolor: active ? "rgb(0 31 84 / 0.04)" : meridian.surface,
                  p: 1.75,
                }}
              >
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  sx={{ justifyContent: "space-between", gap: 1.5 }}
                >
                  <Box
                    component="button"
                    type="button"
                    onClick={() => setSelected(active ? null : p)}
                    sx={{
                      border: 0,
                      background: "transparent",
                      p: 0,
                      textAlign: "left",
                      cursor: "pointer",
                      flex: 1,
                    }}
                  >
                    <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1, mb: 0.5 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: "0.875rem" }}>
                        {p.receipt_number}
                      </Typography>
                      <PaymentStatusChip status={p.status} />
                    </Stack>
                    <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                      {formatINR(p.amount)} · {PAYMENT_MODE_LABELS[p.mode]} · {p.collected_by}
                    </Typography>
                  </Box>
                  <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: "wrap" }}>
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => setPrintTarget(p)}
                      sx={{ textTransform: "none", borderRadius: "10px" }}
                    >
                      Print
                    </Button>
                    {p.status === "success" ? (
                      <Button
                        size="small"
                        variant="outlined"
                        color="error"
                        disabled={busy}
                        onClick={() => setReverseTarget(p)}
                        sx={{ textTransform: "none", borderRadius: "10px" }}
                      >
                        Reverse
                      </Button>
                    ) : null}
                  </Stack>
                </Stack>
              </Box>
            );
          })}
        </Stack>
      )}

      {selected ? (
        <Box sx={{ mt: 2.5 }}>
          <ImmutableReceipt payment={selected} invoice={invoice} />
        </Box>
      ) : null}

      <CollectPaymentModal
        open={collectOpen}
        balanceDue={fromMoney(balanceDue)}
        busy={busy}
        onClose={() => setCollectOpen(false)}
        onSubmit={async (body) => {
          await onCollect(body);
          setCollectOpen(false);
        }}
      />

      <ReversalFormModal
        open={Boolean(reverseTarget)}
        payment={reverseTarget}
        busy={busy}
        onClose={() => setReverseTarget(null)}
        onSubmit={async (body) => {
          if (!reverseTarget) return;
          await onRefund(reverseTarget.id, body);
          setReverseTarget(null);
          setSelected(null);
        }}
      />

      <ReceiptPrintView
        open={Boolean(printTarget)}
        payment={printTarget}
        invoice={invoice}
        onClose={() => setPrintTarget(null)}
        onPrint={() => window.print()}
      />
    </Box>
  );
}

function Stat({
  label,
  value,
  emphasize,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <Box sx={{ minWidth: 120 }}>
      <Typography sx={{ fontSize: "0.6875rem", fontWeight: 600, color: meridian.textSecondary }}>
        {label}
      </Typography>
      <Typography
        sx={{
          fontSize: emphasize ? "1.125rem" : "0.9375rem",
          fontWeight: 700,
          color: meridian.textPrimary,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}
