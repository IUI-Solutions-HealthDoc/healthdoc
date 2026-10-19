"use client";

import { Mail, Phone } from "lucide-react";
import StripeBar from "./StripeBar";
import { useLocale } from "@/lib/i18n";

interface Laboratory {
  name: string;
  nablNumber?: string;
  address: string;
  phone: string;
  phoneSecondary?: string;
  email: string;
  website: string;
  logo: string;
  tagline?: string;
}

interface ReportHeaderProps {
  laboratory: Laboratory;
}

export default function ReportHeader({ laboratory }: ReportHeaderProps) {
  const { t } = useLocale();
  return (
    <header className="drlogy-header">
      <div className="flex items-start justify-between gap-4 px-1 pt-1">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className="relative h-[68px] w-[68px] shrink-0 overflow-hidden rounded-full border-[3px] border-[#0b2f6b] bg-white">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={laboratory.logo}
              alt={laboratory.name}
              width={68}
              height={68}
              className="h-full w-full object-cover"
            />
          </div>

          <div className="min-w-0 pt-0.5">
            <h1 className="text-[22px] font-extrabold uppercase leading-none tracking-wide text-[#0b2f6b]">
              {laboratory.name}
            </h1>
            {laboratory.tagline && (
              <p className="mt-1.5 text-[11px] font-medium tracking-wide text-slate-600">
                {laboratory.tagline.split("|").map((part, index, arr) => (
                  <span key={part}>
                    <span className="inline-flex items-center gap-1">
                      {index === 0 && "✔ "}
                      {index === 1 && "❤ "}
                      {index === 2 && "⚡ "}
                      {part.trim()}
                    </span>
                    {index < arr.length - 1 ? (
                      <span className="mx-1.5 text-slate-300">|</span>
                    ) : null}
                  </span>
                ))}
              </p>
            )}
            <p className="mt-2 text-[11px] leading-4 text-slate-600">
              {laboratory.address}
            </p>
            {laboratory.nablNumber && (
              <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-[#0b5cab]">{t("common.ui.nablAccreditedNablnumber", { nablNumber: laboratory.nablNumber })}</p>
            )}
          </div>
        </div>

        <div className="shrink-0 space-y-1.5 pt-1 text-right text-[12px] text-slate-700">
          <p className="flex items-center justify-end gap-1.5 font-semibold">
            <Phone className="h-3.5 w-3.5 text-emerald-600" />
            {laboratory.phone}
          </p>
          {laboratory.phoneSecondary && (
            <p className="flex items-center justify-end gap-1.5 font-semibold">
              <Phone className="h-3.5 w-3.5 text-emerald-600" />
              {laboratory.phoneSecondary}
            </p>
          )}
          <p className="flex items-center justify-end gap-1.5">
            <Mail className="h-3.5 w-3.5 text-orange-500" />
            <span className="font-medium text-[#0b2f6b]">{laboratory.email}</span>
          </p>
        </div>
      </div>

      <StripeBar
        rightLabel={laboratory.website}
        className="mt-3"
      />
    </header>
  );
}
