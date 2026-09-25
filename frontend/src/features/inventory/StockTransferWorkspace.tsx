"use client";

/**
 * Moving stock between locations within one facility.
 *
 * DISPATCH AND RECEIVE ARE TWO STEPS, NOT ONE.
 *
 * Between them the goods belong to neither location: they have left the store
 * and not yet arrived on the ward. Collapsing that into a single button would
 * make a consignment that never turns up invisible — the source would show it
 * gone, the destination would show it present, and nothing would show it
 * missing. The gap between the two clicks is the only place a loss is
 * detectable.
 *
 * A transfer moves a SPECIFIC BATCH, not a quantity of an item. Expiry travels
 * with the goods, so the ward needs to know which batch it received, and FEFO
 * at the destination depends on it.
 */
import { useCallback, useEffect, useState } from "react";

import { searchMedicines } from "@/features/pharmacy/api";
import type { BatchAvailability, MedicineSearchResult } from "@/features/pharmacy/types";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import {
  cancelStockTransfer,
  createStockTransfer,
  dispatchStockTransfer,
  listStockLocations,
  listStockTransfers,
  receiveStockTransfer,
} from "./api";
import type { StockLocation, StockTransfer, StockTransferStatus } from "./types";

interface DraftLine {
  item_id: string;
  item_name: string;
  batch_id: string;
  batch_number: string;
  available: string;
  quantity: string;
}

function statusTone(status: StockTransferStatus): string {
  if (status === "received") return "bg-green-100 text-green-800";
  if (status === "cancelled") return "bg-red-100 text-red-800";
  if (status === "dispatched") return "bg-amber-100 text-amber-900";
  return "bg-gray-100 text-gray-700";
}

