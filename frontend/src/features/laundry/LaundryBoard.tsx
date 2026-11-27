"use client";

/**
 * Laundry: collect linen from a ward (or a place such as OT), move each batch
 * forward one step, and count it back. The count shows what was condemned and
 * what is missing. Infected linen is flagged at collection and stays flagged.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { getWardLocations } from "@/lib/wardLocations";

import {
  LINEN_ITEM_TYPES,
  NEXT_STATUS,
  advanceBatch,
  collectLinen,
  listBatches,
  type BatchStatus,
  type LinenBatch,
  type LinenItemType,
} from "./api";

const BADGE: Record<BatchStatus, string> = {
  collected: "bg-amber-100 text-amber-900",
  washing: "bg-sky-100 text-sky-900",
  ready: "bg-emerald-100 text-emerald-800",
  returned: "bg-slate-100 text-slate-700",
};

/** Blank is zero; anything else must be a whole number. */
function count(value: string): number {
  const n = Number(value.trim() || "0");
  return Number.isInteger(n) && n >= 0 ? n : NaN;
}

export function LaundryBoard() {
  const { t } = useLocale();
  const [openOnly, setOpenOnly] = useState(true);
  const [wards, setWards] = useState<{ id: string; name: string }[]>([]);
  const [batches, setBatches] = useState<LinenBatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBatches(await listBatches(openOnly));
      setError(null);
    } catch (reason) {
      setBatches(null);
      setError(reason instanceof ApiError ? reason.message : t("laundry.errLoad"));
    }
  }, [openOnly, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    getWardLocations().then((list) => setWards(list.map((w) => ({ id: w.ward_id, name: w.ward_name })))).catch(() => setWards([]));
  }, []);

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("laundry.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("laundry.intro")}</p>
      </div>
      <CollectForm wards={wards} onSaved={() => void load()} />
      <div className="flex gap-2 text-sm">
        <button type="button" onClick={() => setOpenOnly(true)}
          className={`rounded-md px-3 py-1 ${openOnly ? "bg-primary text-white" : "border border-border"}`}>{t("laundry.openTab")}</button>
        <button type="button" onClick={() => setOpenOnly(false)}
          className={`rounded-md px-3 py-1 ${!openOnly ? "bg-primary text-white" : "border border-border"}`}>{t("laundry.returnedTab")}</button>
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {batches === null && !error ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {batches && batches.length === 0 ? <p className="text-sm text-muted-foreground">{t("laundry.empty")}</p> : null}
      {batches && batches.length ? (
        <ul className="space-y-2">
          {batches.map((batch) => <BatchRow key={batch.id} batch={batch} onChanged={() => void load()} />)}
        </ul>
      ) : null}
    </div>
  );
}

function CollectForm({ wards, onSaved }: { wards: { id: string; name: string }[]; onSaved: () => void }) {
  const { t } = useLocale();
  const [wardId, setWardId] = useState("");
  const [source, setSource] = useState("");
  const [infected, setInfected] = useState(false);
  const [counts, setCounts] = useState<Partial<Record<LinenItemType, string>>>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const items = LINEN_ITEM_TYPES.map((item_type) => ({ item_type, quantity: count(counts[item_type] ?? "") }))
    .filter((line) => line.quantity !== 0);
  const valid = items.length > 0 && items.every((line) => Number.isInteger(line.quantity) && line.quantity > 0)
    && (wardId !== "" || source.trim() !== "");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await collectLinen({ ward_id: wardId || null, source: source.trim() || null, is_infected: infected, notes: null, items }, key);
      setCounts({});
      setInfected(false);
      setKey(newIdempotencyKey());
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("laundry.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 rounded border border-border p-4 text-sm">
      <p className="font-medium">{t("laundry.collectTitle")}</p>
      <div className="flex flex-wrap gap-3">
        <label>
          <span className="text-muted-foreground">{t("laundry.ward")}</span>
          <select value={wardId} onChange={(e) => setWardId(e.target.value)} className="mt-1 block rounded-md border border-border px-2 py-1.5">
            <option value="">{t("laundry.noWard")}</option>
            {wards.map((ward) => <option key={ward.id} value={ward.id}>{ward.name}</option>)}
          </select>
        </label>
        {wardId === "" ? (
          <label>
            <span className="text-muted-foreground">{t("laundry.source")}</span>
            <input value={source} onChange={(e) => setSource(e.target.value)} maxLength={120}
              className="mt-1 block rounded-md border border-border px-2 py-1.5" />
          </label>
        ) : null}
        <label className="flex items-center gap-2 self-end">
          <input type="checkbox" checked={infected} onChange={(e) => setInfected(e.target.checked)} />
          {t("laundry.infected")}
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        {LINEN_ITEM_TYPES.map((item) => (
          <label key={item} className="text-xs">
            <span className="text-muted-foreground">{t(`laundry.item.${item}` as "laundry.item.other")}</span>
            <input inputMode="numeric" value={counts[item] ?? ""} onChange={(e) => setCounts((c) => ({ ...c, [item]: e.target.value }))}
              className="mt-1 w-full rounded-md border border-border px-2 py-1" />
          </label>
        ))}
      </div>
      <button type="submit" disabled={!valid || busy} className="rounded-md bg-primary px-3 py-1.5 font-medium text-white disabled:opacity-50">
        {t("laundry.collect")}
      </button>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
    </form>
  );
}

