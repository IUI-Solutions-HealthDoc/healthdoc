"use client";

import QRCode from "react-qr-code";
import BarcodeDisplay from "@/components/shared/BarcodeDisplay";
import { formatDateTime } from "./utils";
import { useLocale } from "@/lib/i18n";

interface PatientMetaProps {
  patient: {
    patientId: string;
    name: string;
    age: number;
    gender: string;
  };
  doctor: {
    name: string;
  };
  sample: {
    barcode: string;
    collectedAt: string;
    collectedAtLocation?: string;
    receivedAt: string;
  };
  reportInfo: {
    reportNumber: string;
    reportedAt: string;
  };
  order: {
    orderedAt: string;
  };
  qrValue: string;
  labAddress: string;
}

export default function PatientMeta({
  patient,
  doctor,
  sample,
  reportInfo,
  order,
  qrValue,
  labAddress,
}: PatientMetaProps) {
  const { t } = useLocale();
  return (
    <section className="drlogy-patient-meta grid grid-cols-[1.15fr_1.2fr_0.95fr] gap-0 border-b border-slate-300 py-3 text-[12px]">
      <div className="flex gap-3 border-r border-slate-300 pr-3">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-[15px] font-bold text-slate-900">{patient.name}</p>
          <p className="text-slate-700">{t("common.ui.age")}{" "}{patient.age}{" "}{t("common.ui.years")}{" "}
            <span className="mx-1 text-slate-300">|</span>{" "}{t("common.ui.sex")}{" "}{patient.gender}
          </p>
          <p className="text-slate-700">{t("common.ui.pid")}{" "}<span className="font-semibold">{patient.patientId}</span>
          </p>
        </div>
        <div className="h-[72px] w-[72px] shrink-0 rounded border border-slate-200 bg-white p-1">
          <QRCode value={qrValue} size={64} style={{ width: "100%", height: "100%" }} />
        </div>
      </div>

      <div className="space-y-2 border-r border-slate-300 px-3">
        <div>
          <p className="font-bold text-slate-800">{t("common.ui.sampleCollectedAt")}</p>
          <p className="mt-0.5 leading-4 text-slate-600">
            {sample.collectedAtLocation || labAddress}
          </p>
        </div>
        <p className="pt-1">
          <span className="font-bold text-slate-800">{t("common.ui.refBy")}</span>{" "}
          <span className="font-semibold text-slate-700">{doctor.name}</span>
        </p>
      </div>

      <div className="flex flex-col items-end pl-3">
        <div className="mb-2 scale-90 origin-top-right">
          <BarcodeDisplay
            value={reportInfo.reportNumber}
            width={1.2}
            height={36}
            displayValue={false}
          />
        </div>
        <div className="w-full space-y-1 text-[11px] text-slate-700">
          <MetaLine label={t("common.ui.registeredOn")} value={formatDateTime(order.orderedAt)} />
          <MetaLine label={t("common.ui.collectedOn")} value={formatDateTime(sample.collectedAt)} />
          <MetaLine label={t("common.ui.reportedOn")} value={formatDateTime(reportInfo.reportedAt)} />
        </div>
      </div>
    </section>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="font-semibold text-slate-800">{label}</span>
      <span className="text-right tabular-nums text-slate-600">{value}</span>
    </div>
  );
}
