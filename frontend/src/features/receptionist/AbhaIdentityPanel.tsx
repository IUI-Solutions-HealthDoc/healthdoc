"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import {
  downloadNhaAbhaCard,
  requestAbhaEnrolmentOtp,
  requestAbhaLoginOtp,
  requestEnrolmentMobileOtp,
  resendAbhaOtp,
  submitEnrolmentAbhaAddress,
  verifyAbhaEnrolmentOtp,
  selectAbhaLoginAccount,
  verifyAbhaLoginOtp,
  verifyEnrolmentMobileOtp,
} from "./api";
import { digitsOnly, isValidAbhaInput, normaliseIndianMobileInput } from "./patientValidation";
import type { AbhaIdentityLinked, AbhaLoginIdentifier } from "./types";

/** Official M1 collection grant. Hindi legal text is not shipped until NHA-approved copy exists. */
const ENROLMENT_CONSENT = {
  granted: true,
  code: "abha-enrollment",
  version: "1.4",
  language: "en" as const,
};
const ENROLMENT_CONSENT_TEXT =
  "I confirm the patient agrees to share Aadhaar demographic information with the National Health Authority for the sole purpose of creating an ABHA. Consent code abha-enrollment, version 1.4.";

type Flow = "existing" | "new";
/** How an existing ABHA is proven: OTP to its linked mobile, or through Aadhaar. */
type Method = "abha-number" | "aadhaar" | "abha-address" | "mobile";

/** Mirrors the server cooldown; the server is authoritative and answers 429
 *  with retry_after_seconds if the desk is early. */
const RESEND_COOLDOWN_SECONDS = 30;

interface Props {
  patient: { id: string; full_name: string; abha_number?: string | null };
}

function refusalCode(reason: unknown): string | null {
  if (!(reason instanceof ApiError)) return null;
  const payload = (reason as { payload?: unknown }).payload;
  return payload && typeof payload === "object" && typeof (payload as { code?: unknown }).code === "string"
    ? (payload as { code: string }).code
    : null;
}

export function AbhaIdentityPanel({ patient }: Props) {
  // Keep the boundary here, not only at one call site: every consumer must
  // discard the previous patient's OTP, success and identifier before paint.
  return <PatientAbhaIdentity key={patient.id} patient={patient} />;
}