function BatchRow({ batch, onChanged }: { batch: LinenBatch; onChanged: () => void }) {
  const { t } = useLocale();
  const next = NEXT_STATUS[batch.status];
  const [returned, setReturned] = useState<Partial<Record<LinenItemType, string>>>({});
  const [condemned, setCondemned] = useState<Partial<Record<LinenItemType, string>>>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const countsFor = batch.items.map((line) => ({
    item_type: line.item_type,
    returned: count(returned[line.item_type] ?? String(line.quantity)),
    condemned: count(condemned[line.item_type] ?? ""),
  }));
  const countsValid = countsFor.every((c, i) => Number.isInteger(c.returned) && Number.isInteger(c.condemned)
    && c.returned + c.condemned <= batch.items[i].quantity);

  async function move() {
    if (!next || busy || (next === "returned" && !countsValid)) return;
    setBusy(true);
    setError(null);
    try {
      await advanceBatch(batch.id, next === "returned" ? { status: next, counts: countsFor } : { status: next }, key);
      setKey(newIdempotencyKey());
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("laundry.errSave"));
    } finally {
      setBusy(false);
    }
  }

  const where = [batch.ward_name ?? batch.source, batch.bed_number ? t("kitchen.bed", { bed: batch.bed_number }) : null]
    .filter(Boolean).join(" · ");

  return (
    <li className="rounded border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {where || "—"}
            {batch.is_infected ? <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">{t("laundry.infectedBadge")}</span> : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("laundry.collectedAt", { when: formatDateTime(batch.collected_at) })}
            {batch.returned_at ? ` · ${t("laundry.returnedAt", { when: formatDateTime(batch.returned_at) })}` : ""}
          </p>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${BADGE[batch.status]}`}>
          {t(`laundry.status.${batch.status}` as "laundry.status.collected")}
        </span>
      </div>
      <ul className="mt-2 space-y-1 text-xs">
        {batch.items.map((line) => (
          <li key={line.item_type} className="flex flex-wrap items-center gap-2">
            <span className="min-w-28 font-medium">{t(`laundry.item.${line.item_type}` as "laundry.item.other")}</span>
            {line.returned_quantity !== null ? (
              <span className={line.missing_quantity ? "text-red-700" : ""}>
                {t("laundry.lineReturned", {
                  sent: line.quantity, returned: line.returned_quantity, condemned: line.condemned_quantity, missing: line.missing_quantity ?? 0,
                })}
              </span>
            ) : next === "returned" ? (
              <>
                <span>{t("laundry.lineSummary", { sent: line.quantity })}</span>
                <label className="flex items-center gap-1">{t("laundry.returnedCount")}
                  <input inputMode="numeric" value={returned[line.item_type] ?? String(line.quantity)}
                    onChange={(e) => setReturned((r) => ({ ...r, [line.item_type]: e.target.value }))}
                    className="w-16 rounded-md border border-border px-1 py-0.5" />
                </label>
                <label className="flex items-center gap-1">{t("laundry.condemned")}
                  <input inputMode="numeric" value={condemned[line.item_type] ?? ""}
                    onChange={(e) => setCondemned((c) => ({ ...c, [line.item_type]: e.target.value }))}
                    className="w-16 rounded-md border border-border px-1 py-0.5" />
                </label>
              </>
            ) : (
              <span>{t("laundry.lineSummary", { sent: line.quantity })}</span>
            )}
          </li>
        ))}
      </ul>
      {next ? (
        <button type="button" disabled={busy || (next === "returned" && !countsValid)} onClick={() => void move()}
          className="mt-2 rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
          {t("laundry.moveTo", { status: t(`laundry.status.${next}` as "laundry.status.collected") })}
        </button>
      ) : null}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p> : null}
    </li>
  );
}
