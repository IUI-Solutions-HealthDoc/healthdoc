"use client";

import { useCallback, useEffect, useState } from "react";

import { ModuleCapabilityGate } from "@/components/common/ModuleCapabilityGate";
import { ExpiryTracker } from "@/features/pharmacy/ExpiryTracker";
import { AdjustmentWorkspace } from "@/features/inventory/AdjustmentWorkspace";
import { GrnWorkspace } from "@/features/inventory/GrnWorkspace";
import { PurchaseOrderWorkspace } from "@/features/inventory/PurchaseOrderWorkspace";
import { StockTransferWorkspace } from "@/features/inventory/StockTransferWorkspace";
import { IndentWorkspace } from "@/features/inventory/IndentWorkspace";
import { listReorderAlerts } from "@/features/pharmacy/api";
import type { ReorderAlertItem } from "@/features/pharmacy/types";
import { ApiError } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";

type StockTab = "purchase-orders" | "grn" | "transfers" | "indents" | "adjustments";

// Ordered as the goods move: ordered -> received -> moved between stores ->
// requested by a ward -> corrected. A storekeeper reading left to right is
// following the same path the stock takes.
const STOCK_TABS: Array<{ id: StockTab; labelKey: MessageKey }> = [
  { id: "purchase-orders", labelKey: "inventory.tab.purchaseOrders" },
  { id: "grn", labelKey: "inventory.tab.grn" },
  { id: "transfers", labelKey: "inventory.tab.transfers" },
  { id: "indents", labelKey: "inventory.tab.indents" },
  { id: "adjustments", labelKey: "inventory.tab.adjustments" },
];

function Inventory() {
  const { t } = useLocale();
  const { user, isLoading: authLoading } = useAuth();
  const isHod = user?.role === "hod";
  const [tab, setTab] = useState<StockTab>("purchase-orders");
  const [alerts, setAlerts] = useState<ReorderAlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // HODs come here for their one exclusive action: deciding department
    // indents. Reorder, expiry, purchasing and receiving reads are deliberately
    // pharmacist/admin-only and must never be mounted for an HOD.
    if (authLoading || isHod) return;
    try {
      const response = await listReorderAlerts();
      setAlerts(response.items);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load inventory alerts");
    }
  }, [authLoading, isHod]);

  useEffect(() => {
    void load();
  }, [load]);

  if (authLoading) {
    return <p className="p-6 text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  if (isHod) {
    return (
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-3xl font-semibold">{t("inventory.indentsTitle")}</h1>
          <p className="mt-2 max-w-prose text-sm text-muted-foreground">
            {t("inventory.hodSubtitle")}
          </p>
        </div>
        <IndentWorkspace />
      </div>
    );
  }

  return (
    <div className="space-y-8 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">{t("inventory.title")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("inventory.subtitle")}</p>
        </div>
        <button type="button" className="text-sm underline" onClick={() => void load()}>
          {t("common.refresh")}
        </button>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">{t("inventory.reorderAlertsTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("inventory.reorderAlertsHint")}</p>
        </div>
        {alerts === null ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : null}
        {alerts?.length === 0 ? (
          <div className="surface-card p-6 text-sm text-success">{t("inventory.reorderEmpty")}</div>
        ) : null}
        {alerts && alerts.length > 0 ? (
          <div className="surface-card overflow-hidden">
            <table className="min-w-full border-collapse text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-4 py-3 text-left">{t("inventory.col.item")}</th>
                  <th className="px-4 py-3 text-right">{t("inventory.col.currentStock")}</th>
                  <th className="px-4 py-3 text-right">{t("inventory.col.reorderLevel")}</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((item) => (
                  <tr key={item.item_id} className="border-b border-border last:border-none">
                    <td className="px-4 py-3 font-medium">{item.item_name}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-danger">
                      {item.current_stock}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{item.reorder_level}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">{t("inventory.batchExpiryTitle")}</h2>
        <ExpiryTracker />
      </section>

      {/*
        This was a warning panel explaining why receiving, indents and
        adjustments were absent: the mutations existed, but no supplier,
        stock-location, GRN, indent or adjustment LIST contract did, so the
        screen would have had to ask operators to paste UUIDs and would have
        given approvers no queue to work from. That diagnosis was exactly
        right. Those six reads now exist, so the panel is replaced by the
        workflows it was standing in for.
      */}
      <section className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold">{t("inventory.stockMovementTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("inventory.stockMovementHint")}</p>
        </div>

        <div className="flex gap-1 border-b border-border">
          {STOCK_TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              className={`px-4 py-2 text-sm ${
                tab === entry.id
                  ? "border-b-2 border-blue-700 font-medium text-blue-700"
                  : "text-muted-foreground"
              }`}
            >
              {t(entry.labelKey)}
            </button>
          ))}
        </div>

        {tab === "purchase-orders" ? <PurchaseOrderWorkspace /> : null}
        {tab === "grn" ? <GrnWorkspace /> : null}
        {tab === "transfers" ? <StockTransferWorkspace /> : null}
        {tab === "indents" ? <IndentWorkspace /> : null}
        {tab === "adjustments" ? <AdjustmentWorkspace /> : null}
      </section>
    </div>
  );
}

export default function Page() {
  return (
    <ModuleCapabilityGate module="pharmacy">
      <Inventory />
    </ModuleCapabilityGate>
  );
}
