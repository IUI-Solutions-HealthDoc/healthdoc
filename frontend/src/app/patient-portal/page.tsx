"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getPortalDashboard,
  type PortalDashboard,
} from "@/features/patientPortal/api";
import { ReleasedDocumentsTab } from "@/features/patientPortal/components/ReleasedDocumentsTab";
import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

type ViewState =
  | { status: "loading" }
  | { status: "unbound" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PortalDashboard };

function humanise(value: string | null): string {
  return value ? value.replaceAll("_", " ") : "—";
}

function UnboundPortal() {
  const { t } = useLocale();
  return (
    <section className="surface-card space-y-3 p-5">
      <h2 className="text-lg font-medium">{t("patientPortal.unboundTitle")}</h2>
      <p className="text-sm text-muted-foreground">{t("patientPortal.unboundBody1")}</p>
      <p className="text-sm text-muted-foreground">{t("patientPortal.unboundBody2")}</p>
    </section>
  );
}

export default function Page() {
  const { t } = useLocale();
  const verificationLabel = (method: "abha_otp" | "in_person_document") =>
    method === "abha_otp" ? t("patientPortal.verify.abhaOtp") : t("patientPortal.verify.inPerson");
  const [view, setView] = useState<ViewState>({ status: "loading" });
  const [activeTab, setActiveTab] = useState<"documents" | "permissions" | "identity">("documents");
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
        message: error instanceof Error ? error.message : t("patientPortal.errLoad"),
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
    <main id="main-content" className="mx-auto max-w-6xl space-y-6 p-6">
      <header role="banner" className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-primary">{t("area.patient")}</p>
          <h1 className="mt-2 text-3xl font-semibold">{t("patientPortal.title")}</h1>
        </div>
        <button type="button" className="rounded-md border border-border px-4 py-2 text-sm" onClick={() => void load()}>
          {t("common.refresh")}
        </button>
      </header>

      {view.status === "loading" ? (
        <p role="status" className="surface-card p-5 text-sm text-muted-foreground">{t("patientPortal.loadingRecord")}</p>
      ) : null}
      {view.status === "unbound" ? <UnboundPortal /> : null}
      {view.status === "error" ? (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-muted p-5 text-danger">
          <p className="font-medium">{t("patientPortal.unavailableTitle")}</p>
          <p className="mt-1 text-sm">{view.message}</p>
        </div>
      ) : null}

      {view.status === "ready" ? (
        <>
          {/* Navigation Tab Bar (ARIA compliant) */}
          <div role="tablist" aria-label={t("patientPortal.tabListAria")} className="flex border-b border-border">
            <button
              id="portal-tab-documents"
              role="tab"
              aria-selected={activeTab === "documents"}
              aria-controls="portal-panel-documents"
              type="button"
              onClick={() => setActiveTab("documents")}
              className={`border-b-2 px-5 py-3 text-sm font-semibold transition-colors ${
                activeTab === "documents"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("patientPortal.tab.documents")}
            </button>
            <button
              id="portal-tab-permissions"
              role="tab"
              aria-selected={activeTab === "permissions"}
              aria-controls="portal-panel-permissions"
              type="button"
              onClick={() => setActiveTab("permissions")}
              className={`border-b-2 px-5 py-3 text-sm font-semibold transition-colors ${
                activeTab === "permissions"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("patientPortal.tab.permissions")}
            </button>
            <button
              id="portal-tab-identity"
              role="tab"
              aria-selected={activeTab === "identity"}
              aria-controls="portal-panel-identity"
              type="button"
              onClick={() => setActiveTab("identity")}
              className={`border-b-2 px-5 py-3 text-sm font-semibold transition-colors ${
                activeTab === "identity"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("patientPortal.tab.identity")}
            </button>
          </div>

          {/* Tab 1: Clinical Documents */}
          {activeTab === "documents" && (
            <div id="portal-panel-documents" role="tabpanel" aria-labelledby="portal-tab-documents">
              <ReleasedDocumentsTab />
            </div>
          )}

          {/* Tab 3: ABHA & Identity */}
          {activeTab === "identity" && (
            <div id="portal-panel-identity" role="tabpanel" aria-labelledby="portal-tab-identity">
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
                    {verificationLabel(view.data.binding.verification_method)}
                  </p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Verified {formatDateTime(view.data.binding.verified_at)}
                  </p>
                </article>
              </section>
            </div>
          )}

          {/* Tab 2: Consents & Data Access History */}
          {activeTab === "permissions" && (
            <div id="portal-panel-permissions" role="tabpanel" aria-labelledby="portal-tab-permissions" className="space-y-8">
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
                {verificationLabel(view.data.binding.verification_method)}
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
        </div>
      )}
    </>
  ) : null}
    </main>
  );
}
