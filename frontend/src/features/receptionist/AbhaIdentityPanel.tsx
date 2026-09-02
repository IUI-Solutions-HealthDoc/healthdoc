"use client";

import { useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";

import {
  requestAbhaEnrolmentOtp,
  requestAbhaLoginOtp,
  verifyAbhaEnrolmentOtp,
  verifyAbhaLoginOtp,
} from "./api";
import { digitsOnly, isValidAbhaInput, normaliseIndianMobileInput } from "./patientValidation";
import type { AbhaIdentityLinked } from "./types";

type Flow = "existing" | "new";

interface Props {
  patient: { id: string; full_name: string; abha_number?: string | null };
}

export function AbhaIdentityPanel({ patient }: Props) {
  const [flow, setFlow] = useState<Flow>(patient.abha_number ? "existing" : "existing");
  const [identifier, setIdentifier] = useState(patient.abha_number ?? "");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [maskedMobile, setMaskedMobile] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [mobile, setMobile] = useState("");
  const [linked, setLinked] = useState<AbhaIdentityLinked | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const digits = digitsOnly(identifier);
  const identifierValid = flow === "existing" ? isValidAbhaInput(identifier) : digits.length === 12;
  const otpValid = /^\d{4,8}$/.test(otp);
  const mobileNormalised = mobile.trim() ? normaliseIndianMobileInput(mobile) : null;
  const mobileValid = !mobile.trim() || mobileNormalised !== null;

  function changeFlow(next: Flow) {
    setFlow(next);
    setIdentifier(next === "existing" ? (patient.abha_number ?? "") : "");
    setSessionId(null);
    setMaskedMobile(null);
    setOtp("");
    setMobile("");
    setError(null);
  }

  async function requestOtp() {
    if (!identifierValid) {
      setError(flow === "existing" ? "Enter a valid 14-digit ABHA number." : "Enter a valid 12-digit Aadhaar number.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = flow === "existing"
        ? await requestAbhaLoginOtp(patient.id, identifier, newIdempotencyKey())
        : await requestAbhaEnrolmentOtp(patient.id, identifier, newIdempotencyKey());
      setSessionId(result.session_id);
      setMaskedMobile(result.masked_mobile);
      if (flow === "new") setIdentifier("");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ABDM could not send the OTP. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp() {
    if (!sessionId || !otpValid || !mobileValid) {
      setError("Enter the OTP sent to the patient before continuing.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = flow === "existing"
        ? await verifyAbhaLoginOtp(sessionId, otp, newIdempotencyKey())
        : await verifyAbhaEnrolmentOtp(sessionId, otp, mobileNormalised, newIdempotencyKey());
      setLinked(result);
      setOtp("");
      setMobile("");
      setSessionId(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ABDM could not verify the OTP. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (linked) {
    return (
      <section className="surface-card space-y-2 border border-success/30 bg-success-muted p-5" aria-live="polite">
        <p className="font-medium">ABHA verified and linked</p>
        <p className="font-mono text-lg">{linked.abha_number}</p>
        {linked.abha_address ? <p className="text-sm text-muted-foreground">{linked.abha_address}</p> : null}
      </section>
    );
  }

  return (
    <section className="surface-card space-y-4 p-5">
      <div>
        <h3 className="font-medium">ABHA identity</h3>
        <p className="text-sm text-muted-foreground">Verify and link the identity for {patient.full_name}. The linking credential stays encrypted on the server.</p>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="ABHA identity flow">
        <button type="button" onClick={() => changeFlow("existing")} aria-pressed={flow === "existing"} className={`rounded-md border px-3 py-2 text-sm ${flow === "existing" ? "border-primary bg-primary/10" : "border-border"}`}>Use existing ABHA</button>
        <button type="button" onClick={() => changeFlow("new")} aria-pressed={flow === "new"} className={`rounded-md border px-3 py-2 text-sm ${flow === "new" ? "border-primary bg-primary/10" : "border-border"}`}>Create ABHA</button>
      </div>

      {!sessionId ? (
        <div className="space-y-3">
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{flow === "existing" ? "ABHA number" : "Aadhaar number"}</span>
            <input
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              inputMode="numeric"
              autoComplete="off"
              maxLength={flow === "existing" ? 20 : 12}
              aria-invalid={Boolean(identifier) && !identifierValid}
              className={`w-full rounded-md border px-3 py-2 ${identifier && !identifierValid ? "border-danger" : "border-border"}`}
            />
          </label>
          <button type="button" disabled={busy || !identifierValid} onClick={() => void requestOtp()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? "Requesting…" : "Send OTP"}</button>
        </div>
      ) : (
        <div className="space-y-3">
          {maskedMobile ? <p className="text-sm text-muted-foreground">ABDM response: {maskedMobile}</p> : null}
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">OTP</span>
            <input value={otp} onChange={(event) => setOtp(digitsOnly(event.target.value))} inputMode="numeric" autoComplete="one-time-code" maxLength={8} className="w-full rounded-md border border-border px-3 py-2" />
          </label>
          {flow === "new" ? (
            <label className="block space-y-1 text-sm">
              <span className="text-muted-foreground">Mobile override (only if ABDM asks for it)</span>
              <input value={mobile} onChange={(event) => setMobile(event.target.value)} inputMode="tel" autoComplete="tel" aria-invalid={!mobileValid} className={`w-full rounded-md border px-3 py-2 ${mobileValid ? "border-border" : "border-danger"}`} />
            </label>
          ) : null}
          <div className="flex gap-3">
            <button type="button" disabled={busy || !otpValid || !mobileValid} onClick={() => void verifyOtp()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? "Verifying…" : "Verify and link"}</button>
            <button type="button" disabled={busy} onClick={() => { setSessionId(null); setOtp(""); setError(null); }} className="text-sm underline">Start again</button>
          </div>
        </div>
      )}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}
