"use client";
import { useLocale, translate } from "@/lib/i18n";

interface Remarks {
  interpretation?: string;
  comments?: string;
  advice?: string;
}

interface RemarksProps {
  remarks: Remarks;
}

export default function Remarks({ remarks }: RemarksProps) {
  const { t } = useLocale();
  const blocks = [
    { title: translate("common.msg.interpretation"), content: remarks.interpretation },
    { title: translate("common.msg.comments"), content: remarks.comments },
    { title: translate("common.msg.advice"), content: remarks.advice },
  ].filter((block) => Boolean(block.content));

  if (blocks.length === 0) return null;

  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.clinicalRemarks")}</h3>
      </div>

      <div className="divide-y divide-slate-100 text-[12px]">
        {blocks.map((block) => (
          <div
            key={block.title}
            className="grid grid-cols-[140px_1fr] gap-3 px-3.5 py-3"
          >
            <p className="font-semibold uppercase tracking-wide text-slate-400">
              {block.title}
            </p>
            <p className="leading-5 text-slate-700">{block.content}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
