"use client";

import { formatDate } from "./utils";
import { useLocale } from "@/lib/i18n";

interface Patient {
  patientId: string;
  uhid: string;
  name: string;
  age: number;
  gender: string;
  dob: string;
  mobile: string;
}

interface PatientCardProps {
  patient: Patient;
}

export default function PatientCard({ patient }: PatientCardProps) {
  const { t } = useLocale();
  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.patientParticulars")}</h3>
      </div>

      <div className="border-b border-slate-100 bg-[#f5f8fc] px-3.5 py-2.5">
        <p className="text-[10px] uppercase tracking-wide text-slate-400">{t("common.ui.patientName")}</p>
        <p className="report-display-title text-[16px] font-semibold text-[#001f54]">
          {patient.name}
        </p>
      </div>

      <div className="grid grid-cols-2 text-[12px]">
        <MetaCell label={t("field.uhid")} value={patient.uhid} />
        <MetaCell label={t("supervisor.merge.patientId")} value={patient.patientId} muted />
        <MetaCell
          label={t("doctor.summaryAgeSex")}
          value={`${patient.age} Y / ${patient.gender}`}
          muted
        />
        <MetaCell label={t("common.ui.dateOfBirth")} value={formatDate(patient.dob)} />
        <MetaCell
          label={t("field.mobile")}
          value={patient.mobile}
          className="col-span-2"
          muted
        />
      </div>
    </section>
  );
}

function MetaCell({
  label,
  value,
  muted,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  muted?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`border-b border-r border-slate-100 px-3.5 py-2 last:border-b-0 ${
        muted ? "bg-slate-50/70" : "bg-white"
      } ${className}`}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 font-semibold text-slate-900">{value}</p>
    </div>
  );
}
