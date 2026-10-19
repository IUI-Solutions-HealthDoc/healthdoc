"use client";

import { formatScheduleAge, humanizeCode } from "@/lib/format-age";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  Clock,
  Plus,
  RefreshCw,
  ShieldAlert,
  Syringe,
} from "lucide-react";
import { formatDate } from "@/lib/dates";
import { fetchPatientSchedule } from "../api";
import type { PatientImmunizationSchedule } from "../types";
import { useLocale, translate } from "@/lib/i18n";

interface ImmunizationScheduleViewProps {
  patientId: string;
  patientName?: string;
  uhid?: string;
  onOpenRecordModal: () => void;
  onOpenCertificateModal: () => void;
  refreshTrigger?: number;
}

export function ImmunizationScheduleView({
  patientId,
  patientName,
  uhid,
  onOpenRecordModal,
  onOpenCertificateModal,
  refreshTrigger = 0,
}: ImmunizationScheduleViewProps) {
  const { t } = useLocale();
  const [schedule, setSchedule] = useState<PatientImmunizationSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"history" | "due" | "overdue">("history");

  const loadSchedule = useCallback(async () => {
    if (!patientId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await fetchPatientSchedule(patientId);
      setSchedule(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : translate("immunization.msg.failedToLoadImmunizationSchedule"));
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule, refreshTrigger]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-muted-foreground">
        <RefreshCw className="h-6 w-6 animate-spin mr-2" />
        <span>{t("immunization.ui.loadingImmunizationSchedule")}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-destructive flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-sm">{t("immunization.ui.errorLoadingImmunizationData")}</h4>
          <p className="text-xs mt-1">{error}</p>
        </div>
        <button
          onClick={loadSchedule}
          className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 transition-colors"
        >{t("common.retry")}</button>
      </div>
    );
  }

  const recordCount = schedule?.administered.length || 0;
  const dueCount = schedule?.due.filter((v) => v.status === "due").length || 0;
  const overdueCount = schedule?.due.filter((v) => v.status === "overdue").length || 0;

  return (
    <div className="space-y-6">
      {/* Top action header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border p-5 rounded-2xl shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <Syringe className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">
              {patientName ? `${patientName}'s Immunization Profile` : t("immunization.ui.patientImmunizationSchedule")}
            </h2>
          </div>
          {uhid && <p className="text-xs text-muted-foreground mt-0.5 font-mono">{t("nurse.ui.uhidUhid", { uhid })}</p>}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onOpenCertificateModal}
            className="flex items-center gap-1.5 rounded-xl border border-border bg-background px-3.5 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors shadow-sm"
          >
            <Award className="h-4 w-4 text-amber-500" />{t("immunization.ui.viewCertificate")}</button>
          <button
            onClick={onOpenRecordModal}
            className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
          >
            <Plus className="h-4 w-4" />{t("immunization.ui.recordDose")}</button>
        </div>
      </div>

      {/* KPI status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div
          onClick={() => setActiveTab("history")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "history"
              ? "border-primary bg-primary/5 ring-1 ring-primary"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{t("immunization.ui.administeredDoses")}</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{recordCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">{t("immunization.ui.verifiedVaccinationsOnRecord")}</p>
        </div>

        <div
          onClick={() => setActiveTab("due")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "due"
              ? "border-amber-500 bg-amber-500/5 ring-1 ring-amber-500"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{t("immunization.ui.dueNext")}</span>
            <Clock className="h-4 w-4 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{dueCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">{t("immunization.ui.recommendedPerNationalSchedule")}</p>
        </div>

        <div
          onClick={() => setActiveTab("overdue")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "overdue"
              ? "border-destructive bg-destructive/5 ring-1 ring-destructive"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{t("immunization.ui.overdueDoses")}</span>
            <ShieldAlert className="h-4 w-4 text-destructive" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{overdueCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">{t("immunization.ui.lapsedMilestoneVaccines")}</p>
        </div>
      </div>

      {/* Tab Panels */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
        <div className="flex items-center border-b border-border px-4 pt-3 bg-muted/20">
          <button
            onClick={() => setActiveTab("history")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "history"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >{t("immunization.ui.administrationHistoryRecordcount", { recordCount })}</button>
          <button
            onClick={() => setActiveTab("due")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "due"
                ? "border-amber-500 text-amber-500"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >{t("immunization.ui.dueVaccinesDuecount", { dueCount })}</button>
          <button
            onClick={() => setActiveTab("overdue")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "overdue"
                ? "border-destructive text-destructive"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >{t("immunization.ui.overdueOverduecount", { overdueCount })}</button>
        </div>

        {/* Tab 1: History */}
        {activeTab === "history" && (
          <div className="p-4">
            {recordCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <Syringe className="h-8 w-8 mx-auto mb-2 opacity-40" />{t("immunization.ui.noVaccinesRecordedYetForThis")}</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/50 text-muted-foreground font-semibold">
                    <tr>
                      <th className="p-3 rounded-l-lg">{t("immunization.record.vaccine")}</th>
                      <th className="p-3">{t("immunization.col.dose")}</th>
                      <th className="p-3">{t("common.ui.administered")}</th>
                      <th className="p-3">{t("immunization.ui.batchLot")}</th>
                      <th className="p-3">{t("immunization.ui.routeSite")}</th>
                      <th className="p-3">{t("immunization.ui.adverseReaction")}</th>
                      <th className="p-3 rounded-r-lg">{t("inventory.grn.expiry")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {schedule?.administered.map((rec) => (
                      <tr key={rec.id} className="hover:bg-muted/30">
                        <td className="p-3 font-semibold text-foreground">
                          {rec.vaccine_code}
                          {rec.vaccine_code && (
                            <span className="ml-1 text-[10px] text-muted-foreground font-mono">
                              ({rec.vaccine_code})
                            </span>
                          )}
                        </td>
                        <td className="p-3">
                          <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                            <span className="whitespace-nowrap">{t("immunization.ui.doseDoseNumber", { dose_number: rec.dose_number })}</span>
                          </span>
                        </td>
                        <td className="p-3 font-mono">{new Date(rec.administered_at).toLocaleString()}</td>
                        <td className="p-3 font-mono font-medium">{rec.batch_number}</td>
                        <td className="p-3 text-muted-foreground">
                          {humanizeCode(rec.route)} {rec.site ? `• ${humanizeCode(rec.site)}` : ""}
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {rec.adverse_reaction ? (
                            <span className="inline-flex items-center gap-1 text-destructive font-medium">
                              <AlertTriangle className="h-3 w-3" />
                              {rec.adverse_reaction}
                            </span>
                          ) : (
                            t("immunization.ui.noneRecorded")
                          )}
                        </td>
                        <td className="p-3 font-mono text-muted-foreground">{rec.expiry_date || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Due Vaccines */}
        {activeTab === "due" && (
          <div className="p-4">
            {dueCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500 opacity-60" />{t("immunization.ui.noDueEntriesWereReturnedConfirm")}</div>
            ) : (
              <div className="space-y-3">
                {schedule?.due.filter((v) => v.status === "due").map((v) => (
                  <div
                    key={v.vaccine_code}
                    className="flex items-center justify-between p-3.5 rounded-xl border border-border bg-background hover:border-primary/40 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-foreground">{v.vaccine_name}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                          {v.vaccine_code}
                        </span>
                        <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">{t("immunization.ui.dueDoseDoseNumber", { dose_number: v.dose_number })}</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{t("immunization.ui.recommendedAt")}{" "}{formatScheduleAge(v.min_age_days)}{" "}{t("immunization.ui.due")}{" "}{v.due_date ? formatDate(v.due_date) : t("immunization.ui.notCalculated")}
                      </p>
                    </div>
                    <button
                      onClick={onOpenRecordModal}
                      className="rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
                    >{t("immunization.ui.administer")}</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Overdue */}
        {activeTab === "overdue" && (
          <div className="p-4">
            {overdueCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500 opacity-60" />{t("immunization.ui.noOverdueEntriesWereReturnedThis")}</div>
            ) : (
              <div className="space-y-3">
                {schedule?.due.filter((v) => v.status === "overdue").map((v) => (
                  <div
                    key={v.vaccine_code}
                    className="flex items-center justify-between p-3.5 rounded-xl border border-destructive/30 bg-destructive/5 hover:border-destructive/60 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-foreground">{v.vaccine_name}</span>
                        <span className="rounded bg-destructive/20 px-1.5 py-0.5 text-[10px] font-mono text-destructive">
                          {v.vaccine_code}
                        </span>
                        <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive">{t("immunization.ui.overdueDoseDoseNumber", { dose_number: v.dose_number })}</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{t("immunization.ui.dueAt")}{" "}{formatScheduleAge(v.min_age_days)}{" "}{t("immunization.ui.due")}{" "}{v.due_date ? formatDate(v.due_date) : t("immunization.ui.notCalculated")}
                      </p>
                    </div>
                    <button
                      onClick={onOpenRecordModal}
                      className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 transition-colors"
                    >{t("immunization.ui.catchUpNow")}</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
