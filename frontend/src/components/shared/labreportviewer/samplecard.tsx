"use client";

import { formatDateTime } from "./utils";
import { useLocale } from "@/lib/i18n";

interface Sample {
  accessionNumber: string;
  sampleId: string;
  barcode: string;
  sampleType: string;
  container: string;
  collectedAt: string;
  receivedAt: string;
  processedAt: string;
}

interface SampleCardProps {
  sample: Sample;
}

export default function SampleCard({ sample }: SampleCardProps) {
  const { t } = useLocale();
  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.specimenDetails")}</h3>
      </div>

      <div className="grid grid-cols-2 text-[12px]">
        <MetaCell label={t("common.ui.accessionNo")} value={sample.accessionNumber} />
        <MetaCell label={t("common.ui.sampleId")} value={sample.sampleId} muted />
        <MetaCell label={t("lab.col.barcode")} value={sample.barcode} muted />
        <MetaCell label={t("lab.col.specimen")} value={sample.sampleType} />
        <MetaCell label={t("common.ui.container")} value={sample.container} />
        <MetaCell
          label={t("reports.billingMis.col.collected")}
          value={formatDateTime(sample.collectedAt)}
          muted
        />
        <MetaCell
          label={t("common.ui.received")}
          value={formatDateTime(sample.receivedAt)}
          muted
        />
        <MetaCell label={t("common.ui.processed")} value={formatDateTime(sample.processedAt)} />
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
      <p className="mt-0.5 break-all font-semibold text-slate-900">{value}</p>
    </div>
  );
}
