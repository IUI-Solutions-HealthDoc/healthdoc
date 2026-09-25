"use client";

import { useEffect, useRef } from "react";
import QRCode from "react-qr-code";
import Barcode from "react-barcode";
import { Printer, AlertTriangle } from "lucide-react";

import { Modal } from "@/components/ui/Modal";
import { PatientAvatar } from "@/components/ui/PatientAvatar";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { useLocale } from "@/lib/i18n";
import { deriveAgeFromDob } from "./patientValidation";

import "./patient-card-print.css";

export interface PatientCardData {
  id: string;
  full_name: string;
  uhid?: string | null;
  thid?: string | null;
  sex: string;
  age_years?: number | null;
  dob?: string | null;
  photo_file_id?: string | null;
}

interface PatientCardModalProps {
  open: boolean;
  onClose: () => void;
  patient: PatientCardData;
}

export function PatientCardModal({ open, onClose, patient }: PatientCardModalProps) {
  const { user: currentUser } = useCurrentUser();
  const { localizeField } = useLocale();
  const printButtonRef = useRef<HTMLButtonElement>(null);

  const identifier = patient.uhid || patient.thid || "";
  const isEmergencyThid = Boolean(patient.thid && !patient.uhid);
  const facilityName = localizeField(
    currentUser?.facility?.name || "HealthDoc Hospital",
    currentUser?.facility?.name_hi,
  );

  const derivedAge = patient.dob ? deriveAgeFromDob(patient.dob)?.displayText : null;
  const ageDisplay = derivedAge || (patient.age_years !== null && patient.age_years !== undefined ? `${patient.age_years}y` : "");

  useEffect(() => {
    if (open) {
      // Focus the print button for rapid keyboard operation
      setTimeout(() => printButtonRef.current?.focus(), 100);
    }
  }, [open]);

  const handlePrint = () => {
    window.print();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Patient Identity Card"
      size="md"
      actions={
        <div className="flex items-center justify-end gap-3 no-print">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-muted"
          >
            Close
          </button>
          <button
            ref={printButtonRef}
            type="button"
            onClick={handlePrint}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-white shadow hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <Printer size={16} />
            Print Card
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* The Card View — Printable Root */}
        <div
          id="patient-card-print-root"
          className={`relative overflow-hidden rounded-xl border-2 bg-gradient-to-br from-white to-slate-50 p-5 shadow-sm ${
            isEmergencyThid ? "border-amber-400" : "border-primary/40"
          }`}
        >
          {/* Top header: Facility details */}
          <div className="flex items-center justify-between border-b pb-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-primary">
                {facilityName}
              </p>
              <p className="text-[10px] text-muted-foreground">Patient Identification Card</p>
            </div>
            {isEmergencyThid ? (
              <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-900">
                <AlertTriangle size={12} />
                PROVISIONAL THID
              </span>
            ) : (
              <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                OFFICIAL ID
              </span>
            )}
          </div>

          {isEmergencyThid && (
            <div className="mt-2 rounded bg-amber-50 p-2 text-left text-[11px] text-amber-800 border border-amber-200">
              <strong>Emergency Record:</strong> Temporary identifier. Must be merged into canonical UHID after patient stabilization and verification.
            </div>
          )}

          {/* Main Card Body */}
          <div className="mt-4 flex gap-4">
            <div className="shrink-0">
              <PatientAvatar
                patientId={patient.id}
                photoFileId={patient.photo_file_id}
                name={patient.full_name}
                size="lg"
              />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-lg font-bold text-foreground">{patient.full_name}</p>
              <p className="text-xs text-muted-foreground capitalize">
                {patient.sex} {ageDisplay ? ` · ${ageDisplay}` : ""}
                {patient.dob ? ` (DOB: ${patient.dob})` : ""}
              </p>
              <p className="mt-2 font-mono text-sm font-extrabold tracking-wide text-foreground">
                {identifier}
              </p>
            </div>
            <div className="shrink-0 flex items-center justify-center p-1 bg-white rounded border border-border/60">
              <QRCode value={identifier} size={68} />
            </div>
          </div>

          {/* Barcode encoding ONLY the local identifier */}
          <div className="mt-4 flex flex-col items-center justify-center border-t pt-3">
            {identifier && (
              <div className="overflow-hidden">
                <Barcode
                  value={identifier}
                  format="CODE128"
                  width={1.3}
                  height={36}
                  displayValue={false}
                  margin={0}
                />
              </div>
            )}
            <p className="mt-1 text-[10px] font-mono text-muted-foreground">{identifier}</p>
          </div>

          {/* Card footer */}
          <div className="mt-3 flex items-center justify-between text-[9px] text-muted-foreground border-t pt-2">
            <span>Non-transferable medical identity card</span>
            <span>Issued: {new Date().toLocaleDateString("en-IN")}</span>
          </div>
        </div>

        <p className="text-xs text-muted-foreground text-center no-print">
          Card encodes strictly the approved local identifier ({identifier}). No Aadhaar, ABHA, phone, or clinical details are encoded.
        </p>
      </div>
    </Modal>
  );
}
