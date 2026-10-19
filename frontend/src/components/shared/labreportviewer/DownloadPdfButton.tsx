"use client";

import { Printer } from "lucide-react";
import { useLocale } from "@/lib/i18n";

interface DownloadPdfButtonProps {
  reportNumber: string;
}

export default function DownloadPdfButton({
  reportNumber,
}: DownloadPdfButtonProps) {
  const { t } = useLocale();
  return (
    <button
      type="button"
      onClick={() => window.print()}
      aria-label={`Print or save pathology report ${reportNumber} as PDF`}
      className="report-download-btn inline-flex items-center gap-2 rounded-xl bg-[#001f54] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_12px_28px_rgba(0,31,84,0.28)] transition hover:-translate-y-0.5 hover:bg-[#003070] hover:shadow-[0_16px_36px_rgba(0,31,84,0.34)]"
    >
      <Printer className="h-4 w-4" />{t("common.ui.printSavePdf")}</button>
  );
}
