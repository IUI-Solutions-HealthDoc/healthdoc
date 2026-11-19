"use client";
import { useLocale } from "@/lib/i18n";

interface Doctor {
  doctorId: string;
  name: string;
  qualification: string;
  department: string;
  registrationNumber: string;
  hospital: string;
}

interface DoctorCardProps {
  doctor: Doctor;
}

export default function DoctorCard({ doctor }: DoctorCardProps) {
  const { t } = useLocale();
  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.referringClinician")}</h3>
      </div>

      <div className="grid grid-cols-2 text-[12px]">
        <MetaCell label={t("common.doctor")} value={doctor.name} className="col-span-2" />
        <MetaCell label={t("common.ui.qualification")} value={doctor.qualification} muted />
        <MetaCell label={t("monitor.department")} value={doctor.department} />
        <MetaCell label={t("common.ui.regNo")} value={doctor.registrationNumber} muted />
        <MetaCell label={t("monitor.colFacility")} value={doctor.hospital} />
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
      className={`border-b border-r border-slate-100 px-3.5 py-2 ${
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
