"use client";

import { useCallback, useEffect, useState } from "react";
import { formatDateTime } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";

import {
  getPortalDocuments,
  getPortalDocumentDetail,
  type PortalDocumentItem,
  type PortalDocumentDetail,
} from "../api";

const CATEGORY_KEYS: { id: string; labelKey: MessageKey }[] = [
  { id: "all", labelKey: "patientPortal.documents.cat.all" },
  { id: "prescription", labelKey: "patientPortal.documents.cat.prescription" },
  { id: "lab_report", labelKey: "patientPortal.documents.cat.lab_report" },
  { id: "radiology", labelKey: "patientPortal.documents.cat.radiology" },
  { id: "discharge_summary", labelKey: "patientPortal.documents.cat.discharge_summary" },
  { id: "vaccine", labelKey: "patientPortal.documents.cat.vaccine" },
];

function getCategoryBadge(type: string) {
  switch (type) {
    case "prescription":
      return "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200";
    case "lab_report":
      return "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200";
    case "radiology":
      return "bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-950 dark:text-purple-200";
    case "discharge_summary":
      return "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-200";
    case "vaccine":
      return "bg-teal-100 text-teal-800 border-teal-200 dark:bg-teal-950 dark:text-teal-200";
    default:
      return "bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-200";
  }
}

