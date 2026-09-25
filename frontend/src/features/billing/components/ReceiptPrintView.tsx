"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Modal } from "@/components/ui/Modal";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { useLocale } from "@/lib/i18n";
import { paymentModeLabel } from "../lib/labels";
import { formatINR } from "../lib/formatters";
import type { InvoiceWithItems, PaymentWithRefunds } from "../types";
import { ImmutableReceipt } from "./ImmutableReceipt";

type Props = {
  open: boolean;
  payment: PaymentWithRefunds | null;
  invoice: InvoiceWithItems | null;
  onClose: () => void;
  onPrint: () => void;
};

export function ReceiptPrintView({ open, payment, invoice, onClose, onPrint }: Props) {
  // The real facility, from GET /users/me. This used to render a hardcoded
  // mock hospital name — on a RECEIPT, which is a document the patient keeps
  // and may present for reimbursement. A wrong name here is worse than a
  // missing one, so it renders nothing rather than a placeholder while the
  // session loads.
  const { user: currentUser } = useCurrentUser();
  const { localizeField, t } = useLocale();

  if (!payment || !invoice) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Print receipt"
      size="md"
      actions={
        <>
          <Button onClick={onClose} className="no-print" sx={{ textTransform: "none" }}>
            Close
          </Button>
          <Button
            variant="contained"
            onClick={onPrint}
            className="no-print"
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Print
          </Button>
        </>
      }
    >
      <Box id="receipt-print-root" className="receipt-print-root">
        <Stack spacing={0.5} sx={{ mb: 2, textAlign: "center" }}>
          <Typography sx={{ fontWeight: 700, fontSize: "1.125rem" }}>
            {localizeField(currentUser?.facility.name ?? "", currentUser?.facility.name_hi)}
          </Typography>
          <Typography sx={{ fontSize: "0.875rem" }}>Payment receipt</Typography>
          <Typography sx={{ fontSize: "0.75rem" }}>
            {paymentModeLabel(t, payment.mode)} · {formatINR(payment.amount)}
          </Typography>
        </Stack>
        <ImmutableReceipt payment={payment} invoice={invoice} />
        <Typography sx={{ mt: 2, fontSize: "0.75rem", textAlign: "center" }}>
          This is a computer-generated receipt.
        </Typography>
      </Box>
    </Modal>
  );
}
