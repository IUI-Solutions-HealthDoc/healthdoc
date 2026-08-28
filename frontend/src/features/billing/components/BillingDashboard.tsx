"use client";

import { useCallback, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { toast } from "@/components/ui/toast";
import { meridian } from "@/styles/theme";
import { createRefund, getInvoice } from "../api";
import { useCollectPayment } from "../hooks/useCollectPayment";
import { useInvoiceDetail } from "../hooks/useInvoiceDetail";
import { useInvoiceEditor } from "../hooks/useInvoiceEditor";
import { useInvoicePayments } from "../hooks/useInvoicePayments";
import { useInvoices } from "../hooks/useInvoices";
import type { InvoiceWithItems } from "../types";
import { InvoiceHeader } from "./InvoiceHeader";
import { InvoiceListPanel } from "./InvoiceListPanel";
import { InvoicePreviewModal } from "./InvoicePreviewModal";
import { InvoiceTotals } from "./InvoiceTotals";
import { LineItemsEditor } from "./LineItemsEditor";
import { PaymentsPanel } from "./PaymentsPanel";
import { SchemeSelector } from "./SchemeSelector";

import "../receipt-print.css";

export function BillingDashboard() {
  const {
    invoices,
    loading: listLoading,
    filters,
    setQuery,
    setStatus,
    refresh: refreshList,
  } = useInvoices({ status: "all" });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refundBusy, setRefundBusy] = useState(false);

  const { invoice, setInvoice, loading: detailLoading } = useInvoiceDetail(selectedId);

  const onSaved = useCallback(
    (next: InvoiceWithItems) => {
      setInvoice(next);
      void refreshList();
    },
    [refreshList, setInvoice],
  );

  const editor = useInvoiceEditor(invoice, onSaved);
  const paymentsHook = useInvoicePayments(selectedId);
  const { refresh: refreshPayments } = paymentsHook;

  const onPaymentSaved = useCallback(
    (next: InvoiceWithItems) => {
      setInvoice(next);
      void refreshList();
      void refreshPayments();
    },
    [refreshList, refreshPayments, setInvoice],
  );

  const collect = useCollectPayment(selectedId, (inv) => onPaymentSaved(inv));

  const canCollect =
    !!editor.draft &&
    (editor.draft.status === "issued" || editor.draft.status === "partially_paid");

  const showPayments =
    !!editor.draft &&
    editor.draft.status !== "draft" &&
    editor.draft.status !== "cancelled";

  const handleSelect = (id: string) => {
    setSelectedId(id);
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Box>
        <Typography
          component="h1"
          sx={{
            m: 0,
            fontSize: "1.5rem",
            fontWeight: 700,
            letterSpacing: "-0.03em",
            color: meridian.textPrimary,
          }}
        >
          Billing
        </Typography>
        <Typography sx={{ m: 0, mt: 0.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
          Invoice builder · payments · immutable receipts (migration 0014)
        </Typography>
      </Box>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "320px 1fr" },
          gap: 2.5,
          alignItems: "start",
        }}
      >
        <InvoiceListPanel
          invoices={invoices}
          loading={listLoading}
          query={filters.query ?? ""}
          status={filters.status ?? "all"}
          selectedId={selectedId}
          onQueryChange={setQuery}
          onStatusChange={setStatus}
          onSelect={handleSelect}
        />

        <Stack spacing={2.5}>
          {!selectedId ? (
            <Box
              sx={{
                borderRadius: "16px",
                border: `1px dashed ${meridian.border}`,
                p: 4,
                textAlign: "center",
                color: meridian.textSecondary,
              }}
            >
              Select an invoice from the list to open the builder.
            </Box>
          ) : detailLoading || !editor.draft ? (
            <Typography sx={{ color: meridian.textSecondary }}>Loading invoice…</Typography>
          ) : (
            <>
              {!editor.canEdit ? (
                <Typography
                  sx={{
                    px: 2,
                    py: 1.25,
                    borderRadius: "12px",
                    backgroundColor: "#e8eef5",
                    color: meridian.brandPrimary,
                    fontSize: "0.875rem",
                    fontWeight: 600,
                  }}
                >
                  This invoice is not a draft — financial fields are read-only. Use Payments to
                  collect or reverse.
                </Typography>
              ) : null}

              <InvoiceHeader invoice={editor.draft} />

              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", md: "1.2fr 0.8fr" },
                  gap: 2.5,
                }}
              >
                <SchemeSelector
                  value={editor.schemeOption}
                  schemeAdjustment={editor.schemeAdjustmentNumber}
                  disabled={!editor.canEdit || editor.busy}
                  onChange={editor.setScheme}
                  onSchemeAdjustmentChange={editor.setSchemeAdjustment}
                />
                <InvoiceTotals
                  gross_amount={editor.draft.gross_amount}
                  discount_amount={editor.draft.discount_amount}
                  scheme_adjustment={editor.draft.scheme_adjustment}
                  net_amount={editor.draft.net_amount}
                  canEdit={editor.canEdit}
                  onDiscountChange={editor.setDiscount}
                />
              </Box>

              <LineItemsEditor
                items={editor.draft.items}
                canEdit={editor.canEdit}
                busy={editor.busy}
                scheme_code={editor.draft.scheme_code}
                onAdd={editor.addItem}
                onPatch={editor.patchItem}
                onRemove={editor.removeItem}
              />

              {editor.canEdit ? (
                <Stack direction="row" useFlexGap sx={{ gap: 1.25, flexWrap: "wrap" }}>
                  <Button
                    variant="outlined"
                    disabled={editor.busy || !editor.isDirty}
                    onClick={() => void editor.saveDraft()}
                    sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
                  >
                    Save draft
                  </Button>
                  <Button
                    variant="outlined"
                    disabled={editor.busy}
                    onClick={() => editor.setPreviewOpen(true)}
                    sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
                  >
                    Preview
                  </Button>
                  <Button
                    variant="contained"
                    disabled={editor.busy}
                    onClick={() => {
                      editor.setPreviewOpen(true);
                      toast.info("Review totals", "Confirm Issue from the preview dialog");
                    }}
                    sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
                  >
                    Issue…
                  </Button>
                </Stack>
              ) : null}

              {showPayments ? (
                <PaymentsPanel
                  invoice={editor.draft}
                  payments={paymentsHook.payments}
                  loading={paymentsHook.loading}
                  busy={collect.busy || refundBusy}
                  balanceDue={paymentsHook.balance_due}
                  paidTotal={paymentsHook.paid_total}
                  refundedTotal={paymentsHook.refunded_total}
                  canCollect={canCollect}
                  onCollect={async (body) => {
                    await collect.submit(body);
                  }}
                  onRefund={async (paymentId, body) => {
                    setRefundBusy(true);
                    try {
                      // Returns the refund alone; re-read the invoice for the
                      // new balance rather than assuming it.
                      const refund = await createRefund(paymentId, body);
                      toast.success("Payment reversed", refund.refund_number);
                      if (selectedId) onPaymentSaved(await getInvoice(selectedId));
                    } catch (e) {
                      toast.error(e instanceof Error ? e.message : "Reversal failed");
                      throw e;
                    } finally {
                      setRefundBusy(false);
                    }
                  }}
                />
              ) : null}

              <InvoicePreviewModal
                open={editor.previewOpen}
                invoice={editor.draft}
                canIssue={editor.canEdit}
                busy={editor.busy}
                onClose={() => editor.setPreviewOpen(false)}
                onIssue={() => void editor.issue()}
              />
            </>
          )}
        </Stack>
      </Box>
    </Box>
  );
}
