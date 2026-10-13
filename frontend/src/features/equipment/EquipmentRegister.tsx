"use client";

/**
 * A facility's machines and whether they work. Anyone who uses a machine can
 * report it down (with what is wrong) or back in service; only an admin
 * registers or retires one. Not-working machines sort first. A failed load
 * says so: an empty list would read as "this hospital has no equipment".
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";

import {
  EQUIPMENT_CATEGORIES,
  changeEquipmentStatus,
  equipmentHistory,
  listEquipment,
  registerEquipment,
  type EquipmentCategory,
  type EquipmentEvent,
  type EquipmentItem,
  type EquipmentStatus,
} from "./api";

const BADGE: Record<EquipmentStatus, string> = {
  working: "bg-emerald-100 text-emerald-800",
  down: "bg-red-100 text-red-800",
  maintenance: "bg-amber-100 text-amber-900",
  retired: "bg-slate-100 text-slate-600",
};

export function EquipmentRegister() {
  const { t } = useLocale();
  const { user } = useAuth();
  // The server is the authority (register and retire are admin-only there);
  // this only hides controls an admin's colleagues cannot use.
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<EquipmentItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listEquipment());
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("equipment.errLoad"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const notWorking = items?.filter((item) => item.status === "down" || item.status === "maintenance").length ?? 0;

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("equipment.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("equipment.intro")}</p>
      </div>
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {isAdmin ? <RegisterForm onSaved={() => void load()} /> : null}
      {items === null && !error ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {items ? (
        <>
          <p className="text-sm">{t("equipment.summary", { total: items.length, down: notWorking })}</p>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("equipment.empty")}</p>
          ) : (
            <ul className="space-y-2">
              {items.map((item) => (
                <EquipmentRow key={item.id} item={item} isAdmin={isAdmin} onChanged={() => void load()} />
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}

function RegisterForm({ onSaved }: { onSaved: () => void }) {
  const { t } = useLocale();
  const [name, setName] = useState("");
  const [category, setCategory] = useState<EquipmentCategory>("other");
  const [location, setLocation] = useState("");
  const [assetTag, setAssetTag] = useState("");
  const [critical, setCritical] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await registerEquipment(
        { name: name.trim(), category, location: location.trim() || null, asset_tag: assetTag.trim() || null, is_critical: critical },
        key,
      );
      setName("");
      setLocation("");
      setAssetTag("");
      setCritical(false);
      setKey(newIdempotencyKey());
      onSaved();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("equipment.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded border border-border p-4 md:grid-cols-6">
      <label className="text-sm md:col-span-2">
        <span className="text-muted-foreground">{t("equipment.name")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} className="mt-1 w-full rounded-md border border-border px-2 py-1.5" />
      </label>
      <label className="text-sm">
        <span className="text-muted-foreground">{t("equipment.category")}</span>
        <select value={category} onChange={(e) => setCategory(e.target.value as EquipmentCategory)} className="mt-1 w-full rounded-md border border-border px-2 py-1.5">
          {EQUIPMENT_CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {t(`equipment.category.${value}` as "equipment.category.other")}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="text-muted-foreground">{t("equipment.location")}</span>
        <input value={location} onChange={(e) => setLocation(e.target.value)} maxLength={120} className="mt-1 w-full rounded-md border border-border px-2 py-1.5" />
      </label>
      <label className="text-sm">
        <span className="text-muted-foreground">{t("equipment.assetTag")}</span>
        <input value={assetTag} onChange={(e) => setAssetTag(e.target.value)} maxLength={60} className="mt-1 w-full rounded-md border border-border px-2 py-1.5" />
      </label>
      <div className="flex flex-col justify-end gap-2 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={critical} onChange={(e) => setCritical(e.target.checked)} />
          {t("equipment.critical")}
        </label>
        <button type="submit" disabled={busy || !name.trim()} className="rounded-md bg-primary px-3 py-1.5 font-medium text-white disabled:opacity-50">
          {t("equipment.register")}
        </button>
      </div>
      {error ? (
        <p className="text-sm text-danger md:col-span-6" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function EquipmentRow({ item, isAdmin, onChanged }: { item: EquipmentItem; isAdmin: boolean; onChanged: () => void }) {
  const { t } = useLocale();
  const [next, setNext] = useState<EquipmentStatus | "">("");
  const [reason, setReason] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<EquipmentEvent[] | null>(null);

  const options: EquipmentStatus[] = (["working", "down", "maintenance", ...(isAdmin ? (["retired"] as const) : [])] as EquipmentStatus[]).filter(
    (status) => status !== item.status,
  );
  const needsReason = next !== "" && next !== "working";

  async function submit() {
    if (!next || busy || (needsReason && !reason.trim())) return;
    setBusy(true);
    setError(null);
    try {
      await changeEquipmentStatus(item.id, { status: next, reason: reason.trim() || null }, key);
      setNext("");
      setReason("");
      setKey(newIdempotencyKey());
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("equipment.errSave"));
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistory() {
    if (history) {
      setHistory(null);
      return;
    }
    try {
      setHistory(await equipmentHistory(item.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("equipment.errLoad"));
    }
  }

  return (
    <li className="rounded border border-border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {item.name}
            {item.is_critical ? <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">{t("equipment.critical")}</span> : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {[t(`equipment.category.${item.category}` as "equipment.category.other"), item.location, item.asset_tag].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="text-right">
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${BADGE[item.status]}`}>{t(`equipment.status.${item.status}` as "equipment.status.working")}</span>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("equipment.since")} {formatDateTime(item.status_since)}
          </p>
          {item.status_reason ? <p className="text-xs">{item.status_reason}</p> : null}
        </div>
      </div>
      {item.status !== "retired" ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select value={next} onChange={(e) => setNext(e.target.value as EquipmentStatus | "")} className="rounded-md border border-border px-2 py-1 text-xs">
            <option value="">{t("equipment.changeStatus")}</option>
            {options.map((status) => (
              <option key={status} value={status}>
                {t(`equipment.status.${status}` as "equipment.status.working")}
              </option>
            ))}
          </select>
          {needsReason ? (
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              placeholder={t("equipment.reasonPlaceholder")}
              className="min-w-64 flex-1 rounded-md border border-border px-2 py-1 text-xs"
            />
          ) : null}
          {next ? (
            <button
              type="button"
              disabled={busy || (needsReason && !reason.trim())}
              onClick={() => void submit()}
              className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              {t("common.save")}
            </button>
          ) : null}
          <button type="button" onClick={() => void toggleHistory()} className="text-xs underline">
            {history ? t("equipment.hideHistory") : t("equipment.showHistory")}
          </button>
        </div>
      ) : null}
      {error ? (
        <p className="mt-1 text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {history ? (
        <ul className="mt-2 space-y-1 border-t border-border pt-2 text-xs text-muted-foreground">
          {history.map((event, index) => (
            <li key={`${event.changed_at}-${index}`}>
              {formatDateTime(event.changed_at)} · {event.from_status ?? "—"} → {event.to_status} · {event.changed_by}
              {event.reason ? ` · ${event.reason}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
