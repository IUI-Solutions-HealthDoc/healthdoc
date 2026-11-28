"use client";

/**
 * The kitchen board: every admitted patient by ward and bed, the diet in
 * force, and the chosen day's meals. Doctors and nurses set or stop a diet;
 * ward staff and the services supervisor record each meal. A patient with no
 * diet order is listed, not hidden, and a nil-by-mouth patient says so in red.
 * A failed load says so: an empty board would read as "nobody is admitted".
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { getWardLocations } from "@/lib/wardLocations";

import {
  DIET_TYPES,
  MEAL_STATUSES,
  getKitchenBoard,
  orderDiet,
  recordMeal,
  stopDiet,
  type BoardRow,
  type DietType,
  type KitchenBoard as Board,
  type Meal,
  type MealStatus,
} from "./api";

const MEAL_BADGE: Record<MealStatus, string> = {
  served: "bg-emerald-100 text-emerald-800",
  refused: "bg-amber-100 text-amber-900",
  not_served: "bg-red-100 text-red-800",
};

function istToday(): string {
  // The ward's calendar day, not UTC's: en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

export function KitchenBoard() {
  const { t } = useLocale();
  const { user } = useAuth();
  // The server is the authority on both; these only hide controls a role cannot use.
  const canOrder = user?.role === "doctor" || user?.role === "nurse";
  const canServe = ["nurse", "admin", "hod", "supervisor"].includes(user?.role ?? "");
  const [day, setDay] = useState(istToday);
  const [wardId, setWardId] = useState<string>("");
  const [wards, setWards] = useState<{ id: string; name: string }[]>([]);
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBoard(await getKitchenBoard(day, wardId || null));
      setError(null);
    } catch (reason) {
      setBoard(null);
      setError(reason instanceof ApiError ? reason.message : t("kitchen.errLoad"));
    }
  }, [day, wardId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    getWardLocations().then((list) => setWards(list.map((w) => ({ id: w.ward_id, name: w.ward_name })))).catch(() => setWards([]));
  }, []);

  const rows = board?.rows ?? [];
  const noOrder = rows.filter((row) => !row.diet).length;
  const npo = rows.filter((row) => row.diet?.diet_type === "npo").length;

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("kitchen.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("kitchen.intro")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label>
          <span className="text-muted-foreground">{t("kitchen.date")}</span>
          <input type="date" value={day} max={istToday()} onChange={(e) => e.target.value && setDay(e.target.value)}
            className="mt-1 block rounded-md border border-border px-2 py-1.5" />
        </label>
        <label>
          <span className="text-muted-foreground">{t("kitchen.ward")}</span>
          <select value={wardId} onChange={(e) => setWardId(e.target.value)} className="mt-1 block rounded-md border border-border px-2 py-1.5">
            <option value="">{t("kitchen.allWards")}</option>
            {wards.map((ward) => (
              <option key={ward.id} value={ward.id}>{ward.name}</option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {board === null && !error ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {board ? (
        <>
          <p className="text-sm">{t("kitchen.summary", { total: rows.length, noOrder, npo })}</p>
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("kitchen.empty")}</p>
          ) : (
            <ul className="space-y-2">
              {rows.map((row) => (
                <PatientRow key={row.admission_id} row={row} day={board.service_date} meals={board.meals}
                  canOrder={canOrder} canServe={canServe} onChanged={() => void load()} />
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}

function PatientRow({ row, day, meals, canOrder, canServe, onChanged }: {
  row: BoardRow; day: string; meals: Meal[]; canOrder: boolean; canServe: boolean; onChanged: () => void;
}) {
  const { t } = useLocale();
  const [editing, setEditing] = useState(false);
  const isNpo = row.diet?.diet_type === "npo";
  const recorded = new Set(row.meals.map((m) => m.meal));

  return (
    <li className={`rounded border p-3 text-sm ${isNpo ? "border-red-300" : "border-border"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{row.patient_name ?? row.uhid ?? "—"}</p>
          <p className="text-xs text-muted-foreground">
            {row.ward_name} · {t("kitchen.bed", { bed: row.bed_number })}{row.uhid ? ` · ${row.uhid}` : ""}
          </p>
        </div>
        <div className="text-right">
          {row.diet ? (
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${isNpo ? "bg-red-100 text-red-800" : "bg-sky-100 text-sky-900"}`}>
              {t(`kitchen.diet.${row.diet.diet_type}` as "kitchen.diet.normal")}
            </span>
          ) : (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">{t("kitchen.noOrder")}</span>
          )}
          {row.diet?.instructions ? <p className="mt-1 text-xs">{row.diet.instructions}</p> : null}
          {row.diet?.food_allergies ? (
            <p className="text-xs font-medium text-red-700">{t("kitchen.allergies", { text: row.diet.food_allergies })}</p>
          ) : null}
          {isNpo ? <p className="text-xs font-semibold text-red-700">{t("kitchen.npoWarning")}</p> : null}
        </div>
      </div>
      {row.meals.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {meals.filter((m) => recorded.has(m)).map((meal) => {
            const record = row.meals.find((m) => m.meal === meal)!;
            return (
              <span key={meal} className={`rounded px-2 py-0.5 text-xs ${MEAL_BADGE[record.status]}`}
                title={record.notes ?? undefined}>
                {t(`kitchen.meal.${meal}` as "kitchen.meal.lunch")}: {t(`kitchen.status.${record.status}` as "kitchen.status.served")}
              </span>
            );
          })}
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap items-start gap-3">
        {canServe ? (
          <MealForm row={row} day={day} pending={meals.filter((m) => !recorded.has(m))} isNpo={isNpo} onSaved={onChanged} />
        ) : null}
        {canOrder ? (
          <button type="button" onClick={() => setEditing((v) => !v)} className="text-xs underline">
            {row.diet ? t("kitchen.changeDiet") : t("kitchen.setDiet")}
          </button>
        ) : null}
      </div>
      {editing && canOrder ? (
        <DietForm row={row} onSaved={() => { setEditing(false); onChanged(); }} />
      ) : null}
    </li>
  );
}

function MealForm({ row, day, pending, isNpo, onSaved }: {
  row: BoardRow; day: string; pending: Meal[]; isNpo: boolean; onSaved: () => void;
}) {
  const { t } = useLocale();
  const [meal, setMeal] = useState<Meal | "">("");
  const [status, setStatus] = useState<MealStatus>(isNpo ? "not_served" : "served");
  const [notes, setNotes] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsReason = status === "not_served";

  if (pending.length === 0) return <p className="text-xs text-muted-foreground">{t("kitchen.allRecorded")}</p>;

  async function submit() {
    if (!meal || busy || (needsReason && !notes.trim())) return;
    setBusy(true);
    setError(null);
    try {
      await recordMeal({ admission_id: row.admission_id, service_date: day, meal, status, notes: notes.trim() || null }, key);
      setMeal("");
      setNotes("");
      setKey(newIdempotencyKey());
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("kitchen.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select aria-label={t("kitchen.meal")} value={meal} onChange={(e) => setMeal(e.target.value as Meal | "")}
        className="rounded-md border border-border px-2 py-1 text-xs">
        <option value="">{t("kitchen.recordMeal")}…</option>
        {pending.map((m) => (
          <option key={m} value={m}>{t(`kitchen.meal.${m}` as "kitchen.meal.lunch")}</option>
        ))}
      </select>
      {meal ? (
        <>
          <select aria-label={t("kitchen.outcome")} value={status} onChange={(e) => setStatus(e.target.value as MealStatus)}
            className="rounded-md border border-border px-2 py-1 text-xs">
            {MEAL_STATUSES.filter((s) => !(isNpo && s === "served")).map((s) => (
              <option key={s} value={s}>{t(`kitchen.status.${s}` as "kitchen.status.served")}</option>
            ))}
          </select>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500}
            placeholder={needsReason ? t("kitchen.notServedReason") : t("kitchen.notes")}
            className="min-w-48 rounded-md border border-border px-2 py-1 text-xs" />
          <button type="button" disabled={busy || (needsReason && !notes.trim())} onClick={() => void submit()}
            className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
            {t("common.save")}
          </button>
        </>
      ) : null}
      {error ? <p className="w-full text-xs text-danger" role="alert">{error}</p> : null}
    </div>
  );
}

function DietForm({ row, onSaved }: { row: BoardRow; onSaved: () => void }) {
  const { t } = useLocale();
  const [dietType, setDietType] = useState<DietType>(row.diet?.diet_type ?? "normal");
  const [instructions, setInstructions] = useState(row.diet?.instructions ?? "");
  const [allergies, setAllergies] = useState(row.diet?.food_allergies ?? "");
  const [stopReason, setStopReason] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsInstructions = dietType === "other";

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      setKey(newIdempotencyKey());
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("kitchen.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2 grid gap-2 rounded border border-border p-3 md:grid-cols-4">
      <label className="text-xs">
        <span className="text-muted-foreground">{t("kitchen.dietType")}</span>
        <select value={dietType} onChange={(e) => setDietType(e.target.value as DietType)}
          className="mt-1 w-full rounded-md border border-border px-2 py-1">
          {DIET_TYPES.map((d) => (
            <option key={d} value={d}>{t(`kitchen.diet.${d}` as "kitchen.diet.normal")}</option>
          ))}
        </select>
      </label>
      <label className="text-xs md:col-span-2">
        <span className="text-muted-foreground">{t("kitchen.instructions")}</span>
        <input value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={1000}
          className="mt-1 w-full rounded-md border border-border px-2 py-1" />
      </label>
      <label className="text-xs">
        <span className="text-muted-foreground">{t("kitchen.foodAllergies")}</span>
        <input value={allergies} onChange={(e) => setAllergies(e.target.value)} maxLength={500}
          className="mt-1 w-full rounded-md border border-border px-2 py-1" />
      </label>
      <div className="flex flex-wrap items-center gap-2 md:col-span-4">
        <button type="button" disabled={busy || (needsInstructions && !instructions.trim())}
          onClick={() => void run(() => orderDiet({
            admission_id: row.admission_id, diet_type: dietType,
            instructions: instructions.trim() || null, food_allergies: allergies.trim() || null,
          }, key))}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50">
          {t("common.save")}
        </button>
        {row.diet ? (
          <>
            <input value={stopReason} onChange={(e) => setStopReason(e.target.value)} maxLength={500}
              placeholder={t("kitchen.stopReason")} className="min-w-48 rounded-md border border-border px-2 py-1 text-xs" />
            <button type="button" disabled={busy || !stopReason.trim()}
              onClick={() => void run(() => stopDiet(row.diet!.id, stopReason.trim(), key))}
              className="text-xs underline disabled:opacity-50">
              {t("kitchen.stopDiet")}
            </button>
          </>
        ) : null}
      </div>
      {error ? <p className="text-xs text-danger md:col-span-4" role="alert">{error}</p> : null}
    </div>
  );
}
