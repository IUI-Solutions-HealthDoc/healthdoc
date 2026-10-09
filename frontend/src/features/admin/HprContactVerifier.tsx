"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";

import {
  sendHprEmailOtp,
  sendHprMobileOtp,
  verifyHprEmailOtp,
  verifyHprMobileOtp,
  type HprContact,
} from "./api/hpr";

const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const button = "rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50";
const MOBILE = /^[6-9]\d{9}$/;
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

function said(reason: unknown, fallback: string): string {
  if (!(reason instanceof ApiError)) return fallback;
  // HealthDoc words these itself and passes HPR's own reason on ("Invalid OTP").
  const payload = reason.payload as { message?: unknown; messages?: unknown } | undefined;
  if (typeof payload?.message === "string" && payload.message) return payload.message;
  if (Array.isArray(payload?.messages) && payload.messages.length) return payload.messages.join("; ");
  return reason.message || fallback;
}

/**
 * The professional's official mobile or email, verified by OTP under their HPR
 * login before registration: NHA's m4-verification journey. HPR refused every
 * registration without it (live 6 Oct 2026). The OTP goes to the professional,
 * who reads it out; registration sends only the verified value.
 */
export function HprContactVerifier({ kind, contact, onChange }: {
  kind: "mobile" | "email";
  contact: HprContact | null;
  onChange: (contact: HprContact) => void;
}) {
  const [value, setValue] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mobile = kind === "mobile";
  const verified = mobile ? contact?.mobile_verified : contact?.email_verified;
  const label = mobile ? "Official mobile" : "Official email";

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try { await action(); } catch (reason) { setError(said(reason, fallback)); } finally { setBusy(false); }
  }

  if (verified) {
    return (
      <p role="status" className="text-sm text-success">
        {label} verified{mobile ? ` (ending ${contact?.mobile_hint ?? ""})` : `: ${contact?.email ?? ""}`}.{" "}
        <button type="button" className="underline" onClick={() => onChange({ ...contact!, ...(mobile ? { mobile_verified: false } : { email_verified: false }) })}>
          Change
        </button>
      </p>
    );
  }
  const valid = mobile ? MOBILE.test(value) : EMAIL.test(value);
  return (
    <div className="space-y-2 text-sm" aria-label={`Verify ${label.toLowerCase()}`}>
      <label className="block space-y-1">
        <span className="text-muted-foreground">{label} (required by HPR, verified by OTP)</span>
        <input aria-label={label} className={input} value={value} inputMode={mobile ? "tel" : "email"} maxLength={mobile ? 10 : 120}
          onChange={(e) => { setValue(mobile ? e.target.value.replace(/\D/g, "") : e.target.value.trim()); setSent(false); }} />
      </label>
      <button type="button" className={button} disabled={busy || !valid}
        onClick={() => void run(async () => {
          if (mobile) await sendHprMobileOtp(value); else await sendHprEmailOtp(value);
          setSent(true);
          setOtp("");
        }, `HPR did not send the ${mobile ? "mobile" : "email"} OTP.`)}>{sent ? "Send again" : "Send OTP"}</button>
      {sent ? (
        <div className="flex gap-2">
          <input aria-label={`${label} OTP`} className={input} value={otp} inputMode="numeric" maxLength={6} placeholder="6-digit OTP"
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
          <button type="button" className={button} disabled={busy || otp.length !== 6}
            onClick={() => void run(async () => {
              onChange(mobile ? await verifyHprMobileOtp(otp) : await verifyHprEmailOtp(otp));
            }, "HPR did not verify the OTP.")}>Verify</button>
        </div>
      ) : null}
      {error ? <p role="alert" className="text-danger">{error}</p> : null}
    </div>
  );
}
