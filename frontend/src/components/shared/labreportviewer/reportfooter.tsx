"use client";

import Image from "next/image";
import { MessageCircle } from "lucide-react";
import StripeBar from "./StripeBar";
import { formatDateTime } from "./utils";
import { useLocale } from "@/lib/i18n";

interface Signatory {
  name: string;
  qualification: string;
  designation: string;
  signature: string;
}

interface ReportFooterProps {
  footer: {
    generatedAt: string;
    whatsapp?: string;
  };
  signatories: Signatory[];
}

export default function ReportFooter({
  footer,
  signatories,
}: ReportFooterProps) {
  const { t } = useLocale();
  return (
    <footer className="drlogy-footer mt-4">
      <div className="grid grid-cols-3 gap-4 border-t border-slate-300 px-1 pb-4 pt-5">
        {signatories.map((person) => (
          <div key={person.name} className="flex flex-col items-center text-center">
            <div className="mb-1 h-12 w-36">
              <Image
                src={person.signature}
                alt={`${person.name} signature`}
                width={144}
                height={48}
                className="h-full w-full object-contain"
              />
            </div>
            <p className="text-[12px] font-bold text-slate-900">{person.name}</p>
            <p className="text-[11px] text-slate-600">{person.qualification}</p>
            <p className="text-[10px] text-slate-500">{person.designation}</p>
          </div>
        ))}
      </div>

      <div className="mb-2 flex items-center justify-between px-1 text-[11px] text-slate-600">
        <span>
          <span className="font-semibold text-slate-800">{t("common.ui.generatedOn")}</span>{" "}
          {formatDateTime(footer.generatedAt)}
        </span>
      </div>

      <div className="relative overflow-hidden">
        <StripeBar />
        <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
          <span className="rounded bg-white/95 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#0b2f6b]">{t("common.ui.sampleCollection")}</span>
        </div>
        {footer.whatsapp && (
          <div className="absolute inset-y-0 right-3 flex items-center gap-1.5 text-white">
            <MessageCircle className="h-4 w-4 fill-white text-white" />
            <span className="text-[12px] font-bold">{footer.whatsapp}</span>
          </div>
        )}
      </div>
    </footer>
  );
}
