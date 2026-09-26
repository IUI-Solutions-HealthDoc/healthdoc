"use client";

import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { meridian } from "@/styles/theme";
import { useLocale } from "@/lib/i18n";
import { chargeCategoryLabel } from "../lib/labels";
import { formatINR } from "../lib/formatters";
import type { InvoiceWithItems } from "../types";

type Props = {
  open: boolean;
  invoice: InvoiceWithItems | null;
  canIssue: boolean;
  busy?: boolean;
  onClose: () => void;
  onIssue: () => void;
};

export function InvoicePreviewModal({
  open,
  invoice,
  canIssue,
  busy,
  onClose,
  onIssue,
}: Props) {
  const { t } = useLocale();
  if (!invoice) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Invoice preview"
      size="md"
      loading={busy}
      actions={
        <>
          <Button onClick={onClose} sx={{ textTransform: "none" }}>
            Close
          </Button>
          {canIssue ? (
            <Button
              variant="contained"
              onClick={onIssue}
              sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
            >
              Issue invoice
            </Button>
          ) : null}
        </>
      }
    >
      <Stack spacing={2}>
        <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>
          {invoice.invoice_number} · {invoice.patient?.full_name} ({invoice.patient?.uhid}) · Scheme:{" "}
          {invoice.scheme_code ?? "Self-pay"}
        </Typography>

        <Stack spacing={1}>
          {invoice.items.map((item) => (
            <Stack
              key={item.id}
              direction="row"
              sx={{ justifyContent: "space-between", gap: 2 }}
            >
              <Typography sx={{ fontSize: "0.875rem", color: meridian.textPrimary }}>
                {chargeCategoryLabel(t, item.charge_category)} — {item.description} ×{" "}
                {item.quantity}
              </Typography>
              <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>
                {formatINR(item.amount)}
              </Typography>
            </Stack>
          ))}
        </Stack>

        <Stack spacing={0.75} sx={{ borderTop: `1px solid ${meridian.border}`, pt: 1.5 }}>
          <Typography sx={{ fontSize: "0.875rem" }}>
            Gross: {formatINR(invoice.gross_amount)}
          </Typography>
          <Typography sx={{ fontSize: "0.875rem" }}>
            Discount: {formatINR(invoice.discount_amount)}
          </Typography>
          <Typography sx={{ fontSize: "0.875rem" }}>
            Scheme adjustment: {formatINR(invoice.scheme_adjustment)}
          </Typography>
          <Typography sx={{ fontWeight: 700, fontSize: "1rem", color: meridian.textPrimary }}>
            Net: {formatINR(invoice.net_amount)}
          </Typography>
        </Stack>
      </Stack>
    </Modal>
  );
}
