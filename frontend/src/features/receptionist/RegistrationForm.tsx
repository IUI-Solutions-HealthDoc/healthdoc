"use client";

import { useMemo, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";

import { registerPatient } from "./api";
import { AbhaIdentityPanel } from "./AbhaIdentityPanel";
import { StartVisit } from "./StartVisit";
import type { Patient, PatientCreate } from "./types";
import {
  digitsOnly,
  isValidAbhaInput,
  isValidPatientName,
  normaliseIndianMobileInput,
} from "./patientValidation";

const SEXES = ["male", "female", "other"] as const;

type AgeMode = "dob" | "age";

export function RegistrationForm({ onRegistered }: { onRegistered?: (p: Patient) => void }) {
  const [fullName, setFullName] = useState("");
  const [sex, setSex] = useState<PatientCreate["sex"] | "">("");
  const [ageMode, setAgeMode] = useState<AgeMode>("dob");
  const [dob, setDob] = useState("");
  const [ageYears, setAgeYears] = useState("");
  const [mobile, setMobile] = useState("");
  const [abha, setAbha] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registered, setRegistered] = useState<Patient | null>(null);

  /**
   * Generated once when the form mounts, not per submit.
   *
   * That is what makes the retry safe: a double-click, or a network drop after
   * the server has committed, replays the stored response and returns the same
   * patient with the same UHID. A key generated per submit would defeat the
   * whole mechanism and hand the second click a second chart.
   */
  const idempotencyKey = useMemo(() => newIdempotencyKey(), []);

  const ageProvided = ageMode === "dob" ? dob !== "" : ageYears !== "";
  const fullNameValid = isValidPatientName(fullName);
  const normalisedMobile = normaliseIndianMobileInput(mobile);
  const mobileValid = !mobile.trim() || normalisedMobile !== null;
  const abhaValid = !abha.trim() || isValidAbhaInput(abha);
  const ageValid =
    ageMode === "dob"
      ? Boolean(dob && dob <= new Date().toISOString().slice(0, 10))
      : Boolean(ageYears && Number.isInteger(Number(ageYears)) && Number(ageYears) >= 0 && Number(ageYears) <= 130);
  const canSubmit = fullNameValid && sex !== "" && ageProvided && ageValid && mobileValid && abhaValid && !busy;
  const inputClass = (invalid: boolean) =>
    `w-full rounded-md border px-3 py-2 ${invalid ? "border-danger" : "border-border"}`;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) {
      setError("Please correct the highlighted registration fields before submitting.");
      return;
    }

    const payload: PatientCreate = {
      full_name: fullName.trim(),
      sex,
      // Exactly one, matching the server's `_dob_or_age_required`. Sending both
      // would let a typed age silently disagree with a date of birth.
      ...(ageMode === "dob"
        ? { dob, age_years: null }
        : { dob: null, age_years: Number(ageYears) }),
      mobile: normalisedMobile,
      abha_number: abha.trim() ? digitsOnly(abha) : null,
    };

    setBusy(true);
    setError(null);
    try {
      const patient = await registerPatient(payload, idempotencyKey);
      setRegistered(patient);
      onRegistered?.(patient);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Registration failed. Do not retry from a new form — reload this page first.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (registered) {
    return (
      <div className="space-y-6">
        <div className="surface-card space-y-2 p-8 text-center">
          <p className="text-sm text-muted-foreground">Registered</p>
          <p className="font-mono text-3xl font-bold">{registered.uhid ?? registered.thid}</p>
          <p className="text-lg font-medium">{registered.full_name}</p>
          <p className="text-sm text-muted-foreground">
            {registered.sex}
            {registered.age_years !== null ? ` · ${registered.age_years}y` : ""}
          </p>
        </div>

        <AbhaIdentityPanel patient={registered} />

        {/* A UHID on its own does nothing for the patient standing at the desk.
            The visit is what starts billing; the token is what gets them seen. */}
        <StartVisit patient={registered} />

        <div className="text-center">
          <button
            type="button"
            // Full reload, deliberately: the next patient needs NEW idempotency
            // keys. Resetting in place would reuse them and the server would
            // replay this registration, visit and token.
            onClick={() => window.location.reload()}
            className="text-sm underline"
          >
            Register another patient
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="surface-card space-y-5 p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1 text-sm sm:col-span-2">
          <span className="text-muted-foreground">Full name *</span>
          <input
            required
            className={inputClass(Boolean(fullName) && !fullNameValid)}
            aria-invalid={Boolean(fullName) && !fullNameValid}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            minLength={2}
          />
          {fullName && !fullNameValid ? (
            <span className="text-xs text-danger">Enter a valid name without digits or markup characters.</span>
          ) : null}
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Sex *</span>
          <select
            required
            className={inputClass(false)}
            value={sex}
            onChange={(e) => setSex(e.target.value as PatientCreate["sex"] | "")}
          >
            <option value="">Select…</option>
            {SEXES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-1 text-sm">
          <span className="text-muted-foreground">Age *</span>
          <div className="flex gap-2">
            <select
              className="rounded-md border border-border px-2 py-2"
              value={ageMode}
              onChange={(e) => setAgeMode(e.target.value as AgeMode)}
            >
              <option value="dob">Date of birth</option>
              <option value="age">Age in years</option>
            </select>

            {/* Either, never both. Many patients at a district hospital do not
                know a date of birth, which is why the server accepts an age —
                but a recorded DOB and a recorded age that disagree are worse
                than one honest value. */}
            {ageMode === "dob" ? (
              <input
                type="date"
                className={`flex-1 rounded-md border px-3 py-2 ${dob && !ageValid ? "border-danger" : "border-border"}`}
                aria-invalid={Boolean(dob) && !ageValid}
                value={dob}
                onChange={(e) => setDob(e.target.value)}
                max={new Date().toISOString().slice(0, 10)}
                required
              />
            ) : (
              <input
                type="number"
                min={0}
                max={130}
                className={`flex-1 rounded-md border px-3 py-2 ${ageYears && !ageValid ? "border-danger" : "border-border"}`}
                aria-invalid={Boolean(ageYears) && !ageValid}
                value={ageYears}
                onChange={(e) => setAgeYears(e.target.value)}
                required
              />
            )}
          </div>
        </div>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Mobile</span>
          <input
            className={inputClass(!mobileValid)}
            aria-invalid={!mobileValid}
            value={mobile}
            onChange={(e) => setMobile(e.target.value)}
            inputMode="tel"
            maxLength={18}
            placeholder="10 digits or +91"
          />
          {!mobileValid ? (
            <span className="text-xs text-danger">Enter a valid Indian mobile number.</span>
          ) : null}
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">ABHA number</span>
          <input
            className={inputClass(!abhaValid)}
            aria-invalid={!abhaValid}
            value={abha}
            onChange={(e) => setAbha(e.target.value)}
            inputMode="numeric"
            maxLength={20}
          />
          {!abhaValid ? (
            <span className="text-xs text-danger">ABHA number must contain 14 digits.</span>
          ) : null}
        </label>
      </div>

      {/* Aadhaar is accepted by the API and not collected here. It is not needed
          to register a patient, and a field on a shared counter screen invites
          collecting it by default — which is the opposite of data minimisation
          under the DPDP Act. Add it only behind a stated purpose. */}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {busy ? "Registering…" : "Register patient"}
      </button>
    </form>
  );
}

export default RegistrationForm;
