"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpen, RefreshCw, Search, Syringe } from "lucide-react";
import { fetchVaccineCatalogue, fetchImmunizationCertificate } from "./api";
import { ImmunizationCertificateModal } from "./components/ImmunizationCertificateModal";
import { ImmunizationScheduleView } from "./components/ImmunizationScheduleView";
import { RecordImmunizationModal } from "./components/RecordImmunizationModal";
import type { ImmunizationCertificate, Vaccine } from "./types";
import { api } from "@/lib/api";

interface PatientSearchResult {
  items: Array<{
    id: string;
    uhid: string;
    full_name?: string;
    first_name?: string;
    last_name?: string;
  }>;
}

export function ImmunizationPage() {
  const [catalogue, setCatalogue] = useState<Vaccine[]>([]);
  const [loadingCatalogue, setLoadingCatalogue] = useState(true);

  // Selected patient state
  const [patientSearch, setPatientSearch] = useState("");
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
  const [refreshScheduleTrigger, setRefreshScheduleTrigger] = useState(0);

  // View tabs
  const [topTab, setTopTab] = useState<"patient" | "catalogue">("patient");

  useEffect(() => {
    async function loadData() {
      try {
        setLoadingCatalogue(true);
        const cat = await fetchVaccineCatalogue();
        setCatalogue(cat);
      } catch (err: unknown) {
        console.error("Failed to load vaccine catalogue:", err);
      } finally {
        setLoadingCatalogue(false);
      }
    }
    loadData();
  }, []);

  const handlePatientSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!patientSearch.trim()) return;
    try {
      const isDigits = /^\d+$/.test(patientSearch.trim());
      const body = isDigits
        ? { mobile: patientSearch.trim(), page: 1, page_size: 5 }
        : { uhid: patientSearch.trim(), page: 1, page_size: 5 };
      const res = await api<PatientSearchResult>("/patients/search", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (res?.items && res.items.length === 1) {
        setCertificateData(null); setIsCertModalOpen(false); setIsRecordModalOpen(false);
        const p = res.items[0];
        setActivePatient({
          id: p.id,
          uhid: p.uhid,
          full_name: p.full_name || `${p.first_name || ""} ${p.last_name || ""}`.trim() || "Patient",
        });
      }
    } catch (err: unknown) {
      console.error("Search failed:", err);
    }
  };

  const handleOpenCertificate = async () => {
    if (!activePatient) return;
    try {
      const cert = await fetchImmunizationCertificate(activePatient.id);
      if (patientRef.current !== activePatient) return;
      setCertificateData(cert);
      setIsCertModalOpen(true);
    } catch (err: unknown) {
      console.error("Failed to load certificate:", err);
    }
  };

  if (loadingCatalogue) {
    return (
      <div className="flex items-center justify-center p-16 text-muted-foreground">
        <RefreshCw className="h-6 w-6 animate-spin mr-2" />
        <span>Loading immunization catalogue...</span>
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
            Immunization Management
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Universal Immunization Programme, paediatric schedules, batch traceability & digital certification
          </p>
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
            Patient Schedule
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
            Vaccine Catalogue ({catalogue.length})
          </button>
        </div>
      </div>

      {topTab === "patient" ? (
        <div className="space-y-6">
          {/* Patient Search Bar */}
          <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
            <form onSubmit={handlePatientSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search patient by UHID, Name, or Mobile number..."
                  value={patientSearch}
                  onChange={(e) => setPatientSearch(e.target.value)}
                  className="w-full rounded-xl border border-input bg-background pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
              <button
                type="submit"
                className="rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Find Patient
              </button>
            </form>
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
              Search for a patient or enter a UHID above to review due vaccines and record immunizations.
            </div>
          )}
        </div>
      ) : (
        /* Catalogue Table */
        <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
          <div className="p-4 border-b border-border bg-muted/20 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-foreground">Standardized National Vaccine Schedule</h3>
              <p className="text-xs text-muted-foreground">Universal Immunization Programme (UIP) approved antigens</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-muted/50 text-muted-foreground font-semibold">
                <tr>
                  <th className="p-3">Vaccine Name</th>
                  <th className="p-3">Code</th>
                  <th className="p-3">Target Disease</th>
                  <th className="p-3">Schedule Age</th>
                  <th className="p-3">Dose #</th>
                  <th className="p-3">Route</th>
                  <th className="p-3">Site</th>
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
                        ? "At Birth"
                        : `${v.min_age_days} days`}
                    </td>
                    <td className="p-3">
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                        Dose {v.standard_doses}
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
