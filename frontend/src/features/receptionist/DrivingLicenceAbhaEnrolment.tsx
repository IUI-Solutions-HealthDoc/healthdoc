"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { AbhaConsentDeclaration, declarationAccepted, defaultTicks } from "./AbhaConsentDeclaration";
import {
  enrolByDrivingLicence,
  getAbhaEnrolmentDeclaration,
  listLgdDistricts,
  listLgdStates,
  requestLicenceEnrolmentOtp,
  resendLicenceEnrolmentOtp,
  verifyLicenceEnrolmentOtp,
  type LgdOption,
} from "./api";
import { prepareLicencePhoto } from "./licencePhoto";
import { digitsOnly } from "./patientValidation";
import type { AbhaDeclaration, ConsentLanguage, DrivingLicenceEnrolmentResult } from "./types";

const ENROLMENT_CONSENT = { granted: true, code: "abha-enrollment", version: "1.4" };
const GENDERS: Partial<Record<string, "M" | "F" | "O">> = { male: "M", female: "F", other: "O" };
/** NHA's driving-licence pattern: letters and digits with at most one "-" or space. */
const LICENCE = /^[A-Za-z0-9]+[- ]?[A-Za-z0-9]+$/;

interface Patient {
  id: string;
  full_name: string;
  sex?: string | null;
  dob?: string | null;
  mobile?: string | null;
  address_line?: string | null;
  pincode?: string | null;
}

type Step = "start" | "otp" | "details" | "done";

function failure(reason: unknown, fallback: string): string {
  return reason instanceof ApiError || reason instanceof Error ? reason.message : fallback;
}

function nationalMobile(value: string | null | undefined): string {
  const digits = digitsOnly(value ?? "");
  const national = digits.length === 12 && digits.startsWith("91") ? digits.slice(2) : digits;
  return /^[6-9]\d{9}$/.test(national) ? national : "";
}

/** The chart's name as a starting point; the desk corrects it to the licence. */
function nameParts(fullName: string): { first_name: string; middle_name: string; last_name: string } {
  const words = fullName.trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) return { first_name: words[0] ?? "", middle_name: "", last_name: "" };
  return { first_name: words[0], middle_name: words.slice(1, -1).join(" "), last_name: words[words.length - 1] };
}

/**
 * M1 CRT_ABHA_401-411: ABHA enrolment with a driving licence (NHA's "dl-flow").
 *
 * ABDM returns an enrolment number, not an ABHA: NHA issues the ABHA after a
 * participating facility verifies the licence, so the chart is not linked
 * here. The operator compares the licence and its photos with the person and
 * either approves (submits) or rejects it; a rejected licence is never sent.
 */
