"use client";

/**
 * Goods receipt: log a delivery, then verify it into stock.
 *
 * THE TWO STEPS ARE KEPT VISUALLY SEPARATE ON PURPOSE.
 *
 * Creating a GRN records that boxes arrived. It puts nothing into stock —
 * `inventory_batches` gains rows only when the GRN is VERIFIED, which writes
 * `purchase` rows to `stock_ledger` and lets the database trigger apply them.
 * A storekeeper who believes logging the delivery made it dispensable will tell
 * a pharmacist stock is available that the system will refuse to dispense.
 *
 * So an unverified GRN is labelled "not in stock yet" rather than shown as a
 * neutral row, and verification asks for the destination store, because that
 * choice decides which location the quantity becomes available from.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { searchMedicines } from "@/features/pharmacy/api";
import type { MedicineSearchResult } from "@/features/pharmacy/types";
import { ApiError } from "@/lib/api";

import { createGrn, listGrns, listPurchaseOrders, listStockLocations, listSuppliers, verifyGrn } from "./api";
import type { GrnItemDraft, GrnListRow, PurchaseOrder, StockLocation, Supplier } from "./types";

const EMPTY_LINE: GrnItemDraft = {
  item_id: "",
  item_name: "",
  batch_number: "",
  expiry_date: "",
  quantity: "",
  unit_price: "",
};

function statusTone(status: string): string {
  if (status === "verified") return "bg-green-100 text-green-800";
  // GRN's terminal negative state is 'cancelled'; there is no 'rejected'.
  if (status === "cancelled") return "bg-red-100 text-red-800";
  return "bg-amber-100 text-amber-900";
}

export function GrnWorkspace() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [locations, setLocations] = useState<StockLocation[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<PurchaseOrder[]>([]);
  const [rows, setRows] = useState<GrnListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [purchaseOrderId, setPurchaseOrderId] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [receivedDate, setReceivedDate] = useState("");
  const [lines, setLines] = useState<GrnItemDraft[]>([{ ...EMPTY_LINE }]);

  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState<MedicineSearchResult[]>([]);
  const [activeLine, setActiveLine] = useState<number | null>(null);

  const reload = useCallback(async () => {
    try {
      const [supplierList, locationList, grnList, poList] = await Promise.all([
        listSuppliers(),
        listStockLocations(),
        listGrns(),
        listPurchaseOrders(),
      ]);
      setSuppliers(supplierList);
      setLocations(locationList);
      setRows(grnList);
      setPurchaseOrders(
        poList.filter((po) =>
          ["sent", "partially_received", "approved"].includes(po.status),
        ),
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load goods receipts");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const term = search.trim();
    if (term.length < 2) {
      setMatches([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      searchMedicines(term)
        .then((response) => {
          if (!cancelled) setMatches(response.items);
        })
        .catch(() => {
          if (!cancelled) setMatches([]);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search]);

  const updateLine = (index: number, patch: Partial<GrnItemDraft>) => {
    setLines((current) =>
      current.map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  };

  /**
   * A line is only submittable once it names a real item and a positive
   * quantity. Batch number and expiry are optional on the wire, but a line
   * without them produces a batch the FEFO allocator cannot rank — flagged
   * rather than blocked, because a genuine non-expiring consumable exists.
   */
  const readyLines = useMemo(
    () => lines.filter((line) => line.item_id && Number(line.quantity) > 0),
    [lines],
  );

  const canSubmit =
    Boolean(supplierId) && Boolean(receivedDate) && readyLines.length > 0 && !busy;

  const linkableOrders = useMemo(() => {
    if (!supplierId) return purchaseOrders;
    return purchaseOrders.filter((po) => po.supplier_id === supplierId);
  }, [purchaseOrders, supplierId]);

  const selectPurchaseOrder = (poId: string) => {
    setPurchaseOrderId(poId);
    const po = purchaseOrders.find((entry) => entry.id === poId);
    if (po) setSupplierId(po.supplier_id);
  };

  const submit = async () => {
    setBusy(true);
    try {
      await createGrn({
        supplier_id: supplierId,
        purchase_order_id: purchaseOrderId || null,
        invoice_number: invoiceNumber.trim() || null,
        received_date: receivedDate,
        items: readyLines.map((line) => ({
          item_id: line.item_id,
          batch_number: line.batch_number.trim() || null,
          expiry_date: line.expiry_date || null,
          quantity: line.quantity,
          unit_price: line.unit_price.trim() || null,
        })),
      });
      setPurchaseOrderId("");
      setSupplierId("");
      setInvoiceNumber("");
      setReceivedDate("");
      setLines([{ ...EMPTY_LINE }]);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not record the receipt");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (grnId: string, stockLocationId: string) => {
    setBusy(true);
    try {
      await verifyGrn(grnId, stockLocationId);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not verify the receipt");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      {error ? (
        <p
          role="alert"
          className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </p>
      ) : null}

      <section className="rounded border border-gray-200 p-4">
        <h3 className="text-base font-semibold">Record a delivery</h3>
        <p className="mt-1 text-sm text-gray-600">
          This logs the paperwork. Stock becomes dispensable only after the receipt
          is verified into a store, below.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm sm:col-span-2">
            <span className="block text-gray-700">Link to purchase order (optional)</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={purchaseOrderId}
              onChange={(event) => selectPurchaseOrder(event.target.value)}
            >
              <option value="">No purchase order — ad hoc receipt</option>
              {linkableOrders.map((po) => (
                <option key={po.id} value={po.id}>
                  {po.po_number} · {po.supplier_name} · {po.status}
                </option>
              ))}
            </select>
            {purchaseOrderId ? (
              <p className="mt-1 text-xs text-gray-600">
                Supplier and line quantities are checked against this order on verify.
              </p>
            ) : null}
          </label>
          <label className="text-sm">
            <span className="block text-gray-700">Supplier</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={supplierId}
              onChange={(event) => {
                setSupplierId(event.target.value);
                if (purchaseOrderId) {
                  const linked = purchaseOrders.find((po) => po.id === purchaseOrderId);
                  if (linked && linked.supplier_id !== event.target.value) {
                    setPurchaseOrderId("");
                  }
                }
              }}
            >
              <option value="">Select…</option>
              {suppliers.map((supplier) => (
                <option key={supplier.id} value={supplier.id}>
                  {supplier.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-gray-700">Supplier invoice no.</span>
            <input
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={invoiceNumber}
              onChange={(event) => setInvoiceNumber(event.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="block text-gray-700">Received on</span>
            <input
              type="date"
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={receivedDate}
              onChange={(event) => setReceivedDate(event.target.value)}
            />
          </label>
        </div>

        <div className="mt-5 space-y-3">
          {lines.map((line, index) => (
            <div key={index} className="rounded border border-gray-200 p-3">
              <div className="grid gap-2 sm:grid-cols-5">
                <div className="sm:col-span-2">
                  <span className="block text-sm text-gray-700">Item</span>
                  {line.item_id ? (
                    <div className="mt-1 flex items-center justify-between rounded bg-gray-50 p-2 text-sm">
                      <span>{line.item_name}</span>
                      <button
                        type="button"
                        className="text-xs text-blue-700 underline"
                        onClick={() => updateLine(index, { item_id: "", item_name: "" })}
                      >
                        change
                      </button>
                    </div>
                  ) : (
                    <input
                      className="mt-1 w-full rounded border border-gray-300 p-2"
                      placeholder="Search medicines…"
                      value={activeLine === index ? search : ""}
                      onFocus={() => {
                        setActiveLine(index);
                        setSearch("");
                      }}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  )}
                  {activeLine === index && !line.item_id && matches.length > 0 ? (
                    <ul className="mt-1 max-h-40 overflow-auto rounded border border-gray-200 text-sm">
                      {matches.map((match) => (
                        <li key={match.item_id}>
                          <button
                            type="button"
                            className="w-full px-2 py-1 text-left hover:bg-gray-100"
                            onClick={() => {
                              updateLine(index, { item_id: match.item_id, item_name: match.name });
                              setSearch("");
                              setMatches([]);
                              setActiveLine(null);
                            }}
                          >
                            {match.name}
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <label className="text-sm">
                  <span className="block text-gray-700">Batch no.</span>
                  <input
                    className="mt-1 w-full rounded border border-gray-300 p-2"
                    value={line.batch_number}
                    onChange={(event) => updateLine(index, { batch_number: event.target.value })}
                  />
                </label>
                <label className="text-sm">
                  <span className="block text-gray-700">Expiry</span>
                  <input
                    type="date"
                    className="mt-1 w-full rounded border border-gray-300 p-2"
                    value={line.expiry_date}
                    onChange={(event) => updateLine(index, { expiry_date: event.target.value })}
                  />
                </label>
                <label className="text-sm">
                  <span className="block text-gray-700">Quantity</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className="mt-1 w-full rounded border border-gray-300 p-2"
                    value={line.quantity}
                    onChange={(event) => updateLine(index, { quantity: event.target.value })}
                  />
                </label>
              </div>
              {line.item_id && !line.expiry_date ? (
                <p className="mt-2 text-xs text-amber-800">
                  No expiry date. This batch cannot be ranked for first-expiry-first-out
                  issue, and the expiry guard will never flag it.
                </p>
              ) : null}
            </div>
          ))}
          <button
            type="button"
            className="text-sm text-blue-700 underline"
            onClick={() => setLines((current) => [...current, { ...EMPTY_LINE }])}
          >
            Add another line
          </button>
        </div>

        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void submit()}
          className="mt-5 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          Record receipt
        </button>
      </section>

      <section>
        <h3 className="text-base font-semibold">Recent receipts</h3>
        {rows === null ? (
          <p className="mt-2 text-sm text-gray-600">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">No goods receipts recorded yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {rows.map((row) => (
              <li key={row.id} className="rounded border border-gray-200 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{row.supplier_name}</span>
                    {row.invoice_number ? (
                      <span className="text-gray-600"> · invoice {row.invoice_number}</span>
                    ) : null}
                    <span className="text-gray-600">
                      {" "}
                      · {row.received_date} · {row.line_count} line
                      {row.line_count === 1 ? "" : "s"}
                    </span>
                  </div>
                  <span className={`rounded px-2 py-0.5 text-xs ${statusTone(row.status)}`}>
                    {row.status}
                  </span>
                </div>

                {row.status === "draft" || row.status === "received" ? (
                  <div className="mt-3 border-t border-gray-100 pt-3">
                    <p className="text-xs text-amber-900">
                      Not in stock yet. Verifying posts every line into a store and
                      makes the quantity dispensable.
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <select
                        className="rounded border border-gray-300 p-1 text-sm"
                        defaultValue=""
                        onChange={(event) => {
                          if (event.target.value) void verify(row.id, event.target.value);
                        }}
                        disabled={busy}
                      >
                        <option value="">Verify into store…</option>
                        {locations.map((location) => (
                          <option key={location.id} value={location.id}>
                            {location.name} ({location.location_type})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
