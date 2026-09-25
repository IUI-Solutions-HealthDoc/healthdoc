"use client";



import { useCallback, useEffect, useRef, useState } from "react";

import {

  AlertCircle,

  FileCheck,

  FileSpreadsheet,

  FileText,

  History,

  Layers,

  RefreshCw,

  Search,

} from "lucide-react";

import { fetchFormDefinitions, fetchOrderSets, fetchPatientSubmissions } from "./api";

import { ClinicalOrderSetsModal } from "./components/ClinicalOrderSetsModal";

import { CsvAdministrationModal } from "./components/CsvAdministrationModal";

import { DynamicFormRenderer } from "./components/DynamicFormRenderer";

import type { ClinicalOrderSet, FormDefinition, FormSubmission } from "./types";

import { api, formatDateTime } from "@/lib/api";

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



export function FormsPage() {

  const { t } = useLocale();

  const [formDefs, setFormDefs] = useState<FormDefinition[]>([]);

  const [orderSets, setOrderSets] = useState<ClinicalOrderSet[]>([]);

  const [selectedForm, setSelectedForm] = useState<FormDefinition | null>(null);

  const [loading, setLoading] = useState(true);

  const [loadError, setLoadError] = useState<string | null>(null);

  const loadSequence = useRef(0);



  // Active patient & visit

  const [patientSearch, setPatientSearch] = useState("");

  const [isSearching, setIsSearching] = useState(false);

  const [searchError, setSearchError] = useState<string | null>(null);

  const searchSequence = useRef(0);

  const [activePatient, setActivePatient] = useState<{

    id: string;

    uhid: string;

    full_name: string;

  } | null>(null);

  const activePatientRef = useRef(activePatient);

  activePatientRef.current = activePatient;

  const [submissions, setSubmissions] = useState<FormSubmission[]>([]);

  const [historyError, setHistoryError] = useState<string | null>(null);

  const [historyAttempt, setHistoryAttempt] = useState(0);

  const [activeTab, setActiveTab] = useState<"fill" | "history">("fill");



  // Modals

  const [isOrderSetOpen, setIsOrderSetOpen] = useState(false);

  const [isCsvAdminOpen, setIsCsvAdminOpen] = useState(false);



  const loadData = useCallback(async () => {

    const request = ++loadSequence.current;

    setLoadError(null);

    try {

      const [defs, sets] = await Promise.all([fetchFormDefinitions(), fetchOrderSets()]);

      if (request !== loadSequence.current) return;

      setFormDefs(defs);

      setOrderSets(sets);

      setSelectedForm((prev) => (prev && defs.some((d) => d.id === prev.id) ? prev : defs[0] ?? null));

    } catch (err) {

      if (request === loadSequence.current) setLoadError(describe(err, t("forms.errLoad")));

    } finally {

      if (request === loadSequence.current) setLoading(false);

    }

  }, [t]);



  useEffect(() => {

    void loadData();

  }, [loadData]);



  useEffect(() => {

    let cancelled = false;

    setSubmissions([]);

    setHistoryError(null);

    if (activePatient?.id) {

      fetchPatientSubmissions(activePatient.id)

        .then((subs) => { if (!cancelled) setSubmissions(subs); })

        .catch((err: unknown) => {

          if (!cancelled) {

            setHistoryError(describe(err, t("forms.errHistoryFallback")));

          }

        });

    }

    return () => { cancelled = true; };

  }, [activePatient, historyAttempt, t]);



  const handlePatientSearch = async (e: React.FormEvent) => {

    e.preventDefault();

    const term = patientSearch.trim();

    if (!term || isSearching) return;

    const request = ++searchSequence.current;

    setIsSearching(true);

    setSearchError(null);

    try {

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

        const p = items[0];

        setActivePatient({

          id: p.id,

          uhid: p.uhid,

          full_name: p.full_name || `${p.first_name || ""} ${p.last_name || ""}`.trim() || t("common.patient"),

        });

      } else if (items.length === 0) {

        setSearchError(t("forms.errNoPatientMatch"));

      } else {

        setSearchError(t("forms.errMultiplePatients", { count: items.length }));

      }

    } catch (err: unknown) {

      if (request === searchSequence.current) setSearchError(describe(err, t("forms.errSearchFailed")));

    } finally {

      if (request === searchSequence.current) setIsSearching(false);

    }

  };



  const historyPatientName = activePatient?.full_name || t("common.patient");



  return (

    <div className="space-y-6">

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">

        <div>

          <h1 className="text-2xl font-black tracking-tight text-foreground flex items-center gap-2">

            <FileText className="h-7 w-7 text-primary" />

            {t("forms.title")}

          </h1>

          <p className="text-xs text-muted-foreground mt-1">{t("forms.subtitle")}</p>

        </div>



        <div className="flex items-center gap-2">

          <button

            onClick={() => setIsCsvAdminOpen(true)}

            className="flex items-center gap-1.5 rounded-xl border border-border bg-card px-3.5 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors shadow-sm"

          >

            <FileSpreadsheet className="h-4 w-4 text-emerald-500" />

            {t("forms.csvAdmin")}

          </button>

          <button

            onClick={() => setIsOrderSetOpen(true)}

            className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"

          >

            <Layers className="h-4 w-4" />

            {t("forms.previewOrderSets")}

          </button>

        </div>

      </div>



      <div className="rounded-2xl border border-border bg-card p-4 shadow-sm space-y-2">

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">

          <form onSubmit={handlePatientSearch} className="flex flex-1 gap-2">

            <div className="relative flex-1">

              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />

              <input

                type="text"

                placeholder={t("forms.searchPlaceholder")}

                value={patientSearch}

                onChange={(e) => setPatientSearch(e.target.value)}

                className="w-full rounded-xl border border-input bg-background pl-9 pr-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"

              />

            </div>

            <button

              type="submit"

              disabled={isSearching}

              className="rounded-xl bg-secondary px-3.5 py-2 text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 transition-colors shrink-0 disabled:opacity-50"

            >

              {isSearching ? t("forms.searching") : t("forms.find")}

            </button>

          </form>



          {activePatient && (

            <div className="flex items-center gap-3 px-3 py-1.5 rounded-xl bg-primary/10 border border-primary/20 text-xs">

              <div>

                <span className="font-bold text-foreground">{activePatient.full_name}</span>

                <span className="text-muted-foreground font-mono ml-2">

                  {t("field.uhid")}: {activePatient.uhid}

                </span>

              </div>

            </div>

          )}

        </div>

        {searchError && (

          <p role="alert" className="flex items-center gap-2 text-xs text-destructive">

            <AlertCircle className="h-3.5 w-3.5 shrink-0" />

            {searchError}

          </p>

        )}

      </div>



      {loading ? (

        <div className="flex items-center justify-center p-16 text-muted-foreground">

          <RefreshCw className="h-6 w-6 animate-spin mr-2" />

          <span>{t("forms.loading")}</span>

        </div>

      ) : loadError && formDefs.length === 0 ? (

        <div role="alert" className="rounded-2xl border border-destructive/30 bg-destructive/10 p-8 text-center text-sm text-destructive space-y-3">

          <AlertCircle className="h-8 w-8 mx-auto" />

          <p>{t("forms.errLoadDetail", { message: loadError })}</p>

          <button

            type="button"

            onClick={() => void loadData()}

            className="rounded-xl border border-destructive/40 px-4 py-2 text-xs font-semibold hover:bg-destructive/10 transition-colors"

          >

            {t("forms.retryLoad")}

          </button>

        </div>

      ) : (

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">

          {loadError && (

            <p role="alert" className="md:col-span-4 flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">

              <AlertCircle className="h-3.5 w-3.5 shrink-0" />

              {t("forms.errRefreshList", { message: loadError })}

            </p>

          )}

          <div className="md:col-span-1 space-y-4">

            <div className="rounded-2xl border border-border bg-card p-4 shadow-sm space-y-2">

              <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground block mb-2">

                {t("forms.availableForms", { count: formDefs.length })}

              </span>

              <div className="space-y-1.5">

                {formDefs.map((def) => (

                  <button

                    key={def.id}

                    onClick={() => {

                      setSelectedForm(def);

                      setActiveTab("fill");

                    }}

                    className={`w-full text-left p-3 rounded-xl border transition-all text-xs ${

                      selectedForm?.id === def.id && activeTab === "fill"

                        ? "border-primary bg-primary/10 text-foreground font-semibold"

                        : "border-border bg-background text-muted-foreground hover:bg-muted"

                    }`}

                  >

                    <div className="font-bold text-foreground">{def.title}</div>

                    <div className="text-[10px] text-muted-foreground font-mono mt-0.5">

                      {def.code} • {t("forms.fieldsCount", { count: def.fields_schema.length })}

                    </div>

                  </button>

                ))}

              </div>



              <div className="pt-2 border-t border-border">

                <button

                  onClick={() => setActiveTab("history")}

                  className={`w-full text-left p-3 rounded-xl border transition-all text-xs flex items-center gap-2 ${

                    activeTab === "history"

                      ? "border-primary bg-primary/10 text-foreground font-semibold"

                      : "border-border bg-background text-muted-foreground hover:bg-muted"

                  }`}

                >

                  <History className="h-4 w-4 text-primary" />

                  <div>

                    <div className="font-bold text-foreground">{t("forms.patientSubmissions")}</div>

                    <div className="text-[10px] text-muted-foreground font-mono mt-0.5">

                      {historyError

                        ? t("forms.historyUnavailable")

                        : t("forms.completedRecords", { count: submissions.length })}

                    </div>

                  </div>

                </button>

              </div>

            </div>

          </div>



          <div className="md:col-span-3">

            {activeTab === "fill" ? (

              selectedForm && activePatient ? (

                <DynamicFormRenderer

                  key={`${activePatient.id}:${selectedForm.id}`}

                  formDef={selectedForm}

                  patientId={activePatient.id}

                  onSuccess={(sub) => {

                    if (sub.patient_id !== activePatientRef.current?.id) return;

                    setSubmissions((prev) => [sub, ...prev]);

                  }}

                />

              ) : (

                <div className="rounded-2xl border border-dashed border-border p-12 text-center text-muted-foreground text-sm">

                  {t("forms.selectFormPatient")}

                </div>

              )

            ) : (

              <div className="rounded-2xl border border-border bg-card p-6 shadow-sm space-y-4">

                <div className="flex items-center justify-between border-b border-border pb-3">

                  <h3 className="text-base font-bold text-foreground">

                    {t("forms.historyTitle", { name: historyPatientName })}

                  </h3>

                  <span className="text-xs font-mono text-muted-foreground">

                    {t("forms.entries", { count: submissions.length })}

                  </span>

                </div>



                {historyError ? (

                  <div role="alert" className="text-center py-12 text-destructive text-xs space-y-3">

                    <AlertCircle className="h-8 w-8 mx-auto" />

                    <p>{t("forms.errHistoryLoad", { message: historyError })}</p>

                    <p className="text-muted-foreground">{t("forms.errHistoryHint")}</p>

                    <button

                      type="button"

                      onClick={() => setHistoryAttempt((n) => n + 1)}

                      className="rounded-xl border border-destructive/40 px-4 py-2 text-xs font-semibold hover:bg-destructive/10 transition-colors"

                    >

                      {t("forms.retryHistory")}

                    </button>

                  </div>

                ) : submissions.length === 0 ? (

                  <div className="text-center py-12 text-muted-foreground text-xs">

                    <FileCheck className="h-8 w-8 mx-auto mb-2 opacity-30 text-primary" />

                    {t("forms.noSubmissions")}

                  </div>

                ) : (

                  <div className="space-y-3">

                    {submissions.map((sub) => (

                      <div

                        key={sub.id}

                        className="p-4 rounded-xl border border-border bg-background space-y-2 text-xs"

                      >

                        <div className="flex items-center justify-between">

                          <span className="font-bold text-foreground">

                            {t("forms.submissionLabel", { id: sub.id.slice(0, 8) })}

                          </span>

                          <span className="text-[11px] text-muted-foreground font-mono">

                            {formatDateTime(sub.submitted_at || sub.created_at)}

                          </span>

                        </div>

                        <div className="bg-muted/30 p-3 rounded-lg font-mono text-[11px] max-h-40 overflow-y-auto">

                          <pre className="whitespace-pre-wrap">

                            {JSON.stringify(sub.form_data, null, 2)}

                          </pre>

                        </div>

                      </div>

                    ))}

                  </div>

                )}

              </div>

            )}

          </div>

        </div>

      )}



      {activePatient && (

        <ClinicalOrderSetsModal

          isOpen={isOrderSetOpen}

          onClose={() => setIsOrderSetOpen(false)}

          orderSets={orderSets}

        />

      )}



      <CsvAdministrationModal

        isOpen={isCsvAdminOpen}

        onClose={() => setIsCsvAdminOpen(false)}

        onSuccess={loadData}

      />

    </div>

  );

}


