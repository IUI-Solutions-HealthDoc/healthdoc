"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { buildVisitInvoice, getInvoice, issueInvoice } from "../api";
import { fromMoney, toMoney } from "../lib/money";
import { recomputeInvoiceTotals } from "../lib/calculations";
import { toast } from "@/components/ui/toast";
import type {
  AddInvoiceItemInput,
  InvoiceWithItems,
  SchemeOptionCode,
} from "../types";

function schemeCodeFromOption(code: SchemeOptionCode): string | null {
  if (code === "self_pay") return null;
  if (code === "PMJAY") return "PMJAY";
  return "OTHER";
}

function optionFromSchemeCode(scheme_code: string | null): SchemeOptionCode {
  if (scheme_code === "PMJAY") return "PMJAY";
  if (scheme_code === "OTHER") return "OTHER";
  return "self_pay";
}

export function useInvoiceEditor(
  invoice: InvoiceWithItems | null,
  onSaved?: (next: InvoiceWithItems) => void,
) {
  const [draft, setDraft] = useState<InvoiceWithItems | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [buildMessage, setBuildMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(invoice ? structuredClone(invoice) : null);
    setPreviewOpen(false);
  }, [invoice]);

  // No backend supports manual financial edits. Drafts can be built and
  // issued, not edited in browser-only state that will be discarded on issue.
  const canEdit = false;
  const canBuild = draft?.status === "draft";
  const canIssue = canBuild && (draft?.items.length ?? 0) > 0;
  const schemeOption = optionFromSchemeCode(draft?.scheme_code ?? null);

  const isDirty = useMemo(() => {
    if (!invoice || !draft) return false;
    return JSON.stringify(invoice) !== JSON.stringify(draft);
  }, [invoice, draft]);

  const applyTotals = useCallback((next: InvoiceWithItems): InvoiceWithItems => {
    const totals = recomputeInvoiceTotals(
      next.items,
      next.discount_amount,
      next.scheme_adjustment,
    );
    return { ...next, ...totals };
  }, []);

  const setScheme = useCallback(
    (option: SchemeOptionCode) => {
      if (!draft || !canEdit) return;
      setDraft(
        applyTotals({
          ...draft,
          scheme_code: schemeCodeFromOption(option),
          // Keep existing scheme_adjustment; user edits it explicitly (no auto %).
          scheme_adjustment: draft.scheme_adjustment,
        }),
      );
    },
    [applyTotals, canEdit, draft],
  );

  const setDiscount = useCallback(
    (discount_amount: number) => {
      if (!draft || !canEdit) return;
      setDraft(applyTotals({ ...draft, discount_amount: toMoney(Math.max(0, discount_amount)) }));
    },
    [applyTotals, canEdit, draft],
  );

  const setSchemeAdjustment = useCallback(
    (scheme_adjustment: number) => {
      if (!draft || !canEdit) return;
      setDraft(
        applyTotals({
          ...draft,
          scheme_adjustment: toMoney(Math.max(0, scheme_adjustment)),
        }),
      );
    },
    [applyTotals, canEdit, draft],
  );

  /**
   * Draft-level fields (scheme_code, discount, scheme adjustment) have no
   * update endpoint, and after review they should not: the schema treats an
   * invoice's financial fields as derived from what was billed, frozen at
   * issue, and corrected only by cancel-and-reissue. Kept as an explicit
   * refusal rather than removed, so the button surfaces the reason instead of
   * vanishing without explanation.
   */
  const saveDraft = useCallback(async () => {
    toast.error(
      "Invoice amounts are not editable. Charges come from the departments " +
        "via Build; corrections are cancel-and-reissue.",
    );
  }, []);

  const build = useCallback(async () => {
    if (!draft || !canBuild) return;
    setBusy(true);
    setBuildMessage(null);
    try {
      const result = await buildVisitInvoice(draft.visit_id);
      const next = await getInvoice(result.invoice_id);
      setDraft(next);
      onSaved?.(next);
      setBuildMessage(`${result.lines_added} charge(s) added. ${result.lines_skipped_unpriced} unpriced charge(s) skipped.`);
      if (result.lines_skipped_unpriced) toast.error("Some charges have no tariff. Resolve pricing before issuing.");
      else toast.success("Charges built", "Review the refreshed totals before issuing");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Build failed");
    } finally {
      setBusy(false);
    }
  }, [canBuild, draft, onSaved]);

  const issue = useCallback(async () => {
    if (!draft || !canIssue) return;
    setBusy(true);
    try {
      // row_version is the concurrency guard: the server refuses a stale one
      // rather than freezing an invoice that gained a charge line since load.
      const issued = await issueInvoice(draft.id, draft.row_version ?? 1);
      setDraft(issued);
      onSaved?.(issued);
      toast.success("Invoice issued", "Financial fields are now frozen");
      setPreviewOpen(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Issue failed");
    } finally {
      setBusy(false);
    }
  }, [canIssue, draft, onSaved]);

  /**
   * addItem / patchItem / removeItem: manual line editing, refused.
   *
   * No endpoint backs any of these and none should. Charges are aggregated onto
   * the draft by POST /billing/visits/{id}/invoice/build from what the lab,
   * radiology and pharmacy modules actually recorded — a line typed by hand
   * bills for work no department logged, and bypasses the accrual guard in
   * `_already_billed_reference_ids` that stops the same item being billed twice.
   *
   * Kept as explicit refusals rather than deleted so the buttons explain
   * themselves. Delete them once LineItemsEditor is read-only everywhere.
   */
  const refuseEdit = useCallback(() => {
    toast.error(
      "Invoice lines come from the departments. Use Build to pull in unbilled " +
        "charges; a line cannot be added or edited by hand.",
    );
  }, []);

  const addItem = useCallback(async (_body: AddInvoiceItemInput) => refuseEdit(), [refuseEdit]);
  const patchItem = useCallback(
    async (
      _itemId: string,
      _patch: Partial<
        Pick<AddInvoiceItemInput, "quantity" | "unit_price" | "description" | "charge_category">
      >,
    ) => refuseEdit(),
    [refuseEdit],
  );
  const removeItem = useCallback(async (_itemId: string) => refuseEdit(), [refuseEdit]);

  return {
    draft,
    canEdit,
    canBuild,
    canIssue,
    build,
    buildMessage,
    busy,
    isDirty,
    schemeOption,
    previewOpen,
    setPreviewOpen,
    setScheme,
    setDiscount,
    setSchemeAdjustment,
    saveDraft,
    issue,
    addItem,
    patchItem,
    removeItem,
    /** Numeric helpers for controlled inputs */
    discountNumber: draft ? fromMoney(draft.discount_amount) : 0,
    schemeAdjustmentNumber: draft ? fromMoney(draft.scheme_adjustment) : 0,
  };
}