export function StockTransferWorkspace() {
  const { t } = useLocale();
  const [locations, setLocations] = useState<StockLocation[]>([]);
  const [transfers, setTransfers] = useState<StockTransfer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<MedicineSearchResult[]>([]);
  const [picking, setPicking] = useState<MedicineSearchResult | null>(null);

  const reload = useCallback(async () => {
    try {
      const [locationList, transferList] = await Promise.all([
        listStockLocations(),
        listStockTransfers(),
      ]);
      setLocations(locationList);
      setTransfers(transferList);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("inventory.err.loadTransfers"));
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

  const addBatch = (item: MedicineSearchResult, batch: BatchAvailability) => {
    setLines((cur) =>
      cur.some((l) => l.batch_id === batch.batch_id)
        ? cur
        : [
            ...cur,
            {
              item_id: item.item_id,
              item_name: item.name,
              batch_id: batch.batch_id,
              batch_number: batch.batch_number,
              available: batch.quantity,
              quantity: "",
            },
          ],
    );
    setPicking(null);
    setTerm("");
    setMatches([]);
  };

  // A line asking for more than the batch holds will be refused by the
  // quantity >= 0 CHECK once the ledger is written. Caught here so the
  // storekeeper sees it while filling the form, not after submitting.
  const overdrawn = lines.filter(
    (l) => l.quantity !== "" && Number(l.quantity) > Number(l.available),
  );
  const ready = lines.filter((l) => Number(l.quantity) > 0);
  const canSubmit =
    Boolean(fromId && toId) &&
    fromId !== toId &&
    ready.length > 0 &&
    overdrawn.length === 0 &&
    !busy;

  const submit = async () => {
    setBusy(true);
    try {
      await createStockTransfer({
        from_location_id: fromId,
        to_location_id: toId,
        items: ready.map((l) => ({
          item_id: l.item_id,
          batch_id: l.batch_id,
          quantity: l.quantity,
        })),
      });
      setFromId("");
      setToId("");
      setLines([]);
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("inventory.err.createTransfer"));
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn: () => Promise<unknown>, failure: string) => {
    setBusy(true);
    try {
      await fn();
      await reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : failure);
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
        <h3 className="text-base font-semibold">{t("inventory.transfer.moveTitle")}</h3>
        <p className="mt-1 text-sm text-gray-600">{t("inventory.transfer.moveHint")}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="block text-gray-700">{t("inventory.transfer.from")}</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={fromId}
              onChange={(e) => setFromId(e.target.value)}
            >
              <option value="">{t("common.selectEllipsis")}</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name} ({l.location_type})
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-gray-700">{t("inventory.transfer.to")}</span>
            <select
              className="mt-1 w-full rounded border border-gray-300 p-2"
              value={toId}
              onChange={(e) => setToId(e.target.value)}
            >
              <option value="">{t("common.selectEllipsis")}</option>
              {locations
                // A transfer to the same location is a no-op that would still
                // write two ledger rows. Excluded rather than validated after.
                .filter((l) => l.id !== fromId)
                .map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name} ({l.location_type})
                  </option>
                ))}
            </select>
          </label>
        </div>

        <div className="mt-4">
          <input
            className="w-full rounded border border-gray-300 p-2 text-sm sm:max-w-sm"
            placeholder={t("inventory.transfer.searchPlaceholder")}
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
          {matches.length > 0 && !picking ? (
            <ul className="mt-1 max-h-40 max-w-sm overflow-auto rounded border border-gray-200 text-sm">
              {matches.map((m) => (
                <li key={m.item_id}>
                  <button
                    type="button"
                    className="w-full px-2 py-1 text-left hover:bg-gray-100"
                    onClick={() => setPicking(m)}
                  >
                    {m.name}
                    <span className="text-gray-500">
                      {" "}
                      ·{" "}
                      {m.batches.length === 1
                        ? t("inventory.transfer.batchCount", { count: m.batches.length })
                        : t("inventory.transfer.batchCountPlural", { count: m.batches.length })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          {picking ? (
            <div className="mt-2 max-w-sm rounded border border-gray-200 p-2 text-sm">
              <p className="font-medium">
                {t("inventory.transfer.chooseBatch", { name: picking.name })}
              </p>
              {picking.batches.length === 0 ? (
                <p className="mt-1 text-amber-800">{t("inventory.transfer.noBatches")}</p>
              ) : (
                <ul className="mt-1">
                  {picking.batches.map((b) => (
                    <li key={b.batch_id}>
                      <button
                        type="button"
                        className="w-full px-1 py-1 text-left hover:bg-gray-100"
                        onClick={() => addBatch(picking, b)}
                      >
                        {b.batch_number} · expires {b.expiry_date} · {b.quantity} on hand
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <button
                type="button"
                className="mt-1 text-xs text-blue-700 underline"
                onClick={() => setPicking(null)}
              >
                {t("common.cancel")}
              </button>
            </div>
          ) : null}
        </div>

        {lines.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {lines.map((line, index) => {
              const over = line.quantity !== "" && Number(line.quantity) > Number(line.available);
              return (
                <li key={line.batch_id} className="text-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="flex-1">
                      {line.item_name}{" "}
                      <span className="text-gray-600">· batch {line.batch_number}</span>
                    </span>
                    <input
                      type="number" min="0" step="0.01" placeholder={t("inventory.po.qtyPlaceholder")}
                      className={`w-24 rounded border p-1 ${
                        over ? "border-red-400" : "border-gray-300"
                      }`}
                      value={line.quantity}
                      onChange={(e) =>
                        setLines((cur) =>
                          cur.map((l, i) => (i === index ? { ...l, quantity: e.target.value } : l)),
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
                  </div>
                  {over ? (
                    <p className="mt-1 text-xs text-red-700">
                      {t("inventory.transfer.overdrawn", { available: line.available })}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}

        <button
          type="button"
          disabled={!canSubmit}
          onClick={() => void submit()}
          className="mt-5 rounded bg-blue-700 px-4 py-2 text-sm text-white disabled:bg-gray-300"
        >
          {t("inventory.transfer.create")}
        </button>
      </section>

      <section>
        <h3 className="text-base font-semibold">{t("inventory.transfer.listTitle")}</h3>
        {transfers === null ? (
          <p className="mt-2 text-sm text-gray-600">{t("common.loading")}</p>
        ) : transfers.length === 0 ? (
          <p className="mt-2 text-sm text-gray-600">{t("inventory.transfer.empty")}</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {transfers.map((transfer) => (
              <li key={transfer.id} className="rounded border border-gray-200 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <span className="font-medium">{transfer.from_location_name}</span>
                    {" → "}
                    <span className="font-medium">{transfer.to_location_name}</span>
                    <span className="text-gray-600">
                      {" "}
                      ·{" "}
                      {transfer.items.length === 1
                        ? t("inventory.indent.lineCount", { count: transfer.items.length })
                        : t("inventory.indent.lineCountPlural", { count: transfer.items.length })}
                    </span>
                  </span>
                  <span className={`rounded px-2 py-0.5 text-xs ${statusTone(transfer.status)}`}>
                    {transfer.status}
                  </span>
                </div>

                <ul className="mt-1 text-gray-600">
                  {transfer.items.map((item) => (
                    <li key={item.id}>
                      {item.item_name} · batch {item.batch_number} · {item.quantity}
                    </li>
                  ))}
                </ul>

                {transfer.status === "dispatched" ? (
                  <p className="mt-2 text-xs text-amber-900">{t("inventory.transfer.inTransit")}</p>
                ) : null}

                <div className="mt-2 flex flex-wrap gap-2">
                  {transfer.status === "draft" ? (
                    <>
                      <button
                        type="button" disabled={busy}
                        onClick={() =>
                          void act(() => dispatchStockTransfer(transfer.id), t("inventory.err.dispatch"))
                        }
                        className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                      >
                        {t("inventory.transfer.dispatch")}
                      </button>
                      <button
                        type="button" disabled={busy}
                        onClick={() =>
                          void act(() => cancelStockTransfer(transfer.id), t("inventory.err.cancelTransfer"))
                        }
                        className="rounded border border-gray-300 px-3 py-1 text-xs disabled:opacity-50"
                      >
                        {t("common.cancel")}
                      </button>
                    </>
                  ) : null}
                  {transfer.status === "dispatched" ? (
                    <button
                      type="button" disabled={busy}
                      onClick={() =>
                        void act(() => receiveStockTransfer(transfer.id), t("inventory.err.receive"))
                      }
                      className="rounded bg-blue-700 px-3 py-1 text-xs text-white disabled:bg-gray-300"
                    >
                      {t("inventory.transfer.confirmReceipt")}
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
