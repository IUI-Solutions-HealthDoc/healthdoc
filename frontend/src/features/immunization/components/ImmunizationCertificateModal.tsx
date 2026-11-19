"use client";

import { CheckCircle2, Printer, ShieldCheck, X } from "lucide-react";
import type { ImmunizationCertificate } from "../types";
import { useLocale } from "@/lib/i18n";

interface ImmunizationCertificateModalProps {
  isOpen: boolean;
  onClose: () => void;
  certificate: ImmunizationCertificate | null;
}

export function ImmunizationCertificateModal({
  isOpen,
  onClose,
  certificate,
}: ImmunizationCertificateModalProps) {
  const { t } = useLocale();
  if (!isOpen || !certificate) return null;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 print:p-0 print:bg-white print:static">
      <div className="w-full max-w-2xl rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200 print:shadow-none print:border-none print:max-w-none">
        <div className="flex items-center justify-between pb-4 border-b border-border print:hidden">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <h3 className="text-lg font-bold text-card-foreground">{t("immunization.ui.immunizationRecord")}</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrint}
              className="flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 transition-colors"
            >
              <Printer className="h-4 w-4" />{t("common.ui.print")}</button>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Certificate Printable Canvas */}
        <div className="mt-6 rounded-xl border border-border/80 bg-background/50 p-6 space-y-6">
          {/* Header */}
          <div className="text-center border-b border-border pb-4">
            <div className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary mb-2">
              <CheckCircle2 className="h-3.5 w-3.5" />{t("immunization.ui.recordedAdministrations")}</div>
            <h2 className="text-xl font-bold tracking-tight text-foreground">{certificate.facility_name}</h2>
            <p className="text-xs text-muted-foreground">{t("immunization.ui.facilityImmunizationRecord")}</p>
            <p className="text-[11px] text-muted-foreground/80 mt-1 font-mono">{t("immunization.ui.certificateNoCertificateIdIssuedValue", { certificate_id: certificate.certificate_id, value: new Date(certificate.generated_at).toLocaleString() })}</p>
          </div>

          {/* Beneficiary Details */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 rounded-lg bg-muted/40 text-xs">
            <div>
              <span className="text-muted-foreground font-medium block">{t("common.ui.patientName")}</span>
              <span className="font-semibold text-foreground">{certificate.patient_name}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">{t("immunization.ui.patientRecordId")}</span>
              <span className="font-mono font-semibold text-foreground">{certificate.patient_id}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">{t("common.ui.dateOfBirth")}</span>
              <span className="font-semibold text-foreground">{certificate.dob || t("receptionist.scanShare.notRecorded")}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">{t("admin.ui.gender")}</span>
              <span className="font-semibold capitalize text-foreground">{certificate.gender || t("receptionist.scanShare.notRecorded")}</span>
            </div>
          </div>

          {/* Vaccination Table */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">{t("immunization.ui.vaccinationAdministrationHistory")}</h4>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/60 text-muted-foreground font-semibold">
                  <tr>
                    <th className="p-2.5">{t("immunization.record.vaccine")}</th>
                    <th className="p-2.5">{t("immunization.ui.dose")}</th>
                    <th className="p-2.5">{t("common.date")}</th>
                    <th className="p-2.5">{t("immunization.ui.batchLot")}</th>
                    <th className="p-2.5">{t("immunization.record.manufacturer")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {certificate.records.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="p-4 text-center text-muted-foreground">{t("immunization.ui.noImmunizationRecordsFoundForThis")}</td>
                    </tr>
                  ) : (
                    certificate.records.map((v, idx) => (
                      <tr key={idx} className="hover:bg-muted/30">
                        <td className="p-2.5 font-medium text-foreground">
                          <span className="text-muted-foreground text-[10px]">({v.vaccine_code})</span>
                        </td>
                        <td className="p-2.5">{t("immunization.ui.doseDoseNumber", { dose_number: v.dose_number })}</td>
                        <td className="p-2.5 font-mono">{new Date(v.administered_at).toLocaleString()}</td>
                        <td className="p-2.5 font-mono">{v.batch_number}</td>
                        <td className="p-2.5 text-muted-foreground">{v.manufacturer || t("receptionist.scanShare.notRecorded")}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">{t("immunization.ui.generatedFromFacilityRecordsThisDocument")}</p>
        </div>
      </div>
    </div>
  );
}
