"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getPortalDashboard,
  type PortalDashboard,
} from "@/features/patientPortal/api";
import { ApiError, formatDateTime } from "@/lib/api";

type ViewState =
  | { status: "loading" }
  | { status: "unbound" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PortalDashboard };

const verificationLabels = {
  abha_otp: "ABHA OTP",
  in_person_document: "In-person document check",
};

function humanise(value: string | null): string {
  return value ? value.replaceAll("_", " ") : "—";
}

function UnboundPortal() {
  return (
    <section className="surface-card space-y-3 p-5">
      <h2 className="text-lg font-medium">Identity verification required</h2>
      <p className="text-sm text-muted-foreground">
        A portal role alone cannot prove which patient you are. HealthDoc will not ask for a
        patient ID or let this account browse facility records.
      </p>
      <p className="text-sm text-muted-foreground">
        Ask registration to activate the portal after an ABHA OTP or approved in-person identity
        check. Until then, no patient data is requested or displayed.
      </p>
    </section>
  );
}

export default function Page() {
  const [view, setView] = useState<ViewState>({ status: "loading" });
  const [historyPage, setHistoryPage] = useState(1);
  const [consentPage, setConsentPage] = useState(1);
  const HISTORY_PAGE_SIZE = 6;
  const CONSENT_PAGE_SIZE = 5;

  const load = useCallback(async () => {
    setView({ status: "loading" });
    try {
      setView({ status: "ready", data: await getPortalDashboard() });
      setHistoryPage(1);
      setConsentPage(1);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === 403 &&
        (error.payload as { code?: string } | undefined)?.code === "patient_identity_not_bound"
      ) {
        setView({ status: "unbound" });
        return;
      }
      setView({
        status: "error",
        message: error instanceof Error ? error.message : "Patient portal could not be loaded",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const consents = view.status === "ready" ? view.data.consents : [];
  const totalConsentPages = Math.max(1, Math.ceil(consents.length / CONSENT_PAGE_SIZE));
  const paginatedConsents = consents.slice((consentPage - 1) * CONSENT_PAGE_SIZE, consentPage * CONSENT_PAGE_SIZE);

  const historyItems = view.status === "ready" ? view.data.accessHistory.items : [];
  const totalHistoryPages = Math.max(1, Math.ceil(historyItems.length / HISTORY_PAGE_SIZE));
  const paginatedHistory = historyItems.slice((historyPage - 1) * HISTORY_PAGE_SIZE, historyPage * HISTORY_PAGE_SIZE);

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-primary">Patient portal</p>
          <h1 className="mt-2 text-3xl font-semibold">My health-data permissions</h1>
          <p className="mt-2 text-muted-foreground">
            Your ABHA status, consent decisions, and a record of who accessed your data.
          </p>
        </div>
        <button type="button" className="rounded-md border border-border px-4 py-2 text-sm" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {view.status === "loading" ? (
        <p role="status" className="surface-card p-5 text-sm text-muted-foreground">Loading your verified record…</p>
      ) : null}
      {view.status === "unbound" ? <UnboundPortal /> : null}
      {view.status === "error" ? (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-muted p-5 text-danger">
          <p className="font-medium">Portal unavailable</p>
          <p className="mt-1 text-sm">{view.message}</p>
        </div>
      ) : null}

      {view.status === "ready" ? (
        <>
          <section className="grid gap-4 md:grid-cols-2">
            <article className="surface-card p-5">
              <p className="text-sm text-muted-foreground">ABHA identity</p>
              <p className="mt-2 text-xl font-semibold">{view.data.abha.abha_number ?? "Not linked"}</p>
              <p className="mt-2 text-sm text-muted-foreground">
                {view.data.abha.linked_at
                  ? `Linked ${formatDateTime(view.data.abha.linked_at)}`
                  : "Registration can link ABHA only after verified OTP; this portal never accepts an unverified number."}
              </p>
            </article>
            <article className="surface-card p-5">
              <p className="text-sm text-muted-foreground">Portal identity verified by</p>
              <p className="mt-2 text-xl font-semibold">
                {verificationLabels[view.data.binding.verification_method]}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                Verified {formatDateTime(view.data.binding.verified_at)}
              </p>
            </article>
          </section>

          <section className="surface-card overflow-hidden">
            <div className="border-b border-border p-5">
              <h2 className="text-lg font-semibold">My consents</h2>
              <p className="mt-1 text-sm text-muted-foreground">Current and historical consent decisions recorded for you ({consents.length} total).</p>
            </div>
            {consents.length === 0 ? (
              <p className="p-5 text-sm text-muted-foreground">No consent records have been recorded.</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">Purpose</th><th className="p-3">Status</th><th className="p-3">Granted</th><th className="p-3">Expires</th></tr></thead>
                    <tbody>{paginatedConsents.map((consent) => (
                      <tr key={consent.id} className="border-t border-border"><td className="p-3"><span className="font-medium">{humanise(consent.purpose_code)}</span>{consent.purpose_description ? <span className="block text-xs text-muted-foreground">{consent.purpose_description}</span> : null}</td><td className="p-3 capitalize">{humanise(consent.status)}</td><td className="p-3">{formatDateTime(consent.granted_at)}</td><td className="p-3">{consent.expires_at ? formatDateTime(consent.expires_at) : "No expiry"}</td></tr>
                    ))}</tbody>
                  </table>
                </div>

                {consents.length > CONSENT_PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t border-border px-4 py-2.5 bg-muted/20 text-xs">
                    <span className="text-muted-foreground">Page {consentPage} of {totalConsentPages}</span>
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={consentPage <= 1}
                        onClick={() => setConsentPage((p) => Math.max(1, p - 1))}
                        className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                      >
                        Prev
                      </button>
                      <button
                        type="button"
                        disabled={consentPage >= totalConsentPages}
                        onClick={() => setConsentPage((p) => Math.min(totalConsentPages, p + 1))}
                        className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="surface-card overflow-hidden">
            <div className="border-b border-border p-5">
              <h2 className="text-lg font-semibold">Data access history</h2>
              <p className="mt-1 text-sm text-muted-foreground">{view.data.accessHistory.total} recorded access events, newest first.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">When</th><th className="p-3">Accessed by</th><th className="p-3">Data</th><th className="p-3">Purpose</th></tr></thead>
                <tbody>{paginatedHistory.map((entry, index) => (
                  <tr key={`${entry.accessed_at}-${index}`} className="border-t border-border"><td className="p-3">{formatDateTime(entry.accessed_at)}</td><td className="p-3">{entry.staff_name ?? "System"}<span className="block text-xs capitalize text-muted-foreground">{humanise(entry.role)}</span></td><td className="p-3 capitalize">{humanise(entry.resource_type)}{entry.emergency_access ? <span className="ml-2 rounded bg-danger-muted px-2 py-0.5 text-xs text-danger">Emergency</span> : null}</td><td className="p-3 capitalize">{humanise(entry.purpose_code)}</td></tr>
                ))}</tbody>
              </table>
            </div>

            {historyItems.length > HISTORY_PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-border px-4 py-2.5 bg-muted/20 text-xs">
                <span className="text-muted-foreground">Page {historyPage} of {totalHistoryPages}</span>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={historyPage <= 1}
                    onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
                    className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                  >
                    Prev
                  </button>
                  <button
                    type="button"
                    disabled={historyPage >= totalHistoryPages}
                    onClick={() => setHistoryPage((p) => Math.min(totalHistoryPages, p + 1))}
                    className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
