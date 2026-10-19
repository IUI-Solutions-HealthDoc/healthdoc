"use client";

import { formatDateTime } from "./utils";
import { useLocale } from "@/lib/i18n";

interface ReportInfo {
  reportId: string;
  reportNumber: string;
  title: string;
  category: string;
  method: string;
  reportedAt: string;
  verifiedAt: string;
}

interface ReportInfoCardProps {
  report: ReportInfo;
  status: "DRAFT" | "IN_PROGRESS" | "VERIFIED" | "FINAL";
}

const statusClasses = {
  DRAFT: "bg-slate-100 text-slate-700",
  IN_PROGRESS: "bg-amber-100 text-amber-800",
  VERIFIED: "bg-emerald-100 text-emerald-800",
  FINAL: "bg-emerald-100 text-emerald-800",
};

export default function ReportInfoCard({
  report,
  status,
}: ReportInfoCardProps) {
  const { t } = useLocale();
  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.reportInformation")}</h3>
      </div>

      <div className="grid grid-cols-2 text-[12px]">
        <MetaCell label={t("common.ui.reportNo")} value={report.reportNumber} />
        <MetaCell label={t("common.ui.reportId")} value={report.reportId} muted />
        <MetaCell label={t("monitor.department")} value={report.category} muted />
        <MetaCell label={t("common.ui.method")} value={report.method} />
        <MetaCell label={t("common.ui.reportedAt")} value={formatDateTime(report.reportedAt)} />
        <MetaCell
          label={t("common.ui.verifiedAt")}
          value={formatDateTime(report.verifiedAt)}
          muted
        />
        <div className="col-span-2 flex items-center justify-between border-b border-slate-100 bg-white px-3.5 py-2.5">
          <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{t("common.ui.reportStatus")}</span>
          <span
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${statusClasses[status]}`}
          >
            {status.replaceAll("_", " ")}
          </span>
        </div>
      </div>
    </section>
  );
}

function MetaCell({
  label,
  value,
  muted,
}: {
  label: string;
  value: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div
      className={`border-b border-r border-slate-100 px-3.5 py-2 ${
        muted ? "bg-slate-50/70" : "bg-white"
      }`}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 font-semibold text-slate-900">{value}</p>
    </div>
  );
}
