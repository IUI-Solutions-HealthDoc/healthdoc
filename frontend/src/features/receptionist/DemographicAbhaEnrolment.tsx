"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { AbhaConsentDeclaration, declarationAccepted, defaultTicks } from "./AbhaConsentDeclaration";
import {
  enrolAbhaByDemographics,
  getAbhaEnrolmentDeclaration,
  listLgdDistricts,
  listLgdStates,
  type LgdOption,
} from "./api";
import { digitsOnly } from "./patientValidation";
import type { AbhaDeclaration, AbhaIdentityLinked } from "./types";

const ENROLMENT_CONSENT = { granted: true, code: "abha-enrollment", version: "1.4", language: "en" as const };
const GENDERS: Partial<Record<string, "M" | "F" | "O">> = { male: "M", female: "F", other: "O" };

interface Patient {
  id: string;
  full_name: string;
  sex?: string | null;
  dob?: string | null;
  mobile?: string | null;
  address_line?: string | null;
  pincode?: string | null;
}

function failure(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

/** Ten national digits from a stored E.164 mobile, else empty for the desk to fill. */
function nationalMobile(value: string | null | undefined): string {
  const digits = digitsOnly(value ?? "");
  const national = digits.length === 12 && digits.startsWith("91") ? digits.slice(2) : digits;
  return /^[6-9]\d{9}$/.test(national) ? national : "";
}

/**
 * M1 CRT_ABHA_301-309: create or fetch an ABHA from Aadhaar demographics, the
 * route mandatory for government applications. The chart prefills the form;
 * the desk corrects it against the Aadhaar card, because UIDAI matches what is
 * sent. State and district come only from the loaded LGD list.
 */
export function DemographicAbhaEnrolment({ patient, onLinked }: {
  patient: Patient;
  onLinked: (linked: AbhaIdentityLinked) => void;
}) {
  const [declaration, setDeclaration] = useState<AbhaDeclaration | null>(null);
  const [declarationError, setDeclarationError] = useState<string | null>(null);
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  const [states, setStates] = useState<LgdOption[] | null>(null);
  const [districts, setDistricts] = useState<LgdOption[] | null>(null);
  const [lgdError, setLgdError] = useState<string | null>(null);
  const [form, setForm] = useState<{
    aadhaar: string; name: string; date_of_birth: string; gender: "" | "M" | "F" | "O";
    mobile: string; address: string; pincode: string; state_code: string; district_code: string;
  }>({
    aadhaar: "",
    name: patient.full_name,
    date_of_birth: patient.dob ?? "",
    gender: GENDERS[patient.sex ?? ""] ?? "",
    mobile: nationalMobile(patient.mobile),
    address: patient.address_line ?? "",
    pincode: patient.pincode ?? "",
    state_code: "",
    district_code: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);

  useEffect(() => {
    let disposed = false;
    getAbhaEnrolmentDeclaration(patient.id).then(
      (shown) => { if (!disposed) { setDeclaration(shown); setTicks(defaultTicks(shown)); } },
      (reason: unknown) => { if (!disposed) setDeclarationError(failure(reason, "The ABHA consent could not be loaded.")); },
    );
    listLgdStates().then(
      (rows) => { if (!disposed) setStates(rows); },
      (reason: unknown) => { if (!disposed) setLgdError(failure(reason, "The LGD state list could not be loaded.")); },
    );
    return () => { disposed = true; };
  }, [patient.id]);

  useEffect(() => {
    if (!form.state_code) return;
    let disposed = false;
    listLgdDistricts(form.state_code).then(
      (rows) => { if (!disposed) setDistricts(rows); },
      (reason: unknown) => { if (!disposed) setLgdError(failure(reason, "The LGD district list could not be loaded.")); },
    );
    return () => { disposed = true; };
  }, [form.state_code]);

  function change(field: keyof typeof form, value: string) {
    key.current = null; // A changed request is a new request.
    setForm((current) => ({
      ...current,
      [field]: value,
      ...(field === "state_code" ? { district_code: "" } : {}),
    }));
    if (field === "state_code") setDistricts(null);
  }

  const aadhaarValid = /^\d{12}$/.test(digitsOnly(form.aadhaar));
  const complete = aadhaarValid && form.name.trim() !== "" && form.date_of_birth !== "" && form.gender !== ""
    && /^[6-9]\d{9}$/.test(form.mobile) && form.address.trim() !== "" && /^[1-9]\d{5}$/.test(form.pincode)
    && form.state_code !== "" && form.district_code !== "";
  const ready = complete && declarationAccepted(declaration, ticks);

  async function submit() {
    if (!ready || !declaration || form.gender === "") return;
    setBusy(true);
    setError(null);
    key.current ??= newIdempotencyKey();
    try {
      const linked = await enrolAbhaByDemographics({
        ...form,
        gender: form.gender,
        patient_id: patient.id,
        consent: { ...ENROLMENT_CONSENT, statements: ticks, declaration_sha256: declaration.sha256 },
      }, key.current);
      setForm((current) => ({ ...current, aadhaar: "" })); // never left on screen
      onLinked(linked);
    } catch (reason) {
      setError(failure(reason, "ABDM could not create the ABHA. Try again."));
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-md border border-border px-3 py-2";
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Enter the details exactly as printed on the patient&apos;s Aadhaar card. ABDM checks them with UIDAI; no OTP is sent.</p>
      <label className="block space-y-1 text-sm">
        <span className="text-muted-foreground">Aadhaar number</span>
        <input name="aadhaar" value={form.aadhaar} onChange={(e) => change("aadhaar", e.target.value)} inputMode="numeric" autoComplete="off" maxLength={14}
          aria-invalid={Boolean(form.aadhaar) && !aadhaarValid} className={input} />
        {form.aadhaar && !aadhaarValid ? <span role="alert" className="text-danger">Aadhaar number must be 12 digits.</span> : null}
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Name as on Aadhaar</span>
          <input name="name" value={form.name} onChange={(e) => change("name", e.target.value)} className={input} /></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Date of birth</span>
          <input name="date_of_birth" type="date" value={form.date_of_birth} onChange={(e) => change("date_of_birth", e.target.value)} className={input} /></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Gender</span>
          <select name="gender" value={form.gender} onChange={(e) => change("gender", e.target.value)} className={input}>
            <option value="">Choose</option><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option>
          </select></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">Mobile (10 digits)</span>
          <input name="mobile" value={form.mobile} onChange={(e) => change("mobile", digitsOnly(e.target.value))} inputMode="tel" maxLength={10} className={input} /></label>
        <label className="block space-y-1 text-sm md:col-span-2"><span className="text-muted-foreground">Address</span>
          <input name="address" value={form.address} onChange={(e) => change("address", e.target.value)} className={input} /></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">PIN code</span>
          <input name="pincode" value={form.pincode} onChange={(e) => change("pincode", digitsOnly(e.target.value))} inputMode="numeric" maxLength={6} className={input} /></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">State (LGD)</span>
          <select name="state_code" value={form.state_code} onChange={(e) => change("state_code", e.target.value)} disabled={!states} className={input}>
            <option value="">{states ? "Choose" : "Loading…"}</option>
            {(states ?? []).map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}
          </select></label>
        <label className="block space-y-1 text-sm"><span className="text-muted-foreground">District (LGD)</span>
          <select name="district_code" value={form.district_code} onChange={(e) => change("district_code", e.target.value)} disabled={!districts} className={input}>
            <option value="">{form.state_code ? (districts ? "Choose" : "Loading…") : "Choose a state first"}</option>
            {(districts ?? []).map((row) => <option key={row.code} value={row.code}>{row.name}</option>)}
          </select></label>
      </div>
      {lgdError ? <p role="alert" className="text-sm text-danger">{lgdError}</p> : null}
      <AbhaConsentDeclaration
        declaration={declaration}
        error={declarationError}
        ticks={ticks}
        onTick={(id, checked) => { key.current = null; setTicks((current) => ({ ...current, [id]: checked })); }}
      />
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      <button type="button" disabled={busy || !ready} onClick={() => void submit()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        {busy ? "Creating ABHA…" : "Create ABHA from these details"}
      </button>
    </div>
  );
}
