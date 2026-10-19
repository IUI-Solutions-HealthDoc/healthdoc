"use client";

import Image from "next/image";
import { formatDateTime } from "./utils";
import { useLocale } from "@/lib/i18n";

interface Verification {
  verifiedBy: string;
  qualification: string;
  designation: string;
  registrationNumber: string;
  verifiedAt: string;
  digitalSignature: string;
  digitallySigned: boolean;
}

interface VerificationProps {
  verification: Verification;
}

export default function Verification({ verification }: VerificationProps) {
  const { t } = useLocale();
  return (
    <section className="report-panel overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div className="border-b border-white/10 bg-gradient-to-r from-[#001f54] to-[#0a2f6b] px-3.5 py-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white">{t("common.ui.authorizedSignatory")}</h3>
      </div>

      <div className="flex items-end justify-between gap-6 px-4 py-5">
        <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 text-[12px]">
          <Field label={t("common.ui.verifiedBy")} value={verification.verifiedBy} />
          <Field label={t("common.ui.designation")} value={verification.designation} />
          <Field label={t("common.ui.qualification")} value={verification.qualification} />
          <Field
            label={t("common.ui.registrationNo")}
            value={verification.registrationNumber}
          />
          <Field
            label={t("common.ui.verifiedAt")}
            value={formatDateTime(verification.verifiedAt)}
          />
        </div>

        <div className="flex w-48 flex-col items-center rounded-xl border border-slate-100 bg-[#f8fafc] px-3 py-3">
          <div className="h-16 w-40 shrink-0">
            <Image
              src={verification.digitalSignature}
              alt={`${verification.verifiedBy} signature`}
              width={160}
              height={64}
              priority
              className="h-full w-full object-contain"
            />
          </div>
          <div className="mt-2 w-full border-t border-slate-300 pt-2 text-center">
            <p className="report-display-title text-[13px] font-semibold text-[#001f54]">
              {verification.verifiedBy}
            </p>
            <p className="text-[10px] text-slate-500">
              {verification.designation}
            </p>
          </div>
          {verification.digitallySigned && (
            <span className="mt-2 rounded-full bg-emerald-100 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-800">{t("common.ui.digitallyVerified")}</span>
          )}
        </div>
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 font-semibold text-slate-900">{value}</p>
    </div>
  );
}
