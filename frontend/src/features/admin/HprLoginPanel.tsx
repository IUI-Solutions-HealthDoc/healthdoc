"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { hprLoginState, hprLogout, hprPasswordLogin, startHprOtp, verifyHprOtp, type HprSession } from "./api/hfr";

type Method = "AADHAAR_OTP" | "MOBILE_OTP" | "PASSWORD";
const input = "w-full rounded-md border border-border px-3 py-2 text-sm";
const HPR_ID = /^(?:[a-z0-9][a-z0-9._]{2,48}@hpr\.abdm|\d{2}-\d{4}-\d{4}-\d{4})$/;

function failure(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.message : fallback;
}

/**
 * HFR registration and update carry the facility manager's HPR login. The
 * manager signs in here; the OTP or password goes to HPR through HealthDoc and
 * is not kept. HealthDoc holds the login for at most 30 minutes.
 */
export function HprLoginPanel({ onChange }: { onChange?: (session: HprSession) => void }) {
  const [session, setSession] = useState<HprSession | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [hprId, setHprId] = useState("");
  const [method, setMethod] = useState<Method>("AADHAAR_OTP");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<{ id: string; hint: string | null } | null>(null);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function settle(next: HprSession) {
    setSession(next);
    setPending(null);
    setOtp("");
    setPassword("");
    onChange?.(next);
  }

  useEffect(() => {
    let disposed = false;
    hprLoginState().then((next) => { if (!disposed) { setSession(next); onChange?.(next); } },
      (reason: unknown) => { if (!disposed) setStateError(failure(reason, "HPR login state could not be loaded.")); });
    return () => { disposed = true; };
    // onChange is a notification hook; reloading on every parent render is not wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await action(); } catch (reason) { setError(failure(reason, "HPR did not accept this login.")); } finally { setBusy(false); }
  }

  const idValid = HPR_ID.test(hprId.trim());

  if (stateError) return <p role="alert" className="text-sm text-danger">{stateError}</p>;
  if (!session) return <p role="status" className="text-sm text-muted-foreground">Checking HPR login…</p>;

  if (session.logged_in) {
    return (
      <section className="surface-card space-y-2 p-5" aria-label="HPR login">
        <p className="text-sm">Signed in to HPR as <span className="font-mono">{session.hpr_id}</span>
          {session.hpr_id_number ? <> ({session.hpr_id_number})</> : null}, until {new Date(session.expires_at * 1000).toLocaleTimeString()}.</p>
        <button type="button" disabled={busy} onClick={() => void run(async () => settle(await hprLogout()))} className="rounded-md border border-border px-3 py-1.5 text-sm">Sign out of HPR</button>
        {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="surface-card space-y-3 p-5" aria-label="HPR login">
      <h2 className="text-lg font-semibold">Facility manager&apos;s HPR login</h2>
      <p className="text-sm text-muted-foreground">Registering or updating a facility in HFR is done under the facility manager&apos;s Healthcare Professional Registry ID.</p>
      {!pending ? (
        <>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">HPR ID</span>
            <input name="hpr_id" value={hprId} onChange={(e) => setHprId(e.target.value.trim().toLowerCase())} placeholder="name@hpr.abdm" autoComplete="off" className={input} /></label>
          <div className="flex flex-wrap gap-4 text-sm" role="radiogroup" aria-label="HPR login method">
            {([["AADHAAR_OTP", "OTP on Aadhaar mobile"], ["MOBILE_OTP", "OTP on HPR mobile"], ["PASSWORD", "HPR password"]] as const).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2">
                <input type="radio" name="hpr_method" value={value} checked={method === value} onChange={() => setMethod(value)} />{label}
              </label>
            ))}
          </div>
          {method === "PASSWORD" ? (
            <label className="block space-y-1 text-sm"><span className="text-muted-foreground">HPR password</span>
              <input name="hpr_password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className={input} /></label>
          ) : null}
          <button type="button" disabled={busy || !idValid || (method === "PASSWORD" && !password)} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            onClick={() => void run(async () => {
              if (method === "PASSWORD") { settle(await hprPasswordLogin(hprId.trim(), password)); return; }
              const started = await startHprOtp(hprId.trim(), method);
              setPending({ id: started.session_id, hint: started.masked_mobile });
            })}>
            {method === "PASSWORD" ? "Sign in" : "Send OTP"}
          </button>
        </>
      ) : (
        <>
          <p className="text-sm">OTP sent{pending.hint ? <> to {pending.hint}</> : null}.</p>
          <label className="block space-y-1 text-sm"><span className="text-muted-foreground">OTP</span>
            <input name="hpr_otp" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className={input} /></label>
          <div className="flex gap-2">
            <button type="button" disabled={busy || otp.length !== 6} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={() => void run(async () => settle(await verifyHprOtp(pending.id, otp)))}>Verify</button>
            <button type="button" disabled={busy} onClick={() => { setPending(null); setOtp(""); }} className="rounded-md border border-border px-3 py-2 text-sm">Start again</button>
          </div>
        </>
      )}
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    </section>
  );
}
