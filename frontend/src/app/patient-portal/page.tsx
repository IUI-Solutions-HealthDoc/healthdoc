"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getPortalDashboard,
  type PortalDashboard,
} from "@/features/patientPortal/api";
import { AppointmentRequestsTab } from "@/features/patientPortal/components/AppointmentRequestsTab";
import { ReleasedDocumentsTab } from "@/features/patientPortal/components/ReleasedDocumentsTab";
import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

type ViewState =
  | { status: "loading" }
  | { status: "unbound" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PortalDashboard };

// Stored codes as a patient reads them: "abha_identity" printed as
// "Abha Identity" (QA 17 Oct 2026).
const READABLE: Record<string, string> = {
  abha_identity: "ABHA identity",
  abha: "ABHA",
  patients: "Patient record",
  patient: "Patient record",
  encounters: "Consultation notes",
  lab_results: "Lab results",
  radiology_reports: "Imaging reports",
  prescriptions: "Prescriptions",
  consent_records: "Consent records",
  admissions: "Admission record",
  clinical_review: "Clinical review",
  treatment: "Treatment",
};

function humanise(value: string | null): string {
  if (!value) return "—";
  if (READABLE[value]) return READABLE[value];
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type AccessEntry = PortalDashboard["accessHistory"]["items"][number];

/**
 * One screen opening a record reads it several times within a second or two;
 * listed one by one, the history looked like duplicated events (QA 17 Oct
 * 2026). Identical reads within a minute are shown once with a count.
 */
function collapseRepeats(items: AccessEntry[]): (AccessEntry & { repeats: number })[] {
  const out: (AccessEntry & { repeats: number })[] = [];
  for (const entry of items) {
    const last = out[out.length - 1];
    const same =
      last &&
      last.staff_name === entry.staff_name &&
      last.role === entry.role &&
      last.resource_type === entry.resource_type &&
      last.purpose_code === entry.purpose_code &&
      Boolean(last.emergency_access) === Boolean(entry.emergency_access) &&
      Math.abs(new Date(last.accessed_at).getTime() - new Date(entry.accessed_at).getTime()) <= 60_000;
    if (same) last.repeats += 1;
    else out.push({ ...entry, repeats: 1 });
  }
  return out;
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
  const [activeTab, setActiveTab] = useState<"documents" | "appointments" | "permissions" | "identity">("documents");
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

  const historyItems = view.status === "ready" ? collapseRepeats(view.data.accessHistory.items) : [];
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
              id="portal-tab-appointments"
              role="tab"
              aria-selected={activeTab === "appointments"}
              aria-controls="portal-panel-appointments"
              type="button"
              onClick={() => setActiveTab("appointments")}
              className={`border-b-2 px-5 py-3 text-sm font-semibold transition-colors ${
                activeTab === "appointments"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("patientPortal.tab.appointments")}
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

          {activeTab === "appointments" && (
            <div id="portal-panel-appointments" role="tabpanel" aria-labelledby="portal-tab-appointments">
              <AppointmentRequestsTab />
            </div>
          )}

          {/* Tab 3: ABHA & Identity */}
          {activeTab === "identity" && (
            <div id="portal-panel-identity" role="tabpanel" aria-labelledby="portal-tab-identity">
              <section className="grid gap-4 md:grid-cols-2">
                <article className="surface-card p-5">
                  <p className="text-sm text-muted-foreground">{t("receptionist.abha.title")}</p>
                  <p className="mt-2 text-xl font-semibold">{view.data.abha.abha_number ?? t("doctor.abdm.notLinked")}</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {view.data.abha.linked_at
                      ? `Linked ${formatDateTime(view.data.abha.linked_at)}`
                      : t("patientPortal.abhaLinkHint")}
                  </p>
                </article>
                <article className="surface-card p-5">
                  <p className="text-sm text-muted-foreground">{t("patientPortal.verifiedBy")}</p>
                  <p className="mt-2 text-xl font-semibold">
                    {verificationLabel(view.data.binding.verification_method)}
                  </p>
                  <p className="mt-2 text-sm text-muted-foreground">{t("patientPortal.ui.verifiedVerifiedAt", { verified_at: formatDateTime(view.data.binding.verified_at) })}</p>
                </article>
              </section>
            </div>
          )}

          {/* Tab 2: Consents & Data Access History */}
          {activeTab === "permissions" && (
            <div id="portal-panel-permissions" role="tabpanel" aria-labelledby="portal-tab-permissions" className="space-y-8">
          <section className="grid gap-4 md:grid-cols-2">
            <article className="surface-card p-5">
              <p className="text-sm text-muted-foreground">{t("receptionist.abha.title")}</p>
              <p className="mt-2 text-xl font-semibold">{view.data.abha.abha_number ?? t("doctor.abdm.notLinked")}</p>
              <p className="mt-2 text-sm text-muted-foreground">
                {view.data.abha.linked_at
                  ? `Linked ${formatDateTime(view.data.abha.linked_at)}`
                  : t("patientPortal.abhaLinkHint")}
              </p>
            </article>
            <article className="surface-card p-5">
              <p className="text-sm text-muted-foreground">{t("patientPortal.verifiedBy")}</p>
              <p className="mt-2 text-xl font-semibold">
                {verificationLabel(view.data.binding.verification_method)}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">{t("patientPortal.ui.verifiedVerifiedAt", { verified_at: formatDateTime(view.data.binding.verified_at) })}</p>
            </article>
          </section>

          <section className="surface-card overflow-hidden">
            <div className="border-b border-border p-5">
              <h2 className="text-lg font-semibold">{t("patientPortal.consentsTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("patientPortal.consentsSubtitle", { count: consents.length })}</p>
            </div>
            {consents.length === 0 ? (
              <p className="p-5 text-sm text-muted-foreground">{t("patientPortal.noConsents")}</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">{t("field.purpose")}</th><th className="p-3">{t("common.status")}</th><th className="p-3">{t("consent.status.granted")}</th><th className="p-3">{t("receptionist.scanShare.expires")}</th></tr></thead>
                    <tbody>{paginatedConsents.map((consent) => (
                      <tr key={consent.id} className="border-t border-border"><td className="p-3"><span className="font-medium">{humanise(consent.purpose_code)}</span>{consent.purpose_description ? <span className="block text-xs text-muted-foreground">{consent.purpose_description}</span> : null}</td><td className="p-3 capitalize">{humanise(consent.status)}</td><td className="p-3">{formatDateTime(consent.granted_at)}</td><td className="p-3">{consent.expires_at ? formatDateTime(consent.expires_at) : t("patientPortal.noExpiry")}</td></tr>
                    ))}</tbody>
                  </table>
                </div>

                {consents.length > CONSENT_PAGE_SIZE && (
                  <div className="flex items-center justify-between border-t border-border px-4 py-2.5 bg-muted/20 text-xs">
                    <span className="text-muted-foreground">{t("patientPortal.ui.pageConsentpageOfTotalconsentpages", { consentPage, totalConsentPages })}</span>
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={consentPage <= 1}
                        onClick={() => setConsentPage((p) => Math.max(1, p - 1))}
                        className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                      >{t("patientPortal.ui.prev")}</button>
                      <button
                        type="button"
                        disabled={consentPage >= totalConsentPages}
                        onClick={() => setConsentPage((p) => Math.min(totalConsentPages, p + 1))}
                        className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                      >{t("common.next")}</button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="surface-card overflow-hidden">
            <div className="border-b border-border p-5">
              <h2 className="text-lg font-semibold">{t("patientPortal.accessHistoryTitle")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t("patientPortal.ui.totalRecordedAccessEventsNewestFirst", { total: view.data.accessHistory.total })}</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted/50 text-muted-foreground"><tr><th className="p-3">{t("patientPortal.col.when")}</th><th className="p-3">{t("patientPortal.col.accessedBy")}</th><th className="p-3">{t("patientPortal.col.data")}</th><th className="p-3">{t("field.purpose")}</th></tr></thead>
                <tbody>{paginatedHistory.map((entry, index) => (
                  <tr key={`${entry.accessed_at}-${index}`} className="border-t border-border"><td className="p-3">{formatDateTime(entry.accessed_at)}</td><td className="p-3">{entry.staff_name ?? t("consent.access.api")}<span className="block text-xs text-muted-foreground">{humanise(entry.role)}</span></td><td className="p-3">{humanise(entry.resource_type)}{entry.repeats > 1 ? <span className="ml-1 text-xs text-muted-foreground">×{entry.repeats}</span> : null}{entry.emergency_access ? <span className="ml-2 rounded bg-danger-muted px-2 py-0.5 text-xs text-danger">{t("role.emergency")}</span> : null}</td><td className="p-3">{humanise(entry.purpose_code)}</td></tr>
                ))}</tbody>
              </table>
            </div>

            {historyItems.length > HISTORY_PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-border px-4 py-2.5 bg-muted/20 text-xs">
                <span className="text-muted-foreground">{t("patientPortal.ui.pageHistorypageOfTotalhistorypages", { historyPage, totalHistoryPages })}</span>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={historyPage <= 1}
                    onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
                    className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                  >{t("patientPortal.ui.prev")}</button>
                  <button
                    type="button"
                    disabled={historyPage >= totalHistoryPages}
                    onClick={() => setHistoryPage((p) => Math.min(totalHistoryPages, p + 1))}
                    className="rounded border border-border bg-card px-2.5 py-1 disabled:opacity-50"
                  >{t("common.next")}</button>
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
