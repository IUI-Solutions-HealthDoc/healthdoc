"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, BookOpen, RefreshCw, Search, Syringe } from "lucide-react";
import { fetchVaccineCatalogue, fetchImmunizationCertificate } from "./api";
import { ImmunizationCertificateModal } from "./components/ImmunizationCertificateModal";
import { ImmunizationScheduleView } from "./components/ImmunizationScheduleView";
import { RecordImmunizationModal } from "./components/RecordImmunizationModal";
import type { ImmunizationCertificate, Vaccine } from "./types";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface PatientSearchResult {
  items: Array<{
    id: string;
    uhid: string;
    full_name?: string;
    first_name?: string;
    last_name?: string;
  }>;
}

const describe = (err: unknown, fallback: string) =>
  err instanceof Error && err.message ? err.message : fallback;

export function ImmunizationPage() {
  const { t } = useLocale();
  const [catalogue, setCatalogue] = useState<Vaccine[]>([]);
  const [loadingCatalogue, setLoadingCatalogue] = useState(true);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const catalogueSequence = useRef(0);

  // Selected patient state
  const [patientSearch, setPatientSearch] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const searchSequence = useRef(0);
  const [activePatient, setActivePatient] = useState<{
    id: string;
    uhid: string;
    full_name: string;
  } | null>(null);

  const patientRef = useRef(activePatient);
  patientRef.current = activePatient;

  // Modals state
  const [isRecordModalOpen, setIsRecordModalOpen] = useState(false);
  const [isCertModalOpen, setIsCertModalOpen] = useState(false);
  const [certificateData, setCertificateData] = useState<ImmunizationCertificate | null>(null);
  const [certificateError, setCertificateError] = useState<string | null>(null);
  const [refreshScheduleTrigger, setRefreshScheduleTrigger] = useState(0);

  // View tabs
  const [topTab, setTopTab] = useState<"patient" | "catalogue">("patient");

  // A failed catalogue read used to render an empty catalogue and a dose
  // modal with no vaccines, which reads as "nothing is configured" rather
  // than "the read failed". It is shown as a failure with a retry.
  const loadCatalogue = useCallback(async () => {
    const request = ++catalogueSequence.current;
    setCatalogueError(null);
    try {
      const cat = await fetchVaccineCatalogue();
      if (request !== catalogueSequence.current) return;
      setCatalogue(cat);
    } catch (err: unknown) {
      if (request === catalogueSequence.current)
        setCatalogueError(describe(err, t("immunization.errCatalogue")));
    } finally {
      if (request === catalogueSequence.current) setLoadingCatalogue(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCatalogue();
  }, [loadCatalogue]);

  const handlePatientSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const term = patientSearch.trim();
    if (!term || isSearching) return;
    const request = ++searchSequence.current;
    setIsSearching(true);
    setSearchError(null);
    try {
      // Digits search by mobile number, anything else by UHID; there is no
      // name search on this request, so the placeholder must not offer one.
      const body = /^\d+$/.test(term)
        ? { mobile: term, page: 1, page_size: 5 }
        : { uhid: term, page: 1, page_size: 5 };
      const res = await api<PatientSearchResult>("/patients/search", {
        method: "POST",
        idempotencyKey: null,
        body: JSON.stringify(body),
      });
      if (request !== searchSequence.current) return;
      const items = res?.items ?? [];
      if (items.length === 1) {
        setCertificateData(null); setCertificateError(null); setIsCertModalOpen(false); setIsRecordModalOpen(false);
        const p = items[0];
        setActivePatient({
          id: p.id,
          uhid: p.uhid,
          full_name: p.full_name || `${p.first_name || ""} ${p.last_name || ""}`.trim() || t("common.patient"),
        });
      } else if (items.length === 0) {
        setSearchError(t("immunization.errNoPatientMatch"));
      } else {
        setSearchError(t("immunization.errMultiplePatients", { count: items.length }));
      }
    } catch (err: unknown) {
      if (request === searchSequence.current) setSearchError(describe(err, t("immunization.errSearchFailed")));
    } finally {
      if (request === searchSequence.current) setIsSearching(false);
    }
  };

  const handleOpenCertificate = async () => {
    if (!activePatient) return;
    setCertificateError(null);
    try {
      const cert = await fetchImmunizationCertificate(activePatient.id);
      if (patientRef.current !== activePatient) return;
      setCertificateData(cert);
      setIsCertModalOpen(true);
    } catch (err: unknown) {
      if (patientRef.current === activePatient)
        setCertificateError(describe(err, t("immunization.errCertificate")));
    }
  };

  if (loadingCatalogue) {
    return (
      <div className="flex items-center justify-center p-16 text-muted-foreground">
        <RefreshCw className="h-6 w-6 animate-spin mr-2" />
        <span>{t("immunization.loadingCatalogue")}</span>
      </div>
    );
  }

  if (catalogueError && catalogue.length === 0) {
    return (
      <div role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/10 p-8 text-center text-sm text-destructive space-y-3">
        <AlertCircle className="h-8 w-8 mx-auto" />
        <p>{t("immunization.errCatalogueDetail", { message: catalogueError })}</p>
        <p className="text-xs text-muted-foreground">{t("immunization.errCatalogueHint")}</p>
        <button
          type="button"
          onClick={() => void loadCatalogue()}
          className="rounded-xl border border-destructive/40 px-4 py-2 text-xs font-semibold hover:bg-destructive/10 transition-colors"
        >
          {t("immunization.retryCatalogue")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Navigation Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-foreground flex items-center gap-2">
            <Syringe className="h-7 w-7 text-primary" />
            {t("immunization.title")}
          </h1>
          <p className="text-xs text-muted-foreground mt-1">{t("immunization.subtitle")}</p>
        </div>

        {/* Tab switcher */}
        <div className="inline-flex rounded-xl bg-muted p-1 border border-border">
          <button
            onClick={() => setTopTab("patient")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              topTab === "patient"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Syringe className="h-3.5 w-3.5" />
            {t("immunization.tab.patientSchedule")}
          </button>
          <button
            onClick={() => setTopTab("catalogue")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              topTab === "catalogue"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <BookOpen className="h-3.5 w-3.5" />
            {t("immunization.tab.catalogueCount", { count: catalogue.length })}
          </button>
        </div>
      </div>

      {topTab === "patient" ? (
        <div className="space-y-6">
          {/* Patient Search Bar */}
          <div className="rounded-2xl border border-border bg-card p-4 shadow-sm space-y-2">
            <form onSubmit={handlePatientSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder={t("immunization.searchPlaceholder")}
                  value={patientSearch}
                  onChange={(e) => setPatientSearch(e.target.value)}
                  className="w-full rounded-xl border border-input bg-background pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <button
                type="submit"
                disabled={isSearching}
                className="rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {isSearching ? t("immunization.searching") : t("immunization.findPatient")}
              </button>
            </form>
            {searchError && (
              <p role="alert" className="flex items-center gap-2 text-xs text-destructive">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {searchError}
              </p>
            )}
            {certificateError && (
              <p role="alert" className="flex items-center gap-2 text-xs text-destructive">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {certificateError}
              </p>
            )}
          </div>

          {activePatient ? (
            <ImmunizationScheduleView key={activePatient.id}
              patientId={activePatient.id}
              patientName={activePatient.full_name}
              uhid={activePatient.uhid}
              onOpenRecordModal={() => setIsRecordModalOpen(true)}
              onOpenCertificateModal={handleOpenCertificate}
              refreshTrigger={refreshScheduleTrigger}
            />
          ) : (
            <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted-foreground text-sm">
              <Syringe className="h-10 w-10 mx-auto mb-3 opacity-30 text-primary" />
              {t("immunization.noPatientSelected")}
            </div>
          )}
        </div>
      ) : (
        /* Catalogue Table */
        <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
          <div className="p-4 border-b border-border bg-muted/20 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-foreground">{t("immunization.catalogueTitle")}</h3>
              <p className="text-xs text-muted-foreground">{t("immunization.catalogueSubtitle")}</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/50 text-muted-foreground font-semibold">
                <tr>
                  <th className="p-3">{t("immunization.col.vaccineName")}</th>
                  <th className="p-3">{t("immunization.col.code")}</th>
                  <th className="p-3">{t("immunization.col.targetDisease")}</th>
                  <th className="p-3">{t("immunization.col.scheduleAge")}</th>
                  <th className="p-3">{t("immunization.col.dose")}</th>
                  <th className="p-3">{t("immunization.col.route")}</th>
                  <th className="p-3">{t("immunization.col.site")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {catalogue.map((v) => (
                  <tr key={v.id} className="hover:bg-muted/30">
                    <td className="p-3 font-semibold text-foreground">{v.name}</td>
                    <td className="p-3 font-mono font-medium text-primary">{v.code}</td>
                    <td className="p-3 text-muted-foreground">{v.target_disease}</td>
                    <td className="p-3 font-medium">
                      {v.min_age_days === 0
                        ? t("immunization.atBirth")
                        : t("immunization.daysAge", { days: v.min_age_days })}
                    </td>
                    <td className="p-3">
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                        {t("immunization.doseLabel", { n: v.standard_doses })}
                      </span>
                    </td>
                    <td className="p-3 text-muted-foreground">{v.route}</td>
                    <td className="p-3 text-muted-foreground">{v.site || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Record Immunization Modal */}
      {activePatient && (
        <RecordImmunizationModal key={`${activePatient.id}:${isRecordModalOpen}`}
          isOpen={isRecordModalOpen}
          onClose={() => setIsRecordModalOpen(false)}
          patientId={activePatient.id}
          catalogue={catalogue}
          onSuccess={() => {
            setRefreshScheduleTrigger((prev) => prev + 1);
          }}
        />
      )}

      {/* Certificate Modal */}
      <ImmunizationCertificateModal
        isOpen={isCertModalOpen}
        onClose={() => setIsCertModalOpen(false)}
        certificate={certificateData}
      />
    </div>
  );
}
