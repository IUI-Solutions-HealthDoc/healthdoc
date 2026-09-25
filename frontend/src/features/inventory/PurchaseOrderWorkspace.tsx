"use client";

/**
 * Purchase orders — the step upstream of receiving.
 *
 * Until now goods were received against no order at all: `grn.purchase_order_id`
 * existed, was always null, and nothing could set it. That means a GRN could
 * record any quantity of anything from any supplier with nothing to check it
 * against. Linking a receipt to an order is what makes over-delivery,
 * wrong-supplier and phantom-line receipts detectable rather than merely
 * unlikely.
 *
 * WHAT THIS SCREEN DELIBERATELY CANNOT DO
 *
 * Mark an order received. `received` and `partially_received` are set by the
 * SERVER when a GRN linked to the order is verified — they are not offered as
 * transitions, and the type does not include them. A clerk who could tick
 * "received" by hand would let the paperwork assert goods arrived that no
 * goods-receipt ever recorded, which is precisely the reconciliation the order
 * exists to provide.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { searchMedicines } from "@/features/pharmacy/api";
import type { MedicineSearchResult } from "@/features/pharmacy/types";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import {
  createPurchaseOrder,
  listPurchaseOrders,
  listSuppliers,
  transitionPurchaseOrder,
} from "./api";
import type { PurchaseOrder, PurchaseOrderStatus, Supplier } from "./types";

interface DraftLine {
  item_id: string;
  item_name: string;
  quantity: string;
  unit_price: string;
}

function statusTone(status: PurchaseOrderStatus): string {
  if (status === "received") return "bg-green-100 text-green-800";
  if (status === "cancelled") return "bg-red-100 text-red-800";
  if (status === "partially_received") return "bg-blue-100 text-blue-800";
  return "bg-amber-100 text-amber-900";
}

/** Ordered minus received, per line. Both are decimal strings from the server. */
function outstanding(quantity: string, received: string): string {
  const left = Number(quantity) - Number(received);
  // Displayed only. Never sent back — the server owns this arithmetic, and two
  // implementations of it would eventually disagree about what is owed.
  return Number.isFinite(left) ? String(left) : "—";
}

