"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  checkHpid,
  confirmHpidMobile,
  createHpid,
  hprCategories,
  hprDistricts,
  hprStates,
  startHpid,
  verifyHpidMobile,
  type HpidKyc,
  type HprCategory,
  type HprOption,
} from "./api/hpr";

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50";
const secondary = "rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50";
// HPR's own rules, checked here so Create stays disabled; HealthDoc and HPR check again.
const HPR_ID = /^[a-z0-9][a-z0-9._]{3,47}$/;
const PASSWORD = /^(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9]).{8,64}$/;
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

function failure(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

type Stage =
  | { kind: "idle" }
  | { kind: "aadhaar"; session: string; url: string; waiting: boolean }
  | { kind: "existing"; hprId: string }
  | { kind: "verified"; session: string; kyc: HpidKyc; hint: string | null; suggestions: string[]; mobileVerified: boolean; otpSent: boolean }
  | { kind: "done"; hprId: string; number: string };

/**
 * Create an HPID for a health professional (M4 HPR-002 to 011). They verify
 * their Aadhaar on NHA's own page; their name and photo come from that KYC
 * and cannot be edited. The new HPID signs them in to HPR, so registration
 * in HPR can follow.
 */
export function HpidCreation({ onCreated }: { onCreated?: () => void }) {
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try { await action(); } catch (reason) { setError(failure(reason, fallback)); } finally { setBusy(false); }
  }

  const begin = () => run(async () => {
    const started = await startHpid();
    setStage({ kind: "aadhaar", session: started.session_id, url: started.url, waiting: false });
  }, "HPR did not open the Aadhaar verification.");

  const check = (session: string, url: string) => run(async () => {
    const result = await checkHpid(session);
    if (!result.authenticated) { setStage({ kind: "aadhaar", session, url, waiting: true }); return; }
    if ("existing_hpr_id" in result) { setStage({ kind: "existing", hprId: result.existing_hpr_id }); return; }
    setStage({ kind: "verified", session, kyc: result.kyc, hint: result.aadhaar_mobile_hint,
      suggestions: result.suggestions, mobileVerified: result.mobile_verified, otpSent: false });
  }, "HPR did not answer. Check again.");

  return (
    <section className="surface-card space-y-3 p-5" aria-label="Create an HPID">
      <h2 className="text-lg font-semibold">Create an HPID for a health professional</h2>
      {stage.kind === "idle" ? (
        <>
          <p className="text-sm text-muted-foreground">For a doctor or nurse without a Healthcare Professional ID. They verify their Aadhaar on NHA&apos;s own page; HealthDoc never sees the Aadhaar number or its OTP.</p>
          <button type="button" className={primary} disabled={busy} onClick={() => void begin()}>Start</button>
        </>
      ) : null}

      {stage.kind === "aadhaar" ? (
        <div className="space-y-2 text-sm">
          <p>Ask the professional to verify their Aadhaar on NHA&apos;s page, then come back here.</p>
          <a href={stage.url} target="_blank" rel="noopener noreferrer" className="font-medium underline">Open NHA&apos;s Aadhaar verification</a>
          {stage.waiting ? <p role="status">NHA has not confirmed the Aadhaar verification yet.</p> : null}
          <div className="flex gap-2">
            <button type="button" className={primary} disabled={busy} onClick={() => void check(stage.session, stage.url)}>{busy ? "Checking…" : "I have verified on NHA's page"}</button>
            <button type="button" className={secondary} disabled={busy} onClick={() => setStage({ kind: "idle" })}>Cancel</button>
          </div>
        </div>
      ) : null}

      {stage.kind === "existing" ? (
        <div role="status" className="space-y-2 text-sm">
          <p>This Aadhaar already holds the HPR ID <span className="font-mono">{stage.hprId}</span>. A person has one HPID; sign in with it above instead.</p>
          <button type="button" className={secondary} onClick={() => setStage({ kind: "idle" })}>Done</button>
        </div>
      ) : null}

      {stage.kind === "verified" ? (
        <Verified stage={stage} busy={busy} run={run}
          update={(change) => setStage({ ...stage, ...change })}
          finish={(hprId, number) => { setStage({ kind: "done", hprId, number }); onCreated?.(); }} />
      ) : null}

      {stage.kind === "done" ? (
        <div role="status" className="space-y-1 text-sm">
          <p className="font-medium">HPID created: <span className="font-mono">{stage.hprId}</span> ({stage.number}).</p>
          <p>They are signed in to HPR above, so their HPR registration can follow.</p>
        </div>
      ) : null}

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}

function useOptions(load: (() => Promise<HprOption[]>) | null, key: string | null) {
  const [state, setState] = useState<{ key: string | null; rows: HprOption[] | null; error: string | null }>({ key: null, rows: null, error: null });
  useEffect(() => {
    if (!load || !key) return;
    let live = true;
    load().then((rows) => { if (live) setState({ key, rows, error: null }); },
      (reason: unknown) => { if (live) setState({ key, rows: null, error: failure(reason, "HPR did not return this list.") }); });
    return () => { live = false; };
    // The loader is rebuilt each render; the key says when the list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state.key === key ? state : { rows: null, error: null };
}

function Pick({ name, label, value, list, onChange }: {
  name: string; label: string; value: string; list: { rows: HprOption[] | null; error: string | null }; onChange: (value: string) => void;
}) {
  return (
    <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>
      <select name={name} value={value} onChange={(e) => onChange(e.target.value)} disabled={!list.rows} className={input}>
        <option value="">{list.rows ? "Choose" : list.error ? "Unavailable" : "Loading…"}</option>
        {(list.rows ?? []).map((row) => <option key={row.code} value={row.code}>{row.label}</option>)}
      </select>
      {list.error ? <span role="alert" className="text-danger">{list.error}</span> : null}
    </label>
  );
}

function Verified({ stage, busy, run, update, finish }: {
  stage: Extract<Stage, { kind: "verified" }>; busy: boolean;
  run: (action: () => Promise<void>, fallback: string) => Promise<void>;
  update: (change: Partial<Extract<Stage, { kind: "verified" }>>) => void;
  finish: (hprId: string, number: string) => void;
}) {
  const { kyc } = stage;
  const [mobile, setMobile] = useState("");
  const [otp, setOtp] = useState("");
  const [form, setForm] = useState({ hpr_id: stage.suggestions[0] ?? "", email: kyc.email, password: "", confirm: "",
    category: "", subcategory: "", state: "", district: "" });
  const [categories, setCategories] = useState<HprCategory[] | null>(null);
  useEffect(() => {
    let live = true;
    hprCategories().then((rows) => { if (live) setCategories(rows); }, () => { if (live) setCategories([]); });
    return () => { live = false; };
  }, []);
  const states = useOptions(hprStates, "states");
  const districts = useOptions(form.state ? () => hprDistricts(form.state) : null, form.state ? `districts:${form.state}` : null);
  const set = (field: keyof typeof form, value: string) => setForm((current) => ({
    ...current, [field]: value,
    ...(field === "category" ? { subcategory: "" } : {}), ...(field === "state" ? { district: "" } : {}),
  }));
  const subcategories = categories?.find((row) => row.code === form.category)?.subcategories ?? [];
  const namePart = [kyc.first_name, kyc.last_name].filter(Boolean).some((part) => form.password.toLowerCase().includes(part.toLowerCase()));
  const ready = stage.mobileVerified && HPR_ID.test(form.hpr_id) && EMAIL.test(form.email) && PASSWORD.test(form.password)
    && !namePart && form.password === form.confirm && form.category && form.subcategory && form.state && form.district;

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4 text-sm">
        {kyc.photo ? (
          // eslint-disable-next-line @next/next/no-img-element -- Aadhaar's KYC photo as a one-use data URI, not an optimisable asset
          <img src={`data:image/jpeg;base64,${kyc.photo}`} alt="Photograph from Aadhaar" className="h-20 w-16 rounded object-cover" />
        ) : null}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">Name (from Aadhaar)</dt><dd>{kyc.name}</dd>
          {kyc.gender ? <><dt className="text-muted-foreground">Gender</dt><dd>{kyc.gender}</dd></> : null}
          {kyc.birth_date || kyc.year_of_birth ? <><dt className="text-muted-foreground">Date of birth</dt><dd>{kyc.birth_date || kyc.year_of_birth}</dd></> : null}
          {kyc.district_name || kyc.state_name ? <><dt className="text-muted-foreground">District, state</dt><dd>{[kyc.district_name, kyc.state_name].filter(Boolean).join(", ")}</dd></> : null}
        </dl>
      </div>

      {!stage.mobileVerified ? (
        <fieldset className="space-y-2 text-sm"><legend className="font-medium">Communication mobile</legend>
          {!stage.otpSent ? (
            <>
              <p className="text-muted-foreground">If it is the mobile linked to their Aadhaar{stage.hint ? <> (ending {stage.hint})</> : null}, no OTP is needed.</p>
              <input name="hpid_mobile" value={mobile} onChange={(e) => setMobile(e.target.value.replace(/\D/g, ""))} inputMode="tel" maxLength={10} className={input} />
              <button type="button" className={primary} disabled={busy || !/^[6-9]\d{9}$/.test(mobile)}
                onClick={() => void run(async () => {
                  const result = await verifyHpidMobile(stage.session, mobile);
                  update({ mobileVerified: result.mobile_verified, otpSent: result.otp_sent });
                }, "HPR did not check this mobile.")}>Verify mobile</button>
            </>
          ) : (
            <>
              <p>OTP sent to {mobile}.</p>
              <input name="hpid_mobile_otp" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className={input} />
              <button type="button" className={primary} disabled={busy || otp.length !== 6}
                onClick={() => void run(async () => {
                  await confirmHpidMobile(stage.session, otp);
                  update({ mobileVerified: true });
                }, "HPR did not accept this OTP.")}>Verify OTP</button>
            </>
          )}
        </fieldset>
      ) : <p className="text-sm">Communication mobile verified.</p>}

      {stage.mobileVerified ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label className="block space-y-1 text-sm md:col-span-2"><span className="text-muted-foreground">HPR ID (before @hpr.abdm)</span>
            <input name="hpid_id" value={form.hpr_id} onChange={(e) => set("hpr_id", e.target.value.trim().toLowerCase())} maxLength={48} className={input} />
            {stage.suggestions.length ? (
              <span className="flex flex-wrap gap-2">{stage.suggestions.map((suggestion) => (
                <button key={suggestion} type="button" className="underline" onClick={() => set("hpr_id", suggestion)}>{suggestion}</button>
              ))}</span>
            ) : null}
          </label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Email</span>
            <input name="hpid_email" value={form.email} onChange={(e) => set("email", e.target.value.trim())} inputMode="email" className={input} /></label>
          <span />
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">HPR password</span>
            <input name="hpid_password" type="password" value={form.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" className={input} /></label>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Confirm password</span>
            <input name="hpid_confirm" type="password" value={form.confirm} onChange={(e) => set("confirm", e.target.value)} autoComplete="new-password" className={input} /></label>
          <p className="text-xs text-muted-foreground md:col-span-2">8 or more characters, with upper and lower case letters and a special character, not containing their first or last name.
            {form.password && namePart ? <span role="alert" className="text-danger"> The password contains their name.</span> : null}
            {form.confirm && form.password !== form.confirm ? <span role="alert" className="text-danger"> The passwords differ.</span> : null}</p>
          <Pick name="hpid_category" label="Category" value={form.category} onChange={(v) => set("category", v)}
            list={{ rows: categories, error: categories && !categories.length ? "HPR did not return its categories." : null }} />
          <Pick name="hpid_subcategory" label="Subcategory" value={form.subcategory} onChange={(v) => set("subcategory", v)}
            list={{ rows: form.category ? subcategories : null, error: null }} />
          <Pick name="hpid_state" label="State (HPR's list)" value={form.state} list={states} onChange={(v) => set("state", v)} />
          <Pick name="hpid_district" label="District" value={form.district} list={form.state ? districts : { rows: null, error: null }} onChange={(v) => set("district", v)} />
          <div className="md:col-span-2">
            <button type="button" className={primary} disabled={busy || !ready}
              onClick={() => void run(async () => {
                const created = await createHpid({
                  session_id: stage.session, hpr_id: form.hpr_id, email: form.email, password: form.password,
                  category_code: Number(form.category), subcategory_code: Number(form.subcategory),
                  state_code: form.state, district_code: form.district,
                });
                finish(created.hpr_id, created.hpr_id_number);
              }, "HPR did not create the HPID.")}>{busy ? "Creating…" : "Create HPID"}</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
