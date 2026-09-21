"use client";

import { CheckCircle2, Printer, ShieldCheck, X } from "lucide-react";
import type { ImmunizationCertificate } from "../types";

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
            <h3 className="text-lg font-bold text-card-foreground">Immunization Record</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrint}
              className="flex items-center gap-1.5 rounded-lg bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 transition-colors"
            >
              <Printer className="h-4 w-4" />
              Print
            </button>
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
              <CheckCircle2 className="h-3.5 w-3.5" />
              Recorded Administrations
            </div>
            <h2 className="text-xl font-bold tracking-tight text-foreground">{certificate.facility_name}</h2>
            <p className="text-xs text-muted-foreground">Facility immunization record</p>
            <p className="text-[11px] text-muted-foreground/80 mt-1 font-mono">
              Certificate No: {certificate.certificate_id} • Issued: {new Date(certificate.generated_at).toLocaleString()}
            </p>
          </div>

          {/* Beneficiary Details */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 rounded-lg bg-muted/40 text-xs">
            <div>
              <span className="text-muted-foreground font-medium block">Patient Name</span>
              <span className="font-semibold text-foreground">{certificate.patient_name}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">Patient record ID</span>
              <span className="font-mono font-semibold text-foreground">{certificate.patient_id}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">Date of Birth</span>
              <span className="font-semibold text-foreground">{certificate.dob || "Not recorded"}</span>
            </div>
            <div>
              <span className="text-muted-foreground font-medium block">Gender</span>
              <span className="font-semibold capitalize text-foreground">{certificate.gender || "Not recorded"}</span>
            </div>
          </div>

          {/* Vaccination Table */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
              Vaccination Administration History
            </h4>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/60 text-muted-foreground font-semibold">
                  <tr>
                    <th className="p-2.5">Vaccine</th>
                    <th className="p-2.5">Dose</th>
                    <th className="p-2.5">Date</th>
                    <th className="p-2.5">Batch / Lot</th>
                    <th className="p-2.5">Manufacturer</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {certificate.records.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="p-4 text-center text-muted-foreground">
                        No immunization records found for this patient.
                      </td>
                    </tr>
                  ) : (
                    certificate.records.map((v, idx) => (
                      <tr key={idx} className="hover:bg-muted/30">
                        <td className="p-2.5 font-medium text-foreground">
                          <span className="text-muted-foreground text-[10px]">({v.vaccine_code})</span>
                        </td>
                        <td className="p-2.5">Dose {v.dose_number}</td>
                        <td className="p-2.5 font-mono">{new Date(v.administered_at).toLocaleString()}</td>
                        <td className="p-2.5 font-mono">{v.batch_number}</td>
                        <td className="p-2.5 text-muted-foreground">{v.manufacturer || "Not recorded"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">Generated from facility records. This document is not digitally signed.</p>
        </div>
      </div>
    </div>
  );
}
