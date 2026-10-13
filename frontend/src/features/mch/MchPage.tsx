"use client";

/**
 * Maternal and child health: record only.
 *
 * Find the mother by UHID or mobile (exactly one match, never first-match),
 * register a pregnancy, record ANC visits, flag high risk with a reason, and
 * record the delivery and newborns. HealthDoc computes no schedule, due date
 * or risk: the clinician enters each of those (owner decision, 10 Oct 2026).
 *
 * Optional numbers are kept as typed text and sent as null when empty: an
 * empty number input read as a number is NaN, which blocks the whole form.
 */
import { useCallback, useState } from "react";

import { ApiError, api, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import {
  endPregnancy,
  flagRisk,
  listPregnancies,
  recordAncVisit,
  recordDelivery,
  registerPregnancy,
  type Pregnancy,
} from "./api";

type Found = { id: string; uhid: string; full_name: string };
const input = "w-full rounded-md border border-border px-2 py-1.5 text-sm";

function num(value: string): number | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : Number(trimmed);
}

function dec(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function message(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

export function MchPage() {
  const { t } = useLocale();
  const [term, setTerm] = useState("");
  const [patient, setPatient] = useState<Found | null>(null);
  const [pregnancies, setPregnancies] = useState<Pregnancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (found: Found) => {
    try {
      setPregnancies(await listPregnancies(found.id));
      setError(null);
    } catch (reason) {
      setError(message(reason, t("mch.errLoad")));
    }
  }, [t]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const value = term.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body = /^\d+$/.test(value) ? { mobile: value, page: 1, page_size: 5 } : { uhid: value, page: 1, page_size: 5 };
      const res = await api<{ items: Found[] }>("/patients/search", { method: "POST", idempotencyKey: null, body: JSON.stringify(body) });
      const items = res?.items ?? [];
      if (items.length !== 1) {
        setPatient(null);
        setPregnancies(null);
        setError(items.length === 0 ? t("mch.noMatch") : t("mch.manyMatches", { count: items.length }));
        return;
      }
      setPatient(items[0]);
      await load(items[0]);
    } catch (reason) {
      setError(message(reason, t("mch.errSearch")));
    } finally {
      setBusy(false);
    }
  }

  const active = pregnancies?.find((p) => p.status === "active") ?? null;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("mch.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("mch.intro")}</p>
      </div>
      <form onSubmit={search} className="flex flex-wrap gap-2">
        <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder={t("mch.searchPlaceholder")}
          className="min-w-64 flex-1 rounded-md border border-border px-3 py-2 text-sm" />
        <button type="submit" disabled={busy || !term.trim()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {t("common.search")}
        </button>
      </form>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {patient && pregnancies ? (
        <div className="space-y-4">
          <p className="text-sm">
            <span className="font-medium">{patient.full_name}</span> <span className="text-muted-foreground">{patient.uhid}</span>
          </p>
          {active ? (
            <ActivePregnancy pregnancy={active} onChanged={() => void load(patient)} />
          ) : (
            <RegisterPregnancy patientId={patient.id} onDone={() => void load(patient)} />
          )}
          {pregnancies.filter((p) => p.status !== "active").map((p) => (
            <ClosedPregnancy key={p.id} pregnancy={p} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RegisterPregnancy({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const { t } = useLocale();
  const [form, setForm] = useState({ lmp_date: "", edd: "", gravida: "", para: "", rch_id: "" });
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await registerPregnancy({
        patient_id: patientId, lmp_date: form.lmp_date || null, edd: form.edd || null,
        gravida: num(form.gravida), para: num(form.para), rch_id: form.rch_id.trim() || null,
      }, key);
      setKey(newIdempotencyKey());
      onDone();
    } catch (reason) {
      setError(message(reason, t("mch.errSave")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded border border-border p-4 md:grid-cols-5">
      <h2 className="text-sm font-semibold md:col-span-5">{t("mch.register")}</h2>
      <label className="text-xs">{t("mch.lmp")}<input type="date" className={input} value={form.lmp_date} onChange={(e) => setForm((f) => ({ ...f, lmp_date: e.target.value }))} /></label>
      <label className="text-xs">{t("mch.edd")}<input type="date" className={input} value={form.edd} onChange={(e) => setForm((f) => ({ ...f, edd: e.target.value }))} /></label>
      <label className="text-xs">{t("mch.gravida")}<input inputMode="numeric" className={input} value={form.gravida} onChange={(e) => setForm((f) => ({ ...f, gravida: e.target.value }))} /></label>
      <label className="text-xs">{t("mch.para")}<input inputMode="numeric" className={input} value={form.para} onChange={(e) => setForm((f) => ({ ...f, para: e.target.value }))} /></label>
      <label className="text-xs">{t("mch.rchId")}<input className={input} maxLength={30} value={form.rch_id} onChange={(e) => setForm((f) => ({ ...f, rch_id: e.target.value }))} /></label>
      <p className="text-xs text-muted-foreground md:col-span-4">{t("mch.eddNote")}</p>
      <button type="submit" disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{t("mch.registerButton")}</button>
      {error ? <p className="text-sm text-danger md:col-span-5" role="alert">{error}</p> : null}
    </form>
  );
}

function VisitTable({ pregnancy }: { pregnancy: Pregnancy }) {
  const { t } = useLocale();
  if (pregnancy.anc_visits.length === 0) return <p className="text-sm text-muted-foreground">{t("mch.noVisits")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 pr-3">{t("mch.visitDate")}</th><th className="py-1 pr-3">{t("mch.weeks")}</th>
            <th className="py-1 pr-3">{t("mch.weight")}</th><th className="py-1 pr-3">{t("mch.bp")}</th>
            <th className="py-1 pr-3">{t("mch.hb")}</th><th className="py-1 pr-3">{t("mch.fundal")}</th>
            <th className="py-1 pr-3">{t("mch.fhr")}</th><th className="py-1 pr-3">{t("mch.urine")}</th>
            <th className="py-1 pr-3">{t("mch.ifa")}</th><th className="py-1">{t("mch.notes")}</th>
          </tr>
        </thead>
        <tbody>
          {pregnancy.anc_visits.map((v) => (
            <tr key={v.id} className="border-t border-border">
              <td className="py-1 pr-3">{v.visit_date}</td><td className="py-1 pr-3">{v.gestation_weeks ?? "—"}</td>
              <td className="py-1 pr-3">{v.weight_kg ?? "—"}</td>
              <td className="py-1 pr-3">{v.bp_systolic !== null ? `${v.bp_systolic}/${v.bp_diastolic}` : "—"}</td>
              <td className="py-1 pr-3">{v.hemoglobin_g_dl ?? "—"}</td><td className="py-1 pr-3">{v.fundal_height_cm ?? "—"}</td>
              <td className="py-1 pr-3">{v.fetal_heart_rate ?? "—"}</td>
              <td className="py-1 pr-3">{[v.urine_albumin && `A ${v.urine_albumin}`, v.urine_sugar && `S ${v.urine_sugar}`].filter(Boolean).join(" · ") || "—"}</td>
              <td className="py-1 pr-3">{v.ifa_tablets ?? "—"}</td><td className="py-1">{v.notes ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const URINE = ["", "nil", "trace", "+", "++", "+++"];

function ActivePregnancy({ pregnancy, onChanged }: { pregnancy: Pregnancy; onChanged: () => void }) {
  const { t } = useLocale();
  const empty = { visit_date: "", gestation_weeks: "", weight_kg: "", bp_systolic: "", bp_diastolic: "", hemoglobin_g_dl: "",
    fundal_height_cm: "", fetal_heart_rate: "", urine_albumin: "", urine_sugar: "", ifa_tablets: "", notes: "" };
  const [visit, setVisit] = useState(empty);
  const [riskReason, setRiskReason] = useState("");
  const [endReason, setEndReason] = useState("");
  const [delivery, setDelivery] = useState({ delivered_at: "", mode: "normal", notes: "" });
  const [babies, setBabies] = useState([{ outcome: "live_birth", sex: "female", birth_weight_g: "" }]);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setKey(newIdempotencyKey());
      after?.();
      onChanged();
    } catch (reason) {
      setError(message(reason, t("mch.errSave")));
    } finally {
      setBusy(false);
    }
  }

  const field = (name: keyof typeof empty, label: string, mode: "numeric" | "decimal" = "numeric") => (
    <label className="text-xs">{label}
      <input inputMode={mode} className={input} value={visit[name]} onChange={(e) => setVisit((v) => ({ ...v, [name]: e.target.value }))} />
    </label>
  );

  return (
    <section className="space-y-4 rounded border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("mch.activePregnancy")}</h2>
        {pregnancy.high_risk ? (
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">{t("mch.highRisk")}: {pregnancy.high_risk_reason}</span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">
        {[pregnancy.lmp_date && `${t("mch.lmp")} ${pregnancy.lmp_date}`, pregnancy.edd && `${t("mch.edd")} ${pregnancy.edd}`,
          pregnancy.gravida !== null && `G${pregnancy.gravida}`, pregnancy.para !== null && `P${pregnancy.para}`,
          pregnancy.rch_id && `RCH ${pregnancy.rch_id}`].filter(Boolean).join(" · ")}
      </p>
      <VisitTable pregnancy={pregnancy} />

      <form noValidate className="grid gap-2 border-t border-border pt-3 md:grid-cols-6"
        onSubmit={(e) => {
          e.preventDefault();
          void act(() => recordAncVisit(pregnancy.id, {
            visit_date: visit.visit_date, gestation_weeks: num(visit.gestation_weeks), weight_kg: dec(visit.weight_kg),
            bp_systolic: num(visit.bp_systolic), bp_diastolic: num(visit.bp_diastolic), hemoglobin_g_dl: dec(visit.hemoglobin_g_dl),
            fundal_height_cm: num(visit.fundal_height_cm), fetal_heart_rate: num(visit.fetal_heart_rate),
            urine_albumin: visit.urine_albumin || null, urine_sugar: visit.urine_sugar || null,
            ifa_tablets: num(visit.ifa_tablets), notes: visit.notes.trim() || null,
          }, key), () => setVisit(empty));
        }}>
        <h3 className="text-xs font-semibold md:col-span-6">{t("mch.addVisit")}</h3>
        <label className="text-xs">{t("mch.visitDate")}<input type="date" className={input} value={visit.visit_date} onChange={(e) => setVisit((v) => ({ ...v, visit_date: e.target.value }))} /></label>
        {field("gestation_weeks", t("mch.weeks"))}
        {field("weight_kg", t("mch.weight"), "decimal")}
        {field("bp_systolic", t("mch.bpSys"))}
        {field("bp_diastolic", t("mch.bpDia"))}
        {field("hemoglobin_g_dl", t("mch.hb"), "decimal")}
        {field("fundal_height_cm", t("mch.fundal"))}
        {field("fetal_heart_rate", t("mch.fhr"))}
        <label className="text-xs">{t("mch.urineAlbumin")}
          <select className={input} value={visit.urine_albumin} onChange={(e) => setVisit((v) => ({ ...v, urine_albumin: e.target.value }))}>
            {URINE.map((u) => <option key={u} value={u}>{u || "—"}</option>)}
          </select>
        </label>
        <label className="text-xs">{t("mch.urineSugar")}
          <select className={input} value={visit.urine_sugar} onChange={(e) => setVisit((v) => ({ ...v, urine_sugar: e.target.value }))}>
            {URINE.map((u) => <option key={u} value={u}>{u || "—"}</option>)}
          </select>
        </label>
        {field("ifa_tablets", t("mch.ifa"))}
        <label className="text-xs md:col-span-5">{t("mch.notes")}<input className={input} maxLength={1000} value={visit.notes} onChange={(e) => setVisit((v) => ({ ...v, notes: e.target.value }))} /></label>
        <button type="submit" disabled={busy || !visit.visit_date} className="self-end rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{t("mch.saveVisit")}</button>
      </form>

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
        {pregnancy.high_risk ? (
          <button type="button" disabled={busy} className="rounded-md border border-border px-3 py-1.5 text-xs"
            onClick={() => void act(() => flagRisk(pregnancy.id, { high_risk: false, reason: null }, key))}>{t("mch.clearRisk")}</button>
        ) : (
          <>
            <label className="min-w-64 flex-1 text-xs">{t("mch.riskReason")}<input className={input} maxLength={500} value={riskReason} onChange={(e) => setRiskReason(e.target.value)} /></label>
            <button type="button" disabled={busy || !riskReason.trim()} className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 disabled:opacity-50"
              onClick={() => void act(() => flagRisk(pregnancy.id, { high_risk: true, reason: riskReason.trim() }, key), () => setRiskReason(""))}>{t("mch.flagRisk")}</button>
          </>
        )}
      </div>

      <form noValidate className="grid gap-2 border-t border-border pt-3 md:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault();
          const at = new Date(delivery.delivered_at);
          if (Number.isNaN(at.getTime())) return;
          void act(() => recordDelivery(pregnancy.id, {
            delivered_at: at.toISOString(), mode: delivery.mode, notes: delivery.notes.trim() || null,
            newborns: babies.map((b) => ({ outcome: b.outcome, sex: b.sex, birth_weight_g: num(b.birth_weight_g) })),
          }, key));
        }}>
        <h3 className="text-xs font-semibold md:col-span-4">{t("mch.recordDelivery")}</h3>
        <label className="text-xs">{t("mch.deliveredAt")}<input type="datetime-local" className={input} value={delivery.delivered_at} onChange={(e) => setDelivery((d) => ({ ...d, delivered_at: e.target.value }))} /></label>
        <label className="text-xs">{t("mch.mode")}
          <select className={input} value={delivery.mode} onChange={(e) => setDelivery((d) => ({ ...d, mode: e.target.value }))}>
            <option value="normal">{t("mch.mode.normal")}</option><option value="assisted">{t("mch.mode.assisted")}</option><option value="caesarean">{t("mch.mode.caesarean")}</option>
          </select>
        </label>
        <label className="text-xs md:col-span-2">{t("mch.notes")}<input className={input} maxLength={1000} value={delivery.notes} onChange={(e) => setDelivery((d) => ({ ...d, notes: e.target.value }))} /></label>
        {babies.map((baby, index) => (
          <div key={index} className="grid gap-2 md:col-span-4 md:grid-cols-4">
            <label className="text-xs">{t("mch.outcome")}
              <select className={input} value={baby.outcome} onChange={(e) => setBabies((all) => all.map((b, i) => (i === index ? { ...b, outcome: e.target.value } : b)))}>
                <option value="live_birth">{t("mch.liveBirth")}</option><option value="still_birth">{t("mch.stillBirth")}</option>
              </select>
            </label>
            <label className="text-xs">{t("mch.sex")}
              <select className={input} value={baby.sex} onChange={(e) => setBabies((all) => all.map((b, i) => (i === index ? { ...b, sex: e.target.value } : b)))}>
                <option value="female">{t("mch.sex.female")}</option><option value="male">{t("mch.sex.male")}</option>
                <option value="other">{t("mch.sex.other")}</option><option value="unknown">{t("mch.sex.unknown")}</option>
              </select>
            </label>
            <label className="text-xs">{t("mch.birthWeight")}<input inputMode="numeric" className={input} value={baby.birth_weight_g} onChange={(e) => setBabies((all) => all.map((b, i) => (i === index ? { ...b, birth_weight_g: e.target.value } : b)))} /></label>
            {babies.length > 1 ? (
              <button type="button" className="self-end text-xs underline" onClick={() => setBabies((all) => all.filter((_, i) => i !== index))}>{t("mch.removeBaby")}</button>
            ) : <span />}
          </div>
        ))}
        <button type="button" className="text-left text-xs underline md:col-span-3" disabled={babies.length >= 6}
          onClick={() => setBabies((all) => [...all, { outcome: "live_birth", sex: "female", birth_weight_g: "" }])}>{t("mch.addBaby")}</button>
        <button type="submit" disabled={busy || !delivery.delivered_at} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{t("mch.saveDelivery")}</button>
      </form>

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
        <label className="min-w-64 flex-1 text-xs">{t("mch.endReason")}<input className={input} maxLength={500} value={endReason} onChange={(e) => setEndReason(e.target.value)} /></label>
        <button type="button" disabled={busy || !endReason.trim()} className="rounded-md border border-border px-3 py-1.5 text-xs disabled:opacity-50"
          onClick={() => void act(() => endPregnancy(pregnancy.id, endReason.trim(), key))}>{t("mch.endPregnancy")}</button>
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
    </section>
  );
}

function ClosedPregnancy({ pregnancy }: { pregnancy: Pregnancy }) {
  const { t } = useLocale();
  return (
    <section className="space-y-2 rounded border border-border p-4 text-sm">
      <p className="font-medium">
        {pregnancy.status === "delivered" && pregnancy.delivery
          ? t("mch.deliveredOn", { when: formatDateTime(pregnancy.delivery.delivered_at), mode: pregnancy.delivery.mode })
          : t("mch.endedWith", { reason: pregnancy.end_reason ?? "" })}
      </p>
      {pregnancy.delivery?.newborns.map((b) => (
        <p key={b.id} className="text-xs text-muted-foreground">{b.outcome.replace("_", " ")} · {b.sex}{b.birth_weight_g ? ` · ${b.birth_weight_g} g` : ""}</p>
      ))}
      <VisitTable pregnancy={pregnancy} />
    </section>
  );
}
