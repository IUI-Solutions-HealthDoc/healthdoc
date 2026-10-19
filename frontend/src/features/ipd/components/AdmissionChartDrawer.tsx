"use client";

import { formatAge } from "@/lib/format-age";
import * as React from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import {
  getAdmissionChart,
  type AdmissionChart,
} from "@/features/ipd/api/ipd";
import { AdmissionChecklistPanel } from "./AdmissionChecklistPanel";
import { useLocale } from "@/lib/i18n";

export interface AdmissionChartDrawerProps {
  admissionId: string | null;
  open: boolean;
  onClose: () => void;
}

export function AdmissionChartDrawer({
  admissionId,
  open,
  onClose,
}: AdmissionChartDrawerProps) {
  const { t, localizeField } = useLocale();
  const [chart, setChart] = React.useState<AdmissionChart | null>(null);
  const [loading, setLoading] = React.useState<boolean>(false);
  const [tabIndex, setTabIndex] = React.useState<number>(0);
  const [error, setError] = React.useState<string | null>(null);

  const fetchChart = React.useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAdmissionChart(id);
      setChart(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load admission chart");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (open && admissionId) {
      fetchChart(admissionId);
    } else {
      setChart(null);
    }
  }, [open, admissionId, fetchChart]);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      slotProps={{
        paper: {
          sx: {
            width: { xs: "100%", md: "720px", lg: "840px" },
            backgroundColor: "#f8fafc",
            p: 0,
          },
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 3,
          backgroundColor: "#001f54",
          color: "#ffffff",
          display: "flex",
          flexDirection: "column",
          gap: 1.5,
        }}
      >
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Box>
            <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
              <Typography sx={{ fontSize: "1.25rem", fontWeight: 700, color: "#ffffff" }}>
                {chart?.patient.full_name || t("ipd.chartPatientChart")}
              </Typography>
              <Chip
                size="small"
                label={chart?.admission.status?.toUpperCase() || "ADMITTED"}
                sx={{
                  backgroundColor: "#22c55e",
                  color: "#ffffff",
                  fontWeight: 700,
                  fontSize: "0.6875rem",
                }}
              />
            </Stack>
            <Typography sx={{ fontSize: "0.8125rem", color: "#93c5fd", mt: 0.5 }}>{t("ipd.ui.uhid")}{" "}{chart?.patient.uhid || t("doctor.soapStatusPending")} · {chart?.patient.sex || ""} · {formatAge(chart?.patient.age_years)}
            </Typography>
          </Box>
          <IconButton
            onClick={onClose}
            sx={{ color: "#ffffff", "&:hover": { backgroundColor: "rgba(255,255,255,0.1)" } }}
          >
            ✕
          </IconButton>
        </Stack>

        <Stack direction="row" spacing={3} sx={{ pt: 1, borderTop: "1px solid rgba(255,255,255,0.15)", fontSize: "0.8125rem" }}>
          <Box>
            <Typography sx={{ fontSize: "0.6875rem", color: "#93c5fd" }}>{t("ipd.chartWardBed")}</Typography>
            <Typography sx={{ fontWeight: 600 }}>
              {localizeField(chart?.admission.ward_name || "--", chart?.admission.ward_name_hi)} / {chart?.admission.bed_number || "--"}
            </Typography>
          </Box>
          <Box>
            <Typography sx={{ fontSize: "0.6875rem", color: "#93c5fd" }}>{t("ipd.chartAdmissionTime")}</Typography>
            <Typography sx={{ fontWeight: 600 }}>
              {chart?.admission.admitted_at
                ? new Date(chart.admission.admitted_at).toLocaleString([], {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })
                : "--"}
            </Typography>
          </Box>
          <Box>
            <Typography sx={{ fontSize: "0.6875rem", color: "#93c5fd" }}>{t("ipd.chartChecklistReconciled")}</Typography>
            <Typography sx={{ fontWeight: 600, color: "#4ade80" }}>
              {chart?.checklist_summary?.percent_complete ?? 0}%
            </Typography>
          </Box>
        </Stack>
      </Box>

      {/* Navigation Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: "divider", backgroundColor: "#ffffff", px: 3 }}>
        <Tabs value={tabIndex} onChange={(_, val) => setTabIndex(val)}>
          <Tab label={t("ipd.chartTabOverview")} />
          <Tab label={t("ipd.chartTabChecklist")} />
          <Tab label={t("ipd.chartTabVitals", { count: chart?.vitals.length || 0 })} />
          <Tab label={t("ipd.chartTabAllergies", { count: chart?.allergies.length || 0 })} />
          <Tab label={t("ipd.chartTabDiagnoses", { count: chart?.diagnoses.length || 0 })} />
          <Tab label={t("ipd.chartTabOrdersMeds")} />
        </Tabs>
      </Box>

      {/* Content Area */}
      <Box sx={{ p: 3, overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
        {error && (
          <Box sx={{ p: 2, borderRadius: "8px", backgroundColor: "#fee2e2", color: "#991b1b" }}>
            {error}
          </Box>
        )}

        {loading ? (
          <Typography sx={{ color: meridian.textSecondary, py: 4, textAlign: "center" }}>{t("ipd.ui.loadingAdmissionChart")}</Typography>
        ) : !chart ? (
          <Typography sx={{ color: meridian.textSecondary, py: 4, textAlign: "center" }}>{t("ipd.ui.noChartDataAvailable")}</Typography>
        ) : (
          <>
            {/* Tab 0: Overview */}
            {tabIndex === 0 && (
              <Stack spacing={2.5}>
                <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                  <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 1 }}>{t("ipd.ui.admissionIndicationReason")}</Typography>
                  <Typography sx={{ fontSize: "0.875rem", color: chart.admission.reason ? "#1e293b" : "#94a3b8" }}>
                    {chart.admission.reason || t("ipd.ui.noExplicitReasonRecordedUponAdmission")}
                  </Typography>
                </Box>

                {/* Latest Vitals Snapshot */}
                <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                  <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 1.5 }}>{t("ipd.ui.latestBaselineVitalSigns")}</Typography>
                  {chart.vitals.length > 0 ? (
                    <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", gap: 1.5 }}>
                      <Box sx={{ p: 1.5, borderRadius: "8px", backgroundColor: "#f1f5f9", minWidth: 100 }}>
                        <Typography sx={{ fontSize: "0.6875rem", color: "#64748b" }}>{t("ipd.ui.temperature")}</Typography>
                        <Typography sx={{ fontSize: "1.125rem", fontWeight: 700 }}>
                          {chart.vitals[0].temp_c ? `${chart.vitals[0].temp_c} °C` : "--"}
                        </Typography>
                      </Box>
                      <Box sx={{ p: 1.5, borderRadius: "8px", backgroundColor: "#f1f5f9", minWidth: 100 }}>
                        <Typography sx={{ fontSize: "0.6875rem", color: "#64748b" }}>{t("ipd.ui.heartRate")}</Typography>
                        <Typography sx={{ fontSize: "1.125rem", fontWeight: 700 }}>
                          {chart.vitals[0].pulse_bpm ? `${chart.vitals[0].pulse_bpm} bpm` : "--"}
                        </Typography>
                      </Box>
                      <Box sx={{ p: 1.5, borderRadius: "8px", backgroundColor: "#f1f5f9", minWidth: 100 }}>
                        <Typography sx={{ fontSize: "0.6875rem", color: "#64748b" }}>{t("ipd.ui.bloodPressure")}</Typography>
                        <Typography sx={{ fontSize: "1.125rem", fontWeight: 700 }}>
                          {chart.vitals[0].bp_systolic && chart.vitals[0].bp_diastolic
                            ? `${chart.vitals[0].bp_systolic}/${chart.vitals[0].bp_diastolic}`
                            : "--"}
                        </Typography>
                      </Box>
                      <Box sx={{ p: 1.5, borderRadius: "8px", backgroundColor: "#f1f5f9", minWidth: 100 }}>
                        <Typography sx={{ fontSize: "0.6875rem", color: "#64748b" }}>{t("ipd.ui.spo2")}</Typography>
                        <Typography sx={{ fontSize: "1.125rem", fontWeight: 700 }}>
                          {chart.vitals[0].spo2_pct ? `${chart.vitals[0].spo2_pct} %` : "--"}
                        </Typography>
                      </Box>
                      <Box sx={{ p: 1.5, borderRadius: "8px", backgroundColor: "#f1f5f9", minWidth: 100 }}>
                        <Typography sx={{ fontSize: "0.6875rem", color: "#64748b" }}>{t("ipd.ui.respRate")}</Typography>
                        <Typography sx={{ fontSize: "1.125rem", fontWeight: 700 }}>
                          {chart.vitals[0].resp_rate ? `${chart.vitals[0].resp_rate} /min` : "--"}
                        </Typography>
                      </Box>
                    </Stack>
                  ) : (
                    <Typography sx={{ fontSize: "0.875rem", color: "#94a3b8" }}>{t("ipd.ui.noVitalsRecordedYetRecordBaseline")}</Typography>
                  )}
                </Box>

                {/* Admission Checklist Summary */}
                <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                  <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between", mb: 1 }}>
                    <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700 }}>{t("ipd.ui.admissionChecklistSafetyScore")}</Typography>
                    <Chip
                      label={`${chart.checklist_summary.percent_complete}% Complete`}
                      color={chart.checklist_summary.percent_complete === 100 ? "success" : "warning"}
                      size="small"
                      sx={{ fontWeight: 700 }}
                    />
                  </Stack>
                  <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("ipd.ui.completedCompletedSkippedSkippedWithJustification", { completed: chart.checklist_summary.completed, skipped: chart.checklist_summary.skipped, pending: chart.checklist_summary.pending })}</Typography>
                </Box>
              </Stack>
            )}

            {/* Tab 1: Checklist */}
            {tabIndex === 1 && (
              <AdmissionChecklistPanel
                admissionId={admissionId || ""}
                onUpdate={() => {
                  if (admissionId) fetchChart(admissionId);
                }}
              />
            )}

            {/* Tab 2: Vitals */}
            {tabIndex === 2 && (
              <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 2 }}>{t("ipd.ui.recordedVitalSigns")}</Typography>
                {chart.vitals.length === 0 ? (
                  <Typography sx={{ fontSize: "0.875rem", color: "#94a3b8" }}>{t("ipd.ui.noVitalsRecordingsFound")}</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {chart.vitals.map((v) => (
                      <Box
                        key={v.id}
                        sx={{
                          p: 1.5,
                          borderRadius: "8px",
                          border: "1px solid #e2e8f0",
                          backgroundColor: "#f8fafc",
                        }}
                      >
                        <Typography sx={{ fontSize: "0.75rem", color: "#64748b", mb: 0.5 }}>
                          {v.measured_at ? new Date(v.measured_at).toLocaleString() : ""}
                        </Typography>
                        <Typography sx={{ fontSize: "0.875rem", fontWeight: 600 }}>{t("ipd.ui.temp")}{" "}{v.temp_c ? `${v.temp_c}°C` : "--"}{" "}{t("ipd.ui.pulse")}{" "}{v.pulse_bpm ? `${v.pulse_bpm} bpm` : "--"}{" "}{t("ipd.ui.bp")}{" "}{v.bp_systolic && v.bp_diastolic ? `${v.bp_systolic}/${v.bp_diastolic}` : "--"}{" "}{t("ipd.ui.spo22")}{" "}{v.spo2_pct ? `${v.spo2_pct}%` : "--"}{" "}{t("ipd.ui.rr")}{" "}{v.resp_rate ? `${v.resp_rate}/min` : "--"}
                        </Typography>
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>
            )}

            {/* Tab 3: Allergies */}
            {tabIndex === 3 && (
              <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 2 }}>{t("ipd.ui.activeAllergyRegister")}</Typography>
                {chart.allergies.length === 0 ? (
                  <Typography sx={{ fontSize: "0.875rem", color: "#16a34a", fontWeight: 500 }}>{t("ipd.ui.noActiveAllergiesReportedForThis")}</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {chart.allergies.map((a) => (
                      <Box
                        key={a.id}
                        sx={{
                          p: 1.5,
                          borderRadius: "8px",
                          border: `1px solid ${a.severity === "anaphylaxis" ? "#fca5a5" : "#fed7aa"}`,
                          backgroundColor: a.severity === "anaphylaxis" ? "#fef2f2" : "#fff7ed",
                        }}
                      >
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          <Typography sx={{ fontWeight: 700, fontSize: "0.9375rem" }}>
                            {a.substance_text}
                          </Typography>
                          <Chip
                            size="small"
                            label={a.severity.toUpperCase()}
                            color={a.severity === "anaphylaxis" ? "error" : "warning"}
                            sx={{ fontWeight: 700, height: 20, fontSize: "0.6875rem" }}
                          />
                        </Stack>
                        {a.reaction && (
                          <Typography sx={{ fontSize: "0.8125rem", color: "#64748b", mt: 0.5 }}>{t("ipd.ui.reactionReaction", { reaction: a.reaction })}</Typography>
                        )}
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>
            )}

            {/* Tab 4: Diagnoses */}
            {tabIndex === 4 && (
              <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 2 }}>{t("ipd.ui.diagnosesClinicalIndications")}</Typography>
                {chart.diagnoses.length === 0 ? (
                  <Typography sx={{ fontSize: "0.875rem", color: "#94a3b8" }}>{t("ipd.ui.noDiagnosesCodedForThisVisit")}</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {chart.diagnoses.map((d) => (
                      <Box
                        key={d.id}
                        sx={{
                          p: 1.5,
                          borderRadius: "8px",
                          border: "1px solid #e2e8f0",
                          backgroundColor: "#f8fafc",
                        }}
                      >
                        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                          <Typography sx={{ fontWeight: 600, fontSize: "0.9375rem" }}>
                            {d.diagnosis_text}
                          </Typography>
                          <Chip
                            size="small"
                            label={`${d.icd_version?.toUpperCase()}: ${d.icd_code}`}
                            sx={{ height: 20, fontSize: "0.6875rem" }}
                          />
                          {d.is_primary && (
                            <Chip
                              size="small"
                              label={t("doctor.diagnosisPrimaryBadge")}
                              color="primary"
                              sx={{ height: 20, fontSize: "0.6875rem", fontWeight: 700 }}
                            />
                          )}
                        </Stack>
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>
            )}

            {/* Tab 5: Orders & Meds */}
            {tabIndex === 5 && (
              <Stack spacing={2.5}>
                {/* Orders */}
                <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                  <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 1.5 }}>{t("ipd.ui.clinicalOrdersLabsRadiology")}</Typography>
                  {chart.orders.length === 0 ? (
                    <Typography sx={{ fontSize: "0.875rem", color: "#94a3b8" }}>{t("ipd.ui.noActiveOrdersPlaced")}</Typography>
                  ) : (
                    <Stack spacing={1}>
                      {chart.orders.map((o) => (
                        <Box key={o.id} sx={{ p: 1.5, borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                          <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
                            <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>
                              {o.order_type.toUpperCase()} · #{o.order_number}
                            </Typography>
                            <Chip size="small" label={o.status} />
                          </Stack>
                        </Box>
                      ))}
                    </Stack>
                  )}
                </Box>

                {/* Prescriptions */}
                <Box sx={{ p: 2.5, borderRadius: "12px", backgroundColor: "#ffffff", border: `1px solid ${meridian.border}` }}>
                  <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700, mb: 1.5 }}>{t("ipd.ui.medicationsPrescriptions")}</Typography>
                  {chart.medications.length === 0 ? (
                    <Typography sx={{ fontSize: "0.875rem", color: "#94a3b8" }}>{t("ipd.ui.noPrescriptionsRecorded")}</Typography>
                  ) : (
                    <Stack spacing={1}>
                      {chart.medications.map((m) => (
                        <Box key={m.id} sx={{ p: 1.5, borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                          <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>
                            {m.medicine_name}
                          </Typography>
                          <Typography sx={{ fontSize: "0.75rem", color: "#64748b" }}>
                            {m.dosage || ""} · {m.frequency || ""} · {m.route || ""} · {m.duration_days ? `${m.duration_days} days` : ""}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  )}
                </Box>
              </Stack>
            )}
          </>
        )}
      </Box>
    </Drawer>
  );
}