function PatientAbhaIdentity({ patient }: Props) {
  const { t } = useLocale();
  const [flow, setFlow] = useState<Flow>("existing");
  const [method, setMethod] = useState<Method>("abha-number");
  const [identifier, setIdentifier] = useState(patient.abha_number ?? "");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [maskedMobile, setMaskedMobile] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [mobile, setMobile] = useState("");
  const [linked, setLinked] = useState<AbhaIdentityLinked | null>(null);
  const [consentGranted, setConsentGranted] = useState(false);
  const [enrolPhase, setEnrolPhase] = useState<"aadhaar" | "mobile" | "address">("aadhaar");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedAddress, setSelectedAddress] = useState("");
  const communicationMobile = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendsRemaining, setResendsRemaining] = useState<number | null>(null);
  const [resendAvailableAt, setResendAvailableAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const lifecycle = useRef({ active: false, generation: 0, pending: false });
  // The identifier the OTP was requested for, kept in memory only so a resend
  // can re-supply it (the server never stores it). Cleared with the session and
  // never rendered after the request leaves the screen.
  const requestedIdentifier = useRef<AbhaLoginIdentifier | null>(null);

  useEffect(() => {
    const current = lifecycle.current;
    current.active = true;
    return () => {
      current.active = false;
      current.generation += 1;
      current.pending = false;
      requestedIdentifier.current = null;
    };
  }, []);

  useEffect(() => {
    if (resendAvailableAt === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [resendAvailableAt]);

  function beginRequest(): number | null {
    if (!lifecycle.current.active || lifecycle.current.pending) return null;
    lifecycle.current.pending = true;
    return ++lifecycle.current.generation;
  }

  function isCurrent(generation: number): boolean {
    return lifecycle.current.active && lifecycle.current.generation === generation;
  }

  function resetSession() {
    lifecycle.current.generation += 1;
    lifecycle.current.pending = false;
    requestedIdentifier.current = null;
    setBusy(false);
    setSessionId(null);
    setMaskedMobile(null);
    setOtp("");
    setMobile("");
    setLinked(null);
    setError(null);
    setResendsRemaining(null);
    setResendAvailableAt(null);
    setEnrolPhase("aadhaar");
    setSuggestions([]);
    setSelectedAddress("");
    setConsentGranted(false);
    setAccounts([]);
    setSelectedAccount("");
    communicationMobile.current = null;
  }

  const [accounts, setAccounts] = useState<{ abha_number: string; name?: string | null }[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");
  const usesAadhaar = flow === "new" || method === "aadhaar";
  const usesMobile = flow === "existing" && method === "mobile";
  const usesAddress = flow === "existing" && method === "abha-address";
  const digits = digitsOnly(identifier);
  const identifierValid = usesAadhaar
    ? digits.length === 12
    : usesMobile
      ? digits.length === 10
      : usesAddress
        ? identifier.includes("@") && !identifier.includes(" ")
        : isValidAbhaInput(identifier);
  const otpValid = /^\d{4,8}$/.test(otp);
  const mobileNormalised = mobile.trim() ? normaliseIndianMobileInput(mobile) : null;
  const mobileValid = !mobile.trim() || mobileNormalised !== null;
  const resendWaitSeconds = resendAvailableAt === null ? 0 : Math.max(0, Math.ceil((resendAvailableAt - now) / 1000));
  const canResend = sessionId !== null && (resendsRemaining ?? 0) > 0 && resendWaitSeconds === 0 && !busy;

  function changeFlow(next: Flow) {
    resetSession();
    setFlow(next);
    setMethod("abha-number");
    setIdentifier(next === "existing" ? (patient.abha_number ?? "") : "");
  }

  function changeMethod(next: Method) {
    resetSession();
    setMethod(next);
    setIdentifier(next === "abha-number" ? (patient.abha_number ?? "") : "");
  }

  function applyRequested(result: { session_id: string; masked_mobile: string | null; resends_remaining?: number }) {
    setSessionId(result.session_id);
    setMaskedMobile(result.masked_mobile);
    setOtp("");
    setResendsRemaining(result.resends_remaining ?? 0);
    setResendAvailableAt(Date.now() + RESEND_COOLDOWN_SECONDS * 1000);
    setNow(Date.now());
  }

  async function requestOtp() {
    if (flow === "new" && !consentGranted) {
      setError("Confirm the patient's enrolment consent before creating an ABHA.");
      return;
    }
    if (!identifierValid) {
      setError(usesAadhaar ? "Enter a valid 12-digit Aadhaar number." : usesMobile ? "Enter a 10-digit communication mobile." : usesAddress ? "Enter the ABHA address." : "Enter a valid 14-digit ABHA number.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    const loginIdentifier: AbhaLoginIdentifier = usesAadhaar
      ? { aadhaar: digits }
      : usesMobile
        ? { mobile: digits }
        : usesAddress
          ? { abha_address: identifier.trim() }
          : { abha_number: identifier };
    try {
      const result = flow === "existing"
        ? await requestAbhaLoginOtp(patient.id, loginIdentifier, newIdempotencyKey())
        : await requestAbhaEnrolmentOtp(patient.id, identifier, ENROLMENT_CONSENT, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      requestedIdentifier.current = loginIdentifier;
      applyRequested(result);
      // An Aadhaar number does not stay on screen while the OTP is entered.
      if (usesAadhaar) setIdentifier("");
    } catch (reason) {
      if (isCurrent(generation)) setError(reason instanceof ApiError ? reason.message : "ABDM could not send the OTP. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function resendOtp() {
    const current = requestedIdentifier.current;
    if (!sessionId || !current || !canResend) return;
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await resendAbhaOtp(flow, patient.id, sessionId, current, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      // The previous session is spent server-side; only the new one is valid.
      applyRequested(result);
    } catch (reason) {
      if (!isCurrent(generation)) return;
      const code = refusalCode(reason);
      if (code === "otp_resend_too_soon") {
        const payload = (reason as { payload?: { retry_after_seconds?: unknown } }).payload;
        const wait = typeof payload?.retry_after_seconds === "number" ? payload.retry_after_seconds : RESEND_COOLDOWN_SECONDS;
        setResendAvailableAt(Date.now() + wait * 1000);
        setNow(Date.now());
      } else if (code === "otp_resend_exhausted") {
        setResendsRemaining(0);
      }
      setError(reason instanceof ApiError ? reason.message : "ABDM could not resend the OTP. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function verifyOtp() {
    if (!sessionId || !otpValid || !mobileValid) {
      setError("Enter the OTP sent to the patient before continuing.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = flow === "existing"
        ? await verifyAbhaLoginOtp(sessionId, otp, newIdempotencyKey())
        : await verifyAbhaEnrolmentOtp(sessionId, otp, mobileNormalised, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      if (!result.linked || result.linked_patient_id !== patient.id) {
        setError("ABDM did not confirm identity binding for this patient. Restart verification.");
        return;
      }
      if (flow === "existing" && result.next_step === "account_select" && result.accounts && result.accounts.length > 1) {
        setAccounts(result.accounts);
        setSelectedAccount("");
        setSessionId(result.session_id ?? sessionId);
        setOtp("");
        return;
      }
      if (flow === "new" && result.next_step === "mobile_verify" && result.session_id) {
        setSessionId(result.session_id);
        setEnrolPhase("mobile");
        setOtp("");
        setLinked(null);
        return;
      }
      requestedIdentifier.current = null;
      setLinked(result);
      setOtp("");
      setMobile("");
      setSessionId(null);
      setResendsRemaining(null);
      setResendAvailableAt(null);
    } catch (reason) {
      if (!isCurrent(generation)) return;
      // A refused OTP (wrong, expired, over the attempt limit) keeps the
      // session: the desk retypes it or asks for a fresh one. Only clear the
      // typed code so the retry starts from an empty field.
      if (refusalCode(reason) === "otp_rejected") setOtp("");
      setError(reason instanceof ApiError ? reason.message : "ABDM could not verify the OTP. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function chooseAccount() {
    if (!sessionId || !selectedAccount) {
      setError("Choose the ABHA account the patient confirmed.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await selectAbhaLoginAccount(patient.id, sessionId, selectedAccount, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      if (!result.linked || result.linked_patient_id !== patient.id) {
        setError("ABDM did not confirm identity binding for this patient. Restart verification.");
        return;
      }
      setLinked(result);
      setAccounts([]);
      setSessionId(null);
    } catch (reason) {
      if (isCurrent(generation)) setError(reason instanceof ApiError ? reason.message : "ABDM could not confirm that account.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function sendCommunicationOtp() {
    if (!sessionId || mobileNormalised === null) {
      setError("Enter the communication mobile number to verify.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await requestEnrolmentMobileOtp(patient.id, sessionId, mobile, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      communicationMobile.current = mobile;
      applyRequested(result);
    } catch (reason) {
      if (isCurrent(generation)) setError(reason instanceof ApiError ? reason.message : "ABDM could not send the mobile OTP. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function verifyCommunicationOtp() {
    if (!sessionId || !otpValid) {
      setError("Enter the OTP sent to the communication mobile.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await verifyEnrolmentMobileOtp(sessionId, otp, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      const options = result.suggested_addresses ?? [];
      setSuggestions(options);
      setSelectedAddress(options.length === 1 ? options[0] : "");
      setEnrolPhase("address");
      setOtp("");
      setSessionId(result.session_id ?? sessionId);
    } catch (reason) {
      if (!isCurrent(generation)) return;
      if (refusalCode(reason) === "otp_rejected") setOtp("");
      setError(reason instanceof ApiError ? reason.message : "ABDM could not verify the mobile OTP. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function chooseAddress() {
    if (!sessionId || !selectedAddress) {
      setError("Choose an ABHA address before continuing.");
      return;
    }
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitEnrolmentAbhaAddress(patient.id, sessionId, selectedAddress, newIdempotencyKey());
      if (!isCurrent(generation)) return;
      setLinked(result);
      setSessionId(null);
    } catch (reason) {
      if (isCurrent(generation)) setError(reason instanceof ApiError ? reason.message : "ABDM could not save this ABHA address. Try again.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  async function downloadCard() {
    const generation = beginRequest();
    if (generation === null) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await downloadNhaAbhaCard(patient.id);
      if (!isCurrent(generation)) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "nha-abha-card";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      if (isCurrent(generation)) setError(reason instanceof ApiError ? reason.message : "The NHA ABHA card could not be downloaded.");
    } finally {
      if (isCurrent(generation)) {
        lifecycle.current.pending = false;
        setBusy(false);
      }
    }
  }

  if (linked) {
    return (
      <section className="surface-card space-y-2 border border-success/30 bg-success-muted p-5" aria-live="polite">
        <p className="font-medium">ABHA verified and linked</p>
        <p className="font-mono text-lg">{linked.abha_number}</p>
        {linked.abha_address ? <p className="text-sm text-muted-foreground">{linked.abha_address}</p> : null}
        <p className="text-sm text-muted-foreground">The hospital UHID card is printed from registration. The control below fetches the National Health Authority ABHA card.</p>
        {linked.has_nha_card ? (
          <button type="button" disabled={busy} onClick={() => void downloadCard()} className="rounded-md border border-border px-3 py-2 text-sm">Download NHA ABHA card</button>
        ) : (
          <p className="text-sm text-muted-foreground">NHA ABHA card is unavailable until a profile credential is stored.</p>
        )}
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="surface-card space-y-4 p-5">
      <div>
        <h3 className="font-medium">{t("receptionist.abha.title")}</h3>
        <p className="text-sm text-muted-foreground">
          {t("receptionist.abha.verifyLinkIntro", { name: patient.full_name })}
        </p>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="ABHA identity flow">
        <button type="button" onClick={() => changeFlow("existing")} aria-pressed={flow === "existing"} className={`rounded-md border px-3 py-2 text-sm ${flow === "existing" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.useExisting")}</button>
        <button type="button" onClick={() => changeFlow("new")} aria-pressed={flow === "new"} className={`rounded-md border px-3 py-2 text-sm ${flow === "new" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.create")}</button>
      </div>

      {flow === "existing" && !sessionId ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Verification method">
          <button type="button" onClick={() => changeMethod("abha-number")} aria-pressed={method === "abha-number"} className={`rounded-md border px-3 py-1.5 text-xs ${method === "abha-number" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.methodAbhaMobile")}</button>
          <button type="button" onClick={() => changeMethod("aadhaar")} aria-pressed={method === "aadhaar"} className={`rounded-md border px-3 py-1.5 text-xs ${method === "aadhaar" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.methodAadhaar")}</button>
          <button type="button" onClick={() => changeMethod("abha-address")} aria-pressed={method === "abha-address"} className={`rounded-md border px-3 py-1.5 text-xs ${method === "abha-address" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.methodAddress")}</button>
          <button type="button" onClick={() => changeMethod("mobile")} aria-pressed={method === "mobile"} className={`rounded-md border px-3 py-1.5 text-xs ${method === "mobile" ? "border-primary bg-primary/10" : "border-border"}`}>{t("receptionist.abha.methodMobile")}</button>
        </div>
      ) : null}

      {accounts.length > 0 ? (
        <fieldset className="space-y-3">
          <legend className="text-sm text-muted-foreground">ABDM returned more than one account. Choose the one that belongs to this patient.</legend>
          {accounts.map((account) => (
            <label key={account.abha_number} className="flex items-center gap-2 text-sm">
              <input type="radio" name="abha-account" value={account.abha_number} checked={selectedAccount === account.abha_number} onChange={() => setSelectedAccount(account.abha_number)} />
              <span>{account.abha_number}{account.name ? ` · ${account.name}` : ""}</span>
            </label>
          ))}
          <button type="button" disabled={busy || !selectedAccount} onClick={() => void chooseAccount()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{t("receptionist.abha.linkSelectedAccount")}</button>
        </fieldset>
      ) : !sessionId ? (
        <div className="space-y-3">
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">
              {usesAadhaar
                ? t("receptionist.abha.fieldAadhaar")
                : usesMobile
                  ? t("receptionist.abha.fieldMobile")
                  : usesAddress
                    ? t("receptionist.abha.fieldAddress")
                    : t("receptionist.abha.fieldAbhaNumber")}
            </span>
            <input
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              inputMode="numeric"
              autoComplete="off"
              maxLength={usesAadhaar ? 12 : usesMobile ? 10 : 50}
              aria-invalid={Boolean(identifier) && !identifierValid}
              className={`w-full rounded-md border px-3 py-2 ${identifier && !identifierValid ? "border-danger" : "border-border"}`}
            />
          </label>
          {flow === "new" ? (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={consentGranted} onChange={(event) => setConsentGranted(event.target.checked)} />
              <span>{ENROLMENT_CONSENT_TEXT}</span>
            </label>
          ) : null}
          <button type="button" disabled={busy || !identifierValid || (flow === "new" && !consentGranted)} onClick={() => void requestOtp()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? t("receptionist.abha.requestingOtp") : t("receptionist.abha.sendOtp")}</button>
        </div>
      ) : enrolPhase === "mobile" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">Verify the communication mobile in this same enrolment. This is separate from a mobile number typed on the Aadhaar OTP.</p>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("receptionist.abha.fieldMobile")}</span>
            <input value={mobile} onChange={(event) => setMobile(event.target.value)} inputMode="tel" autoComplete="tel" aria-invalid={!mobileValid} className={`w-full rounded-md border px-3 py-2 ${mobileValid ? "border-border" : "border-danger"}`} />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("receptionist.abha.fieldMobileOtp")}</span>
            <input value={otp} onChange={(event) => setOtp(digitsOnly(event.target.value))} inputMode="numeric" autoComplete="one-time-code" maxLength={8} className="w-full rounded-md border border-border px-3 py-2" />
          </label>
          <div className="flex gap-3">
            <button type="button" disabled={busy || mobileNormalised === null} onClick={() => void sendCommunicationOtp()} className="rounded-md border border-border px-3 py-2 text-sm">{t("receptionist.abha.sendMobileOtp")}</button>
            <button type="button" disabled={busy || !otpValid} onClick={() => void verifyCommunicationOtp()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{t("receptionist.abha.verifyMobile")}</button>
          </div>
        </div>
      ) : enrolPhase === "address" ? (
        <fieldset className="space-y-3">
          <legend className="text-sm text-muted-foreground">Choose an ABHA address</legend>
          {suggestions.length === 0 ? <p className="text-sm">ABDM returned no address suggestions. Start again if this continues.</p> : null}
          {suggestions.map((address) => (
            <label key={address} className="flex items-center gap-2 text-sm">
              <input type="radio" name="abha-address" value={address} checked={selectedAddress === address} onChange={() => setSelectedAddress(address)} />
              <span>{address}</span>
            </label>
          ))}
          <button type="button" disabled={busy || !selectedAddress} onClick={() => void chooseAddress()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{t("receptionist.abha.saveAbhaAddress")}</button>
        </fieldset>
      ) : (
        <div className="space-y-3">
          {maskedMobile ? <p className="text-sm text-muted-foreground">ABDM response: {maskedMobile}</p> : null}
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("receptionist.abha.fieldOtp")}</span>
            <input value={otp} onChange={(event) => setOtp(digitsOnly(event.target.value))} inputMode="numeric" autoComplete="one-time-code" maxLength={8} className="w-full rounded-md border border-border px-3 py-2" />
          </label>
          <p className="text-xs text-muted-foreground">
            {(resendsRemaining ?? 0) > 0 ? (
              <button type="button" disabled={!canResend} onClick={() => void resendOtp()} className="underline disabled:no-underline disabled:opacity-60">
                {resendWaitSeconds > 0 ? `Resend OTP in ${resendWaitSeconds}s` : `Resend OTP (${resendsRemaining} left)`}
              </button>
            ) : (
              <span>No more OTP resends for this attempt. Use “Start again” to begin a new verification.</span>
            )}
          </p>
          {flow === "new" ? (
            <label className="block space-y-1 text-sm">
              <span className="text-muted-foreground">Mobile override (only if ABDM asks for it)</span>
              <input value={mobile} onChange={(event) => setMobile(event.target.value)} inputMode="tel" autoComplete="tel" aria-invalid={!mobileValid} className={`w-full rounded-md border px-3 py-2 ${mobileValid ? "border-border" : "border-danger"}`} />
            </label>
          ) : null}
          <div className="flex gap-3">
            <button type="button" disabled={busy || !otpValid || !mobileValid} onClick={() => void verifyOtp()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? t("receptionist.abha.verifying") : t("receptionist.abha.verifyAndLink")}</button>
            <button type="button" disabled={busy} onClick={() => changeFlow(flow)} className="text-sm underline">{t("receptionist.abha.startAgain")}</button>
          </div>
        </div>
      )}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}