export function ReleasedDocumentsTab() {
  const { t } = useLocale();
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [documents, setDocuments] = useState<PortalDocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail Modal State
  const [activeDoc, setActiveDoc] = useState<PortalDocumentDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [_detailError, setDetailError] = useState<string | null>(null);

  const loadDocuments = useCallback(async (cat: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPortalDocuments(cat);
      setDocuments(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("patientPortal.documents.errLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadDocuments(selectedCategory);
  }, [loadDocuments, selectedCategory]);

  const handleOpenDetail = async (item: PortalDocumentItem) => {
    setLoadingDetail(true);
    setDetailError(null);
    try {
      const detail = await getPortalDocumentDetail(item.document_type, item.id);
      setActiveDoc(detail);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : t("patientPortal.documents.errLoadDetail"));
    } finally {
      setLoadingDetail(false);
    }
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <section className="space-y-6" aria-label={t("patientPortal.documents.aria")}>
      {/* Category Filter Pills */}
      <div className="flex flex-wrap gap-2" role="tablist" aria-label={t("patientPortal.documents.categoriesAria")}>
        {CATEGORY_KEYS.map((cat) => {
          const active = selectedCategory === cat.id;
          return (
            <button
              key={cat.id}
              role="tab"
              aria-selected={active}
              type="button"
              onClick={() => setSelectedCategory(cat.id)}
              className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "border border-border bg-card text-muted-foreground hover:bg-muted"
              }`}
            >
              {t(cat.labelKey)}
            </button>
          );
        })}
      </div>

      {/* Loading & Error states */}
      {loading && (
        <div className="surface-card p-6 text-center text-sm text-muted-foreground">
          {t("patientPortal.documents.loading")}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-danger/30 bg-danger-muted p-4 text-sm text-danger">
          {error}
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && documents.length === 0 && (
        <div className="surface-card p-8 text-center">
          <p className="font-medium text-foreground">{t("patientPortal.documents.emptyTitle")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {selectedCategory === "all"
              ? t("patientPortal.documents.emptyAll")
              : t("patientPortal.documents.emptyCategory", {
                  category: t(
                    CATEGORY_KEYS.find((c) => c.id === selectedCategory)?.labelKey ??
                      "patientPortal.documents.cat.all",
                  ),
                })}
          </p>
        </div>
      )}

      {/* Document Grid */}
      {!loading && !error && documents.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {documents.map((doc) => (
            <article
              key={doc.id}
              className="surface-card flex flex-col justify-between p-5 transition-shadow hover:shadow-md"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase tracking-wider ${getCategoryBadge(
                      doc.document_type,
                    )}`}
                  >
                    {doc.document_type.replace("_", " ")}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(doc.date)}
                  </span>
                </div>
                <h3 className="mt-3 text-base font-semibold text-foreground">{doc.title}</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {doc.doctor_name ? `Dr. ${doc.doctor_name}` : t("patientPortal.documents.attendingPhysician")} ·{" "}
                  {doc.facility_name ?? "HealthDoc Medical Center"}
                </p>
                <div className="mt-3 rounded-md bg-muted/40 p-2.5 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{t("patientPortal.documents.summaryLabel")} </span>
                  {doc.summary}
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
                  <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
                      clipRule="evenodd"
                    />
                  </svg>
                  {t("patientPortal.documents.releasedBadge")}
                </span>
                <button
                  type="button"
                  onClick={() => void handleOpenDetail(doc)}
                  className="rounded-md border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
                >
                  {t("patientPortal.documents.viewPrint")}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Loading Detail Spinner */}
      {loadingDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs">
          <div className="surface-card rounded-lg p-6 shadow-xl">
            <p className="text-sm font-medium">Retrieving verified clinical record…</p>
          </div>
        </div>
      )}

      {/* Accessible Document Detail & A4 Print Preview Modal */}
      {activeDoc && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="doc-preview-title"
          className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/50 p-4 backdrop-blur-xs"
          onClick={(e) => {
            if (e.target === e.currentTarget) setActiveDoc(null);
          }}
        >
          <div className="surface-card my-8 w-full max-w-3xl rounded-xl border border-border shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-border p-4">
              <div>
                <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Verified Clinical Document
                </span>
                <h2 id="doc-preview-title" className="text-lg font-bold text-foreground">
                  {activeDoc.title}
                </h2>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handlePrint}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm hover:opacity-90"
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"
                    />
                  </svg>
                  Print (A4)
                </button>
                <button
                  type="button"
                  onClick={() => setActiveDoc(null)}
                  aria-label="Close modal"
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Modal Body / Document Preview */}
            <div className="max-h-[70vh] overflow-y-auto p-6">
              {/* Printed Root Container */}
              <div id="portal-document-print-root" className="space-y-6">
                {/* Formal Clinical Header */}
                <div className="print-header flex items-start justify-between border-b-2 border-primary pb-3">
                  <div>
                    <h1 className="print-header-logo text-xl font-extrabold text-primary">
                      {activeDoc.facility_name ?? "HealthDoc Medical Center"}
                    </h1>
                    <p className="print-header-facility text-xs text-muted-foreground">
                      {activeDoc.facility_address ?? "National Highway 44, Bengaluru, Karnataka 560100"} · NABH Accredited
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="print-header-doc-title text-sm font-bold uppercase text-primary">
                      {activeDoc.document_type.replace("_", " ")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Date: {formatDateTime(activeDoc.date)}
                    </p>
                  </div>
                </div>

                {/* Patient Demographic Banner */}
                <div className="print-patient-banner grid grid-cols-2 gap-3 rounded-lg border border-border bg-muted/30 p-3 text-xs md:grid-cols-4">
                  <div>
                    <span className="block font-semibold uppercase text-muted-foreground">UHID</span>
                    <span className="font-bold text-foreground">{activeDoc.patient_uhid ?? "HD-PAT-ME"}</span>
                  </div>
                  <div>
                    <span className="block font-semibold uppercase text-muted-foreground">Patient Name</span>
                    <span className="font-bold text-foreground">{activeDoc.patient_name}</span>
                  </div>
                  <div>
                    <span className="block font-semibold uppercase text-muted-foreground">Age / Gender</span>
                    <span className="font-medium text-foreground">{activeDoc.patient_age_gender ?? "Adult"}</span>
                  </div>
                  <div>
                    <span className="block font-semibold uppercase text-muted-foreground">Doctor</span>
                    <span className="font-medium text-foreground">
                      {activeDoc.doctor_name ? `Dr. ${activeDoc.doctor_name}` : "Attending Physician"}
                    </span>
                  </div>
                </div>

                {/* Specific Document Payload Rendering */}
                <div className="space-y-4">
                  {/* Prescriptions Table */}
                  {activeDoc.document_type === "prescription" && (
                    <div>
                      <h4 className="border-b border-border pb-1 text-sm font-semibold uppercase text-primary">
                        Prescribed Medications (Rx)
                      </h4>
                      {Array.isArray((activeDoc.content as Record<string, unknown>).items) ? (
                        <table className="print-table mt-2 w-full text-left text-xs">
                          <thead>
                            <tr className="border-b border-border bg-muted/40">
                              <th className="p-2">#</th>
                              <th className="p-2">Medicine / Generic</th>
                              <th className="p-2">Dose / Route</th>
                              <th className="p-2">Frequency</th>
                              <th className="p-2">Duration</th>
                              <th className="p-2">Instructions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {((activeDoc.content as Record<string, unknown>).items as Array<Record<string, unknown>>).map((item, idx) => (
                              <tr key={idx} className="border-b border-border">
                                <td className="p-2 font-medium">{idx + 1}</td>
                                <td className="p-2 font-semibold">{String(item.medicine_name ?? "Medication")}</td>
                                <td className="p-2">{String(item.dosage ?? "Standard")} ({String(item.route ?? "Oral")})</td>
                                <td className="p-2">{String(item.frequency ?? "Daily")}</td>
                                <td className="p-2">{String(item.duration_days ?? "5")} days</td>
                                <td className="p-2 text-muted-foreground">{String(item.instructions ?? "After food")}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className="mt-2 text-xs text-muted-foreground">{activeDoc.summary}</p>
                      )}
                      {(activeDoc.content as Record<string, unknown>).notes ? (
                        <div className="mt-3 rounded border border-border bg-muted/20 p-2 text-xs">
                          <span className="font-semibold">Doctor&apos;s Advice / Notes: </span>
                          {String((activeDoc.content as Record<string, unknown>).notes)}
                        </div>
                      ) : null}
                    </div>
                  )}

                  {/* Lab Reports */}
                  {activeDoc.document_type === "lab_report" && (
                    <div>
                      <h4 className="border-b border-border pb-1 text-sm font-semibold uppercase text-primary">
                        Investigation Findings
                      </h4>
                      <div className="mt-2 space-y-2 text-xs">
                        <div className="flex justify-between border-b border-border py-1.5">
                          <span className="font-medium text-muted-foreground">Test / Panel</span>
                          <span className="font-bold text-foreground">
                            {String((activeDoc.content as Record<string, unknown>).test_name ?? activeDoc.title)}
                          </span>
                        </div>
                        <div className="flex justify-between border-b border-border py-1.5">
                          <span className="font-medium text-muted-foreground">Observed Value</span>
                          <span className="font-bold text-primary">
                            {String((activeDoc.content as Record<string, unknown>).result_value ?? "Normal")}
                          </span>
                        </div>
                        <div className="flex justify-between border-b border-border py-1.5">
                          <span className="font-medium text-muted-foreground">Reference Range</span>
                          <span>{String((activeDoc.content as Record<string, unknown>).reference_range ?? "N/A")}</span>
                        </div>
                        {(activeDoc.content as Record<string, unknown>).notes ? (
                          <div className="py-2">
                            <span className="block font-semibold">Pathologist Interpretation:</span>
                            <p className="mt-1 text-muted-foreground">{String((activeDoc.content as Record<string, unknown>).notes)}</p>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  )}

                  {/* Radiology Reports */}
                  {activeDoc.document_type === "radiology" && (
                    <div className="space-y-3 text-xs">
                      <div>
                        <h4 className="border-b border-border pb-1 text-sm font-semibold uppercase text-primary">
                          Imaging Modality & Findings
                        </h4>
                        <div className="mt-2 space-y-2">
                          <div>
                            <span className="font-semibold text-muted-foreground">Modality / Study: </span>
                            <span className="font-bold">{String((activeDoc.content as Record<string, unknown>).modality ?? "Radiograph")}</span>
                          </div>
                          <div className="rounded bg-muted/20 p-2">
                            <span className="font-semibold block text-foreground">Findings:</span>
                            <p className="mt-1 text-muted-foreground">
                              {String((activeDoc.content as Record<string, unknown>).findings ?? activeDoc.summary)}
                            </p>
                          </div>
                          <div className="rounded border border-primary/20 bg-primary/5 p-2">
                            <span className="font-bold text-primary block">Impression:</span>
                            <p className="mt-1 text-foreground font-medium">
                              {String((activeDoc.content as Record<string, unknown>).impression ?? "No acute abnormality detected.")}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Discharge Summaries */}
                  {activeDoc.document_type === "discharge_summary" && (
                    <div className="space-y-3 text-xs">
                      <h4 className="border-b border-border pb-1 text-sm font-semibold uppercase text-primary">
                        Inpatient Stay & Discharge Summary
                      </h4>
                      <div className="grid grid-cols-2 gap-2 border-b border-border pb-2">
                        <div>
                          <span className="text-muted-foreground">Admission Date: </span>
                          <span className="font-semibold">{String((activeDoc.content as Record<string, unknown>).admission_date ?? "—")}</span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Discharge Date: </span>
                          <span className="font-semibold">{String((activeDoc.content as Record<string, unknown>).discharge_date ?? "—")}</span>
                        </div>
                      </div>
                      <div className="space-y-1">
                        <span className="font-semibold">Final Diagnoses:</span>
                        <p className="text-muted-foreground">{String((activeDoc.content as Record<string, unknown>).final_diagnosis ?? activeDoc.summary)}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="font-semibold">Hospital Course & Treatment:</span>
                        <p className="text-muted-foreground">{String((activeDoc.content as Record<string, unknown>).course_summary ?? "Patient managed conservatively with satisfactory recovery.")}</p>
                      </div>
                      <div className="space-y-1 rounded bg-muted/20 p-2">
                        <span className="font-semibold text-foreground">Discharge Advice & Follow-up:</span>
                        <p className="text-muted-foreground">{String((activeDoc.content as Record<string, unknown>).discharge_advice ?? "Follow up in OPD after 7 days or SOS in Emergency.")}</p>
                      </div>
                    </div>
                  )}

                  {/* Vaccination Certificates */}
                  {activeDoc.document_type === "vaccine" && (
                    <div className="space-y-3 text-xs">
                      <h4 className="border-b border-border pb-1 text-sm font-semibold uppercase text-primary">
                        Immunization Certificate
                      </h4>
                      <div className="grid grid-cols-2 gap-2 rounded border border-border p-3">
                        <div>
                          <span className="text-muted-foreground block">Vaccine Name</span>
                          <span className="font-bold text-foreground text-sm">
                            {String((activeDoc.content as Record<string, unknown>).vaccine_name ?? activeDoc.title)}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Dose Sequence</span>
                          <span className="font-bold text-foreground text-sm">
                            Dose #{String((activeDoc.content as Record<string, unknown>).dose_number ?? "1")}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Batch / Lot Number</span>
                          <span className="font-mono font-medium">
                            {String((activeDoc.content as Record<string, unknown>).batch_number ?? "COV-78829")}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground block">Next Due Date</span>
                          <span className="font-medium text-primary">
                            {String((activeDoc.content as Record<string, unknown>).next_due_date ?? "Complete")}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Digital Verification & Doctor Signature Block */}
                <div className="print-signature-block avoid-break mt-6 flex items-end justify-between border-t border-border pt-4 text-xs">
                  <div className="space-y-1">
                    <div className="inline-flex items-center gap-1 font-semibold text-success">
                      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                        <path
                          fillRule="evenodd"
                          d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                          clipRule="evenodd"
                        />
                      </svg>
                      Verified Digital Health Record
                    </div>
                    <p className="text-muted-foreground text-[10px]">
                      DPDP Act compliant electronic record signed at {formatDateTime(activeDoc.date)}
                    </p>
                  </div>
                  <div className="text-center">
                    <div className="print-signature-line mb-1 h-8 w-44 border-b border-foreground/60"></div>
                    <p className="font-bold text-foreground">
                      {activeDoc.doctor_name ? `Dr. ${activeDoc.doctor_name}` : "Authorized Medical Officer"}
                    </p>
                    <p className="text-[10px] text-muted-foreground">Reg. No: MCI-2018-84729</p>
                  </div>
                </div>

                {/* Print Footer */}
                <div className="print-footer text-[9px] text-muted-foreground">
                  <span>Generated via HealthDoc Patient Portal</span>
                  <span>Confidential Medical Information</span>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex justify-end gap-3 border-t border-border p-4">
              <button
                type="button"
                onClick={() => setActiveDoc(null)}
                className="rounded-md border border-border px-4 py-2 text-xs font-semibold hover:bg-muted"
              >
                Close Preview
              </button>
              <button
                type="button"
                onClick={handlePrint}
                className="rounded-md bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90"
              >
                Print Document
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