export function DrivingLicenceAbhaEnrolment({ patient }: { patient: Patient }) {
  const [step, setStep] = useState<Step>("start");
  const [declaration, setDeclaration] = useState<AbhaDeclaration | null>(null);
  const [declarationError, setDeclarationError] = useState<string | null>(null);
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [consentLanguage, setConsentLanguage] = useState<ConsentLanguage>("en");
  const [mobile, setMobile] = useState(nationalMobile(patient.mobile));
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [states, setStates] = useState<LgdOption[] | null>(null);
  const [districts, setDistricts] = useState<LgdOption[] | null>(null);
  const [lgdError, setLgdError] = useState<string | null>(null);
  const [form, setForm] = useState({
    licence_number: "",
    ...nameParts(patient.full_name),
    date_of_birth: patient.dob ?? "",
    gender: (GENDERS[patient.sex ?? ""] ?? "") as "" | "M" | "F" | "O",
    address: patient.address_line ?? "",
    pincode: patient.pincode ?? "",
    state_code: "",
    district_code: "",
  });
  const [photos, setPhotos] = useState<{ front: string | null; back: string | null }>({ front: null, back: null });
  const [checked, setChecked] = useState(false);
  const [result, setResult] = useState<DrivingLicenceEnrolmentResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const submitKey = useRef<string | null>(null);

  useEffect(() => {
    let disposed = false;
    getAbhaEnrolmentDeclaration(patient.id, consentLanguage, "document").then(
      (shown) => { if (!disposed) { setDeclaration(shown); setTicks(defaultTicks(shown)); } },
      (reason: unknown) => { if (!disposed) setDeclarationError(failure(reason, "The ABHA consent could not be loaded.")); },
    );
    return () => { disposed = true; };
  }, [patient.id, consentLanguage]);

  useEffect(() => {
    if (step !== "details" || states) return;
    let disposed = false;
    listLgdStates().then(
      (rows) => { if (!disposed) setStates(rows); },
      (reason: unknown) => { if (!disposed) setLgdError(failure(reason, "The LGD state list could not be loaded.")); },
    );
    return () => { disposed = true; };
  }, [step, states]);

  useEffect(() => {
    if (!form.state_code) return;
    let disposed = false;
    listLgdDistricts(form.state_code).then(
      (rows) => { if (!disposed) setDistricts(rows); },
      (reason: unknown) => { if (!disposed) setLgdError(failure(reason, "The LGD district list could not be loaded.")); },
    );
    return () => { disposed = true; };
  }, [form.state_code]);

  /** CRT_ABHA_407 reject, or any restart: nothing typed or photographed is kept. */
  function startOver(message: string | null) {
    setStep("start");
    setSessionId(null);
    setSentTo(null);
    setOtp("");
    setPhotos({ front: null, back: null });
    setChecked(false);
    setForm((current) => ({ ...current, licence_number: "" }));
    setError(null);
    setNotice(message);
    submitKey.current = null;
    if (declaration) setTicks(defaultTicks(declaration));
  }

  function change(field: keyof typeof form, value: string) {
    submitKey.current = null; // A changed request is a new request.
    setChecked(false); // The check was of what was on screen before.
    setForm((current) => ({ ...current, [field]: value, ...(field === "state_code" ? { district_code: "" } : {}) }));
    if (field === "state_code") setDistricts(null);
  }

  async function choosePhoto(side: "front" | "back", file: File | undefined) {
    submitKey.current = null;
    setChecked(false);
    setPhotos((current) => ({ ...current, [side]: null }));
    if (!file) return;
    try {
      const encoded = await prepareLicencePhoto(file);
      setPhotos((current) => ({ ...current, [side]: encoded }));
    } catch (reason) {
      setError(failure(reason, "The photo could not be read."));
    }
  }

  async function sendOtp() {
    if (!declaration || !declarationAccepted(declaration, ticks) || !/^[6-9]\d{9}$/.test(mobile)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const requested = await requestLicenceEnrolmentOtp(patient.id, mobile, {
        ...ENROLMENT_CONSENT, language: declaration.language, statements: ticks, declaration_sha256: declaration.sha256,
      }, newIdempotencyKey());
      setSessionId(requested.session_id);
      setSentTo(requested.masked_mobile ?? null);
      setStep("otp");
    } catch (reason) {
      setError(failure(reason, "ABDM could not send the OTP. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function resendOtp() {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const requested = await resendLicenceEnrolmentOtp(patient.id, sessionId, mobile, newIdempotencyKey());
      setSentTo(requested.masked_mobile ?? null);
      setNotice(`A new OTP was sent. ${requested.resends_remaining} more can be requested.`);
    } catch (reason) {
      setError(failure(reason, "ABDM could not send another OTP."));
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp() {
    if (!sessionId || !/^\d{6}$/.test(otp)) return;
    setBusy(true);
    setError(null);
    try {
      await verifyLicenceEnrolmentOtp(patient.id, sessionId, otp, newIdempotencyKey());
      setOtp("");
      setNotice(null);
      setStep("details");
    } catch (reason) {
      setError(failure(reason, "ABDM did not accept this OTP."));
    } finally {
      setBusy(false);
    }
  }

  const complete = LICENCE.test(form.licence_number.trim()) && form.first_name.trim() !== ""
    && form.date_of_birth !== "" && form.gender !== "" && form.address.trim() !== ""
    && /^[1-9]\d{5}$/.test(form.pincode) && form.state_code !== "" && form.district_code !== ""
    && photos.front !== null && photos.back !== null;

  async function submit() {
    if (!sessionId || !complete || !checked || form.gender === "" || !photos.front || !photos.back) return;
    setBusy(true);
    setError(null);
    submitKey.current ??= newIdempotencyKey();
    try {
      const enrolled = await enrolByDrivingLicence({
        ...form,
        gender: form.gender,
        licence_number: form.licence_number.trim(),
        session_id: sessionId,
        patient_id: patient.id,
        front_photo: photos.front,
        back_photo: photos.back,
        operator_verified: true,
      }, submitKey.current);
      setPhotos({ front: null, back: null });
      setResult(enrolled);
      setStep("done");
    } catch (reason) {
      setError(failure(reason, "ABDM could not take this driving licence. Check the details and try again."));
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-md border border-border px-3 py-2";
  const primary = "rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50";

  if (step === "done" && result) {
    return (
      <div className="space-y-2" role="status">
        <p className="text-sm font-medium">Enrolment number: <span className="font-mono">{result.enrolment_number}</span></p>
        {result.enrolment_state ? <p className="text-sm">State: {result.enrolment_state}</p> : null}
        {result.abha_address ? <p className="text-sm">ABHA address: {result.abha_address}</p> : null}
        <p className="text-sm text-muted-foreground">
          This is not yet an ABHA number. NHA issues the ABHA after a participating facility verifies the driving
          licence against the patient. It is not linked to this chart; once the ABHA is issued, link it here with
          &ldquo;Use existing ABHA&rdquo;.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {notice ? <p role="status" className="text-sm text-muted-foreground">{notice}</p> : null}
      {step === "start" ? (
        <>
          <p className="text-sm text-muted-foreground">For a patient without Aadhaar. ABDM sends an OTP to the mobile, then checks the driving licence.</p>
          <AbhaConsentDeclaration
            declaration={declaration}
            error={declarationError}
            ticks={ticks}
            onTick={(id, value) => setTicks((current) => ({ ...current, [id]: value }))}
            language={consentLanguage}
            onLanguage={(next) => {
              if (next === consentLanguage) return;
              setConsentLanguage(next);
              setDeclaration(null);
              setDeclarationError(null);
              setTicks({});
            }}
          />
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Mobile for communication (10 digits)</span>
            <input name="licence_mobile" value={mobile} onChange={(e) => setMobile(digitsOnly(e.target.value))} inputMode="tel" maxLength={10} className={input} />
          </label>
          <button type="button" disabled={busy || !declarationAccepted(declaration, ticks) || !/^[6-9]\d{9}$/.test(mobile)} onClick={() => void sendOtp()} className={primary}>
            {busy ? "Sending OTP…" : "Send OTP"}
          </button>
        </>
      ) : null}

      {step === "otp" ? (
        <>
          <p className="text-sm text-muted-foreground">{sentTo ?? "ABDM sent an OTP to the mobile."}</p>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">OTP</span>
            <input name="licence_otp" value={otp} onChange={(e) => setOtp(digitsOnly(e.target.value))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className={input} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || !/^\d{6}$/.test(otp)} onClick={() => void verifyOtp()} className={primary}>Verify OTP</button>
            <button type="button" disabled={busy} onClick={() => void resendOtp()} className="rounded-md border border-border px-3 py-2 text-sm">Send again</button>
          </div>
        </>
      ) : null}

      {step === "details" ? (
        <>
          <p className="text-sm text-muted-foreground">Enter the details exactly as printed on the driving licence.</p>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block space-y-1 text-sm md:col-span-2"><span className="text-muted-foreground">Driving licence number</span>
              <input name="licence_number" value={form.licence_number} onChange={(e) => change("licence_number", e.target.value)} autoComplete="off" maxLength={20}
                aria-invalid={Boolean(form.licence_number) && !LICENCE.test(form.licence_number.trim())} className={input} />
              {form.licence_number && !LICENCE.test(form.licence_number.trim()) ? <span role="alert" className="text-danger">Driving licence number is not valid</span> : null}
            </label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">First name</span>
              <input name="first_name" value={form.first_name} onChange={(e) => change("first_name", e.target.value)} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Middle name</span>
              <input name="middle_name" value={form.middle_name} onChange={(e) => change("middle_name", e.target.value)} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Last name</span>
              <input name="last_name" value={form.last_name} onChange={(e) => change("last_name", e.target.value)} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Date of birth</span>
              <input name="date_of_birth" type="date" value={form.date_of_birth} onChange={(e) => change("date_of_birth", e.target.value)} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Gender</span>
              <select name="gender" value={form.gender} onChange={(e) => change("gender", e.target.value)} className={input}>
                <option value="">Choose</option><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option>
              </select></label>
            <label className="block space-y-1 text-sm md:col-span-2"><span className="text-muted-foreground">Address</span>
              <input name="address" value={form.address} onChange={(e) => change("address", e.target.value)} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">PIN code</span>
              <input name="pincode" value={form.pincode} onChange={(e) => change("pincode", digitsOnly(e.target.value))} inputMode="numeric" maxLength={6} className={input} /></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">State</span>
              <select name="state_code" value={form.state_code} onChange={(e) => change("state_code", e.target.value)} disabled={!states} className={input}>
                <option value="">{states ? "Choose" : "Loading…"}</option>
                {(states ?? []).map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}
              </select></label>
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">District</span>
              <select name="district_code" value={form.district_code} onChange={(e) => change("district_code", e.target.value)} disabled={!districts} className={input}>
                <option value="">{form.state_code ? (districts ? "Choose" : "Loading…") : "Choose a state first"}</option>
                {(districts ?? []).map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}
              </select></label>
            {(["front", "back"] as const).map((side) => (
              <label key={side} className="block space-y-1 text-sm"><span className="text-muted-foreground">{side === "front" ? "Front of the licence" : "Back of the licence"}</span>
                <input name={`licence_${side}`} type="file" accept="image/jpeg,image/png" capture="environment" onChange={(e) => void choosePhoto(side, e.target.files?.[0])} className={input} />
                {photos[side] ? (
                  // eslint-disable-next-line @next/next/no-img-element -- a local data URI the operator checks, not an optimisable asset
                  <img src={`data:image/jpeg;base64,${photos[side]}`} alt={`${side} of the driving licence`} className="max-h-48 rounded-md border border-border" />
                ) : null}
              </label>
            ))}
          </div>
          {lgdError ? <p role="alert" className="text-sm text-danger">{lgdError}</p> : null}
          <fieldset className="space-y-2 rounded-md border border-border p-3 text-sm">
            <legend className="px-1 font-medium">Check the licence (CRT_ABHA_407)</legend>
            <label className="flex items-start gap-2">
              <input type="checkbox" name="operator_verified" checked={checked} disabled={!complete} onChange={(e) => setChecked(e.target.checked)} />
              <span>I have compared the licence, its photograph, number, name, date of birth and gender with the person at the desk, and they match.</span>
            </label>
          </fieldset>
          {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || !complete || !checked} onClick={() => void submit()} className={primary}>
              {busy ? "Sending to ABDM…" : "Approve and send for enrolment"}
            </button>
            <button type="button" disabled={busy} onClick={() => startOver("Licence rejected. Nothing was sent to ABDM.")} className="rounded-md border border-border px-3 py-2 text-sm">
              Reject licence
            </button>
          </div>
        </>
      ) : null}

      {step !== "details" && error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </div>
  );
}