export function PurchaseOrderWorkspace() {
  const { t } = useLocale();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [supplierId, setSupplierId] = useState("");
  const [expectedDate, setExpectedDate] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<MedicineSearchResult[]>([]);

  const reload = useCallback(async () => {
    try {
      const [supplierList, orderList] = await Promise.all([
        listSuppliers(),
        listPurchaseOrders(),
      ]);
      setSuppliers(supplierList);
      setOrders(orderList);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("inventory.err.loadPurchaseOrders"));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const q = term.trim();
    if (q.length < 2) {
      setMatches([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      searchMedicines(q)
        .then((r) => !cancelled && setMatches(r.items))
        .catch(() => !cancelled && setMatches([]));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [term]);

  const readyLines = useMemo(
    () => lines.filter((l) => l.item_id && Number(l.quantity) > 0),
    [lines],
  );

  const submit = async () => {
    if (!supplierId || readyLines.length === 0) return;
    setBusy(true);
    try {
      await createPurchaseOrder({
        supplier_id: supplierId,
        expected_date: expectedDate || null,
        items: readyLines.map((l) => ({
          item_id: l.item_id,
          quantity: l.quantity,
          unit_price: l.unit_price.trim() || null,
        })),
      });
      setSupplierId("");
      setExpectedDate("");
      setLines([]);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("inventory.err.raiseOrder"));
    } finally {
      setBusy(false);
    }
  };

  const move = async (id: string, target: "approved" | "sent" | "cancelled") => {
    setBusy(true);
    try {
      await transitionPurchaseOrder(id, target);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("inventory.err.updateOrder"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      {error ? (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      <section className="rounded border border-gray-200 p-4">
        <h3 className="text-base font-semibold">{t("inventory.po.raiseTitle")}</h3>
        <p className="mt-1 text-sm text-gray-600">{t("inventory.po.raiseHint")}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="block text-gray-700">{t("inventory.po.supplier")}</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={supplierId}
              onChange={(e) => setSupplierId(e.target.value)}
            >
              <option value="">{t("common.selectEllipsis")}</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-gray-700">{t("inventory.po.expectedDelivery")}</span>
            <input
              type="date"
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={expectedDate}
              onChange={(e) => setExpectedDate(e.target.value)}
            />
          </label>
        </div>

        <div className="mt-4">
          <input
            className="w-full rounded border border-gray-300 p-2 text-sm sm:max-w-sm"
            placeholder={t("inventory.po.searchItemsPlaceholder")}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
          {matches.length > 0 ? (
            <ul className="mt-1 max-h-40 max-w-sm overflow-auto rounded border border-gray-200 text-sm">
              {matches.map((m) => (
                <li key={m.item_id}>
                  <button
                    type="button"
                    className="w-full px-2 py-1 text-left hover:bg-gray-100"
                    onClick={() => {
                      setLines((cur) =>
                        cur.some((l) => l.item_id === m.item_id)
                          ? cur
                          : [
                              ...cur,
                              { item_id: m.item_id, item_name: m.name, quantity: "", unit_price: "" },
                            ],
                      );
                      setTerm("");
                      setMatches([]);
                    }}
                  >
                    {m.name}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {lines.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {lines.map((line, index) => (
              <li key={line.item_id} className="flex flex-wrap items-center gap-3 text-sm">
                <span className="flex-1">{line.item_name}</span>
                <input
                  type="number" min="0" step="0.01" placeholder={t("inventory.po.qtyPlaceholder")}
                  className="w-24 rounded border border-gray-300 p-1"
                  value={line.quantity}
                  onChange={(e) =>
                    setLines((cur) =>
                      cur.map((l, i) => (i === index ? { ...l, quantity: e.target.value } : l)),
                    )
                  }
                />
                <input
                  type="number" min="0" step="0.01" placeholder={t("inventory.po.unitPricePlaceholder")}
                  className="w-28 rounded border border-gray-300 p-1"
                  value={line.unit_price}
                  onChange={(e) =>
                    setLines((cur) =>
                      cur.map((l, i) => (i === index ? { ...l, unit_price: e.target.value } : l)),
                    )
                  }
                />
                <button
                  type="button"
                  className="text-xs text-blue-700 underline"
                  onClick={() => setLines((cur) => cur.filter((_, i) => i !== index))}
                >
                  {t("common.remove")}
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <button
          type="button"
          disabled={busy || !supplierId || readyLines.length === 0}
          onClick={() => void submit()}
          className="mt-5 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          {t("inventory.po.raiseOrder")}
        </button>
      </section>

      <section>
        <h3 className="text-base font-semibold">{t("inventory.po.ordersTitle")}</h3>
        {orders === null ? (
          <p className="mt-2 text-sm text-gray-600">{t("common.loading")}</p>
        ) : orders.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">{t("inventory.po.empty")}</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {orders.map((po) => (
              <li key={po.id} className="rounded border border-gray-200 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{po.po_number}</span>
                    <span className="text-gray-600">
                      {" "}
                      · {po.supplier_name}
                      {po.expected_date
                        ? ` · ${t("inventory.expectedLabel", { date: po.expected_date })}`
                        : ""}
                    </span>
                  </div>
                  <span className={`rounded px-2 py-0.5 text-xs ${statusTone(po.status)}`}>
                    {po.status.replace("_", " ")}
                  </span>
                </div>

                <ul className="mt-2 text-gray-600">
                  {po.items.map((item) => (
                    <li key={item.id}>
                      {t("inventory.po.lineSummary", {
                        name: item.item_name,
                        ordered: item.quantity,
                        received: item.received_quantity,
                        outstanding: outstanding(item.quantity, item.received_quantity),
                      })}
                    </li>
                  ))}
                </ul>

                {po.status === "draft" || po.status === "approved" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {po.status === "draft" ? (
                      <button
                        type="button" disabled={busy}
                        onClick={() => void move(po.id, "approved")}
                        className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                      >
                        {t("common.approve")}
                      </button>
                    ) : (
                      <button
                        type="button" disabled={busy}
                        onClick={() => void move(po.id, "sent")}
                        className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                      >
                        {t("inventory.po.markSent")}
                      </button>
                    )}
                    <button
                      type="button" disabled={busy}
                      onClick={() => void move(po.id, "cancelled")}
                      className="rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                ) : null}

                {po.status === "partially_received" || po.status === "received" ? (
                  <p className="mt-2 text-xs text-gray-600">
                    {t("inventory.po.receivedByServerHint")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
