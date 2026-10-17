"use client";

import { useEffect, useMemo, useState } from "react";
import AddIcon from "@mui/icons-material/Add";
import CheckIcon from "@mui/icons-material/Check";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import LocalHospitalOutlinedIcon from "@mui/icons-material/LocalHospitalOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RefreshIcon from "@mui/icons-material/Refresh";
import StopIcon from "@mui/icons-material/Stop";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import Alert from "@mui/material/Alert";

import { toast } from "@/components/ui/toast";
import { api, getUserFacingError } from "@/lib/api";
import { localDateTimeNow } from "@/lib/dates";
import { formatAgeSexShort } from "@/lib/format-age";
import { useLocale } from "@/lib/i18n";
import { getMe } from "@/features/session/api";
import type { AdmittableVisit } from "@/features/ipd/api/ipd";

import {
  cancelOtCase,
  completeOtCase,
  createOtSchedule,
  listOtSchedules,
  startOtCase,
  updateWhoChecklist,
} from "../api";
import type { OtSchedule } from "../types";

type OtCandidate = AdmittableVisit & { admission_id?: string | null };

// Suggestions only: there is no approved procedure catalogue yet, so the name
// stays free text (QA 17 Oct 2026: "no option inside procedure name").
const COMMON_PROCEDURES = [
  "Appendectomy",
  "Laparoscopic cholecystectomy",
  "Inguinal hernia repair",
  "Caesarean section",
  "Dilatation and curettage",
  "Open reduction and internal fixation",
  "Incision and drainage",
  "Debridement",
  "Cataract extraction with IOL",
  "Tonsillectomy",
];

const hoursFromNow = (hours: number) => localDateTimeNow(new Date(Date.now() + hours * 3_600_000));

function emptySchedule() {
  return {
    theatre_number: "OT-1",
    // Local time. These were UTC (toISOString), so the default start read
    // 07:55 at 12:25 IST (QA 17 Oct 2026).
    scheduled_start: hoursFromNow(1),
    scheduled_end: hoursFromNow(2),
    procedure_name: "",
  };
}

/** Nothing clinical is pre-filled: a draft diagnosis or a pre-ticked safety
 *  check is a record nobody made. */
function emptyRecord(surgeonId: string) {
  return {
    started_at: "",
    ended_at: localDateTimeNow(),
    surgeon_user_id: surgeonId,
    pre_op_diagnosis: "",
    post_op_diagnosis: "",
    procedure_performed: "",
    anesthesia_type: "",
    sponge_needle_count_correct: false,
    recovery_status: "",
    notes: "",
  };
}

export function OtDashboard() {
  const { t } = useLocale();
  const [schedules, setSchedules] = useState<OtSchedule[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [me, setMe] = useState<{ id: string; full_name?: string | null } | null>(null);
  const [patient, setPatient] = useState<OtCandidate | null>(null);
  const [patientQuery, setPatientQuery] = useState("");
  const [patientResults, setPatientResults] = useState<OtCandidate[] | null>(null);
  const [patientError, setPatientError] = useState<string | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [completeError, setCompleteError] = useState<string | null>(null);
  const [theatreTab, setTheatreTab] = useState<string>("ALL");

  // Modals state
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [checklistModalOpen, setChecklistModalOpen] = useState(false);
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [activeSchedule, setActiveSchedule] = useState<OtSchedule | null>(null);

  // Form states
  const [newSchedule, setNewSchedule] = useState(emptySchedule);

  const [checklist, setChecklist] = useState({ sign_in: false, time_out: false, sign_out: false, notes: "" });

  const [completeForm, setCompleteForm] = useState(() => emptyRecord(""));

  const [cancelReason, setCancelReason] = useState("");

  const loadSchedules = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listOtSchedules();
      setSchedules(data);
    } catch (err) {
      // This used to swap in three invented cases (fake patients, fake ids),
      // so a failed load looked like a working theatre list and every action
      // on it failed (QA 17 Oct 2026). A failure is shown as one.
      setSchedules([]);
      setLoadError(getUserFacingError(err, t("ot.errLoad")));
      return;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSchedules();
    getMe()
      .then((user) => setMe({ id: user.id, full_name: user.full_name }))
      .catch(() => setMe(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  async function searchPatients() {
    if (patientQuery.trim().length < 2) {
      setPatientError(t("ot.searchMinChars"));
      return;
    }
    setPatientError(null);
    try {
      setPatientResults(await api<OtCandidate[]>(`/ot/candidate-visits?q=${encodeURIComponent(patientQuery.trim())}`));
    } catch (err) {
      setPatientResults(null);
      setPatientError(getUserFacingError(err, t("ot.errSearch")));
    }
  }

  function openScheduleDialog() {
    setNewSchedule(emptySchedule());
    setPatient(null);
    setPatientQuery("");
    setPatientResults(null);
    setPatientError(null);
    setScheduleError(null);
    setScheduleModalOpen(true);
  }

  const filteredSchedules = useMemo(() => {
    if (theatreTab === "ALL") return schedules;
    return schedules.filter((s) => s.theatre_number === theatreTab);
  }, [schedules, theatreTab]);

  const handleCreateSchedule = async () => {
    if (!patient) {
      setScheduleError(t("ot.errPatientRequired"));
      return;
    }
    if (!newSchedule.procedure_name.trim()) {
      setScheduleError(t("ot.errProcedureRequired"));
      return;
    }
    if (!newSchedule.scheduled_start || !newSchedule.scheduled_end || newSchedule.scheduled_end <= newSchedule.scheduled_start) {
      setScheduleError(t("ot.errTimes"));
      return;
    }
    setScheduleError(null);
    try {
      await createOtSchedule({
        patient_id: patient.patient_id,
        visit_id: patient.visit_id,
        admission_id: patient.admission_id ?? undefined,
        theatre_number: newSchedule.theatre_number,
        procedure_name: newSchedule.procedure_name.trim(),
        scheduled_start: new Date(newSchedule.scheduled_start).toISOString(),
        scheduled_end: new Date(newSchedule.scheduled_end).toISOString(),
      });
      toast.success(t("ot.toast.scheduled"));
      setScheduleModalOpen(false);
      void loadSchedules();
    } catch (e: unknown) {
      setScheduleError(getUserFacingError(e, t("ot.toast.scheduleFailed")));
    }
  };

  const handleUpdateChecklist = async () => {
    if (!activeSchedule) return;
    try {
      await updateWhoChecklist(activeSchedule.id, {
        sign_in_confirmed: checklist.sign_in,
        time_out_confirmed: checklist.time_out,
        sign_out_confirmed: checklist.sign_out,
        notes: checklist.notes,
      });
      toast.success(t("ot.toast.checklistRecorded"));
      setChecklistModalOpen(false);
      void loadSchedules();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("ot.toast.checklistFailed"));
    }
  };

  const handleStartCase = async (schedule: OtSchedule) => {
    try {
      await startOtCase(schedule.id);
      toast.success(t("ot.toast.started", { theatre: schedule.theatre_number }));
      void loadSchedules();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("ot.toast.startFailed"));
    }
  };

  const handleCompleteCase = async () => {
    if (!activeSchedule) return;
    if (!completeForm.started_at || !completeForm.surgeon_user_id || !completeForm.procedure_performed.trim()) {
      setCompleteError(t("ot.errRecordRequired"));
      return;
    }
    setCompleteError(null);
    try {
      await completeOtCase(activeSchedule.id, {
        started_at: new Date(completeForm.started_at).toISOString(),
        ended_at: new Date(completeForm.ended_at).toISOString(),
        surgeon_user_id: completeForm.surgeon_user_id,
        pre_op_diagnosis: completeForm.pre_op_diagnosis,
        post_op_diagnosis: completeForm.post_op_diagnosis,
        procedure_performed: completeForm.procedure_performed,
        anesthesia_type: completeForm.anesthesia_type,
        sponge_needle_count_correct: completeForm.sponge_needle_count_correct,
        recovery_status: completeForm.recovery_status,
        notes: completeForm.notes,
      });
      toast.success(t("ot.toast.completed"));
      setCompleteModalOpen(false);
      void loadSchedules();
    } catch (e: unknown) {
      setCompleteError(getUserFacingError(e, t("ot.toast.completeFailed")));
    }
  };

  const handleCancelCase = async () => {
    if (!activeSchedule || !cancelReason.trim()) return;
    try {
      await cancelOtCase(activeSchedule.id, cancelReason.trim());
      toast.success(t("ot.toast.cancelled"));
      setCancelModalOpen(false);
      void loadSchedules();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("ot.toast.cancelFailed"));
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1380, mx: "auto" }}>
      {/* Header Banner */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 2,
          mb: 3,
        }}
      >
        <Box>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
            <LocalHospitalOutlinedIcon color="primary" sx={{ fontSize: 32 }} />
            <Typography component="h1" variant="h5" sx={{ fontWeight: 800 }}>
              {t("ot.title")}
            </Typography>
            <Chip label={t("ot.chipSafety")} color="primary" size="small" sx={{ fontWeight: 700 }} />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {t("ot.subtitle")}
          </Typography>
        </Box>

        <Box sx={{ display: "flex", gap: 1.5 }}>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadSchedules} disabled={loading}>
            {t("common.refresh")}
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={openScheduleDialog}
            sx={{ fontWeight: 700 }}
          >
            {t("ot.scheduleSurgery")}
          </Button>
        </Box>
      </Box>

      {/* Metrics Summary Strip */}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(4, 1fr)" },
          gap: 2,
          mb: 3,
        }}
      >
        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              {t("ot.metric.scheduledToday")}
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#1565c0" }}>
              {schedules.filter((s) => s.status === "scheduled").length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              {t("ot.metric.inProgress")}
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#e65100" }}>
              {schedules.filter((s) => s.status === "in_progress").length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              {t("ot.metric.whoVerified")}
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#2e7d32" }}>
              {schedules.filter((s) => s.surgical_safety_confirmed).length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              {t("ot.metric.completed")}
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "text.primary" }}>
              {schedules.filter((s) => s.status === "completed").length}
            </Typography>
          </CardContent>
        </Card>
      </Box>

      {loadError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={<Button color="inherit" size="small" onClick={() => void loadSchedules()}>{t("common.retry")}</Button>}
        >
          {loadError}
        </Alert>
      )}

      {/* Theatre Selection Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs value={theatreTab} onChange={(_, v) => setTheatreTab(v)}>
          <Tab label={t("ot.tab.allTheatres")} value="ALL" sx={{ fontWeight: 700 }} />
          <Tab label={t("ot.tab.ot1Main")} value="OT-1" sx={{ fontWeight: 700 }} />
          <Tab label={t("ot.tab.ot2Ortho")} value="OT-2" sx={{ fontWeight: 700 }} />
          <Tab label={t("ot.tab.minorOt")} value="Minor-OT" sx={{ fontWeight: 700 }} />
        </Tabs>
      </Box>

      {/* Schedules Table */}
      <TableContainer component={Card} variant="outlined" sx={{ borderRadius: 2 }}>
        <Table>
          <TableHead sx={{ bgcolor: "action.hover" }}>
            <TableRow>
              <TableCell sx={{ fontWeight: 700 }}>{t("ot.col.theatreTime")}</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{t("ot.col.patient")}</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{t("ot.col.procedure")}</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{t("ot.col.whoSafety")}</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{t("ot.col.status")}</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>{t("ot.col.actions")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {!loading && !loadError && filteredSchedules.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  {t("ot.emptyList")}
                </TableCell>
              </TableRow>
            )}
            {filteredSchedules.map((sch) => {
              const startTime = new Date(sch.scheduled_start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
              const endTime = new Date(sch.scheduled_end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

              return (
                <TableRow key={sch.id} hover>
                  <TableCell>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{sch.theatre_number}</Typography>
                    <Typography variant="caption" color="text.secondary">{startTime} – {endTime}</Typography>
                  </TableCell>

                  <TableCell>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{sch.patient_name || "—"}</Typography>
                    <Typography variant="caption" color="text.secondary">{sch.patient_uhid || "—"}</Typography>
                  </TableCell>

                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{sch.procedure_name}</Typography>
                  </TableCell>

                  <TableCell>
                    {sch.surgical_safety_confirmed ? (
                      <Chip
                        icon={<CheckIcon fontSize="small" />}
                        label={t("ot.checklist.verified")}
                        size="small"
                        color="success"
                        sx={{ fontWeight: 700 }}
                      />
                    ) : (
                      <Chip
                        label={t("ot.checklist.pending")}
                        size="small"
                        color="warning"
                        variant="outlined"
                        sx={{ fontWeight: 700 }}
                      />
                    )}
                  </TableCell>

                  <TableCell>
                    {sch.status === "in_progress" && <Chip label={t("ot.status.inProgress")} size="small" color="warning" sx={{ fontWeight: 700 }} />}
                    {sch.status === "scheduled" && <Chip label={t("ot.status.scheduled")} size="small" color="info" sx={{ fontWeight: 700 }} />}
                    {sch.status === "completed" && <Chip label={t("ot.status.completed")} size="small" color="success" sx={{ fontWeight: 700 }} />}
                    {sch.status === "cancelled" && <Chip label={t("ot.status.cancelled")} size="small" color="default" sx={{ fontWeight: 700 }} />}
                  </TableCell>

                  <TableCell align="right">
                    <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<FactCheckOutlinedIcon />}
                        onClick={() => {
                          setActiveSchedule(sch);
                          setChecklist({
                            sign_in: Boolean(sch.pre_op_checklist?.sign_in),
                            time_out: Boolean(sch.pre_op_checklist?.time_out),
                            sign_out: Boolean(sch.pre_op_checklist?.sign_out),
                            notes: String(sch.pre_op_checklist?.notes ?? ""),
                          });
                          setChecklistModalOpen(true);
                        }}
                      >
                        {t("ot.action.whoChecklist")}
                      </Button>

                      {sch.status === "scheduled" && (
                        <Button
                          size="small"
                          variant="contained"
                          color="warning"
                          startIcon={<PlayArrowIcon />}
                          onClick={() => handleStartCase(sch)}
                        >
                          {t("ot.action.start")}
                        </Button>
                      )}

                      {sch.status === "in_progress" && (
                        <Button
                          size="small"
                          variant="contained"
                          color="success"
                          startIcon={<StopIcon />}
                          onClick={() => {
                            setActiveSchedule(sch);
                            setCompleteForm(emptyRecord(me?.id ?? ""));
                            setCompleteError(null);
                            setCompleteModalOpen(true);
                          }}
                        >
                          {t("ot.action.complete")}
                        </Button>
                      )}

                      {sch.status !== "completed" && sch.status !== "cancelled" && (
                        <Button
                          size="small"
                          color="error"
                          onClick={() => {
                            setActiveSchedule(sch);
                            setCancelModalOpen(true);
                          }}
                        >
                          {t("ot.action.cancel")}
                        </Button>
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Schedule Surgery Dialog */}
      <Dialog open={scheduleModalOpen} onClose={() => setScheduleModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>{t("ot.scheduleDialogTitle")}</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          {scheduleError && <Alert severity="error">{scheduleError}</Alert>}
          {patient ? (
            <Box sx={{ p: 1.5, border: 1, borderColor: "primary.light", borderRadius: 1.5, display: "flex", justifyContent: "space-between", gap: 1 }}>
              <Box>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{patient.patient_name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {[patient.patient_identifier, formatAgeSexShort(patient.patient_age, patient.patient_sex ?? "unknown"), patient.visit_number]
                    .filter(Boolean)
                    .join(" · ")}
                  {patient.admission_id ? ` · ${t("ot.admitted")}` : ""}
                </Typography>
              </Box>
              <Button size="small" onClick={() => setPatient(null)}>{t("common.changePatient")}</Button>
            </Box>
          ) : (
            <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <Box sx={{ display: "flex", gap: 1 }}>
                <TextField
                  label={t("ot.patientSearchLabel")}
                  placeholder={t("ot.patientSearchPlaceholder")}
                  value={patientQuery}
                  onChange={(e) => setPatientQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void searchPatients();
                    }
                  }}
                  error={Boolean(patientError) || Boolean(scheduleError && !patient)}
                  helperText={patientError ?? undefined}
                  fullWidth
                  size="small"
                />
                <Button variant="outlined" onClick={() => void searchPatients()}>{t("common.search")}</Button>
              </Box>
              {patientResults && patientResults.length === 0 && (
                <Typography variant="caption" color="text.secondary">{t("ot.noCandidates")}</Typography>
              )}
              {(patientResults ?? []).map((row) => (
                <Button
                  key={row.visit_id}
                  variant="text"
                  sx={{ justifyContent: "flex-start", textTransform: "none" }}
                  onClick={() => {
                    setPatient(row);
                    setPatientResults(null);
                  }}
                >
                  {row.patient_name} · {[row.patient_identifier, row.visit_number].filter(Boolean).join(" · ")}
                </Button>
              ))}
            </Box>
          )}
          <TextField
            label={t("ot.theatreRoom")}
            select
            value={newSchedule.theatre_number}
            onChange={(e) => setNewSchedule({ ...newSchedule, theatre_number: e.target.value })}
            fullWidth
          >
            <MenuItem value="OT-1">{t("ot.tab.ot1Main")}</MenuItem>
            <MenuItem value="OT-2">{t("ot.tab.ot2Ortho")}</MenuItem>
            <MenuItem value="Minor-OT">{t("ot.tab.minorOt")}</MenuItem>
          </TextField>

          <TextField
            label={t("ot.procedureName")}
            value={newSchedule.procedure_name}
            onChange={(e) => setNewSchedule({ ...newSchedule, procedure_name: e.target.value })}
            slotProps={{ htmlInput: { list: "ot-procedure-suggestions" } }}
            required
            error={Boolean(scheduleError && !newSchedule.procedure_name.trim())}
            fullWidth
          />
          <datalist id="ot-procedure-suggestions">
            {COMMON_PROCEDURES.map((name) => <option key={name} value={name} />)}
          </datalist>

          <TextField
            label={t("ot.scheduledStart")}
            type="datetime-local"
            value={newSchedule.scheduled_start}
            onChange={(e) => setNewSchedule({ ...newSchedule, scheduled_start: e.target.value })}
            fullWidth
          />

          <TextField
            label={t("ot.scheduledEnd")}
            type="datetime-local"
            value={newSchedule.scheduled_end}
            onChange={(e) => setNewSchedule({ ...newSchedule, scheduled_end: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setScheduleModalOpen(false)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={handleCreateSchedule} sx={{ fontWeight: 700 }}>
            {t("ot.confirmBooking")}
          </Button>
        </DialogActions>
      </Dialog>

      {/* WHO Surgical Safety Checklist Modal */}
      <Dialog open={checklistModalOpen} onClose={() => setChecklistModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>
          {t("ot.checklist.modalTitle")}
        </DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {t("ot.checklist.caseLabel", {
              procedure: activeSchedule?.procedure_name ?? "",
              theatre: activeSchedule?.theatre_number ?? "",
            })}
          </Typography>

          <Box sx={{ p: 1.5, bgcolor: "#e3f2fd", borderRadius: 1.5, border: "1px solid #bbdefb" }}>
            <FormControlLabel
              control={<Checkbox checked={checklist.sign_in} onChange={(e) => setChecklist({ ...checklist, sign_in: e.target.checked })} />}
              label={
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>1. SIGN-IN (Before induction of anesthesia)</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Patient identity, site & procedure confirmed. Consent verified. Pulse oximeter active. Known allergies and difficult airway risk assessed.
                  </Typography>
                </Box>
              }
            />
          </Box>

          <Box sx={{ p: 1.5, bgcolor: "#fff3e0", borderRadius: 1.5, border: "1px solid #ffe0b2" }}>
            <FormControlLabel
              control={<Checkbox checked={checklist.time_out} onChange={(e) => setChecklist({ ...checklist, time_out: e.target.checked })} />}
              label={
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>2. TIME-OUT (Before skin incision)</Typography>
                  <Typography variant="caption" color="text.secondary">
                    All team members introduced. Surgeon, anesthetist, and nurse verbal review. Antibiotic prophylaxis given within past 60 mins. Essential imaging displayed.
                  </Typography>
                </Box>
              }
            />
          </Box>

          <Box sx={{ p: 1.5, bgcolor: "#e8f5e9", borderRadius: 1.5, border: "1px solid #c8e6c9" }}>
            <FormControlLabel
              control={<Checkbox checked={checklist.sign_out} onChange={(e) => setChecklist({ ...checklist, sign_out: e.target.checked })} />}
              label={
                <Box>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>3. SIGN-OUT (Before patient leaves operating room)</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Name of procedure recorded. Sponge and needle counts correct. Specimen labelled with patient identifiers. Equipment problems addressed. PACU recovery concerns.
                  </Typography>
                </Box>
              }
            />
          </Box>

          <TextField
            label={t("ot.checklist.notesLabel")}
            multiline
            rows={2}
            value={checklist.notes}
            onChange={(e) => setChecklist({ ...checklist, notes: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setChecklistModalOpen(false)}>{t("common.cancel")}</Button>
          <Button variant="contained" color="success" onClick={handleUpdateChecklist} sx={{ fontWeight: 700 }}>
            {t("ot.checklist.signAndVerify")}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Operative Record & Completion Modal */}
      <Dialog open={completeModalOpen} onClose={() => setCompleteModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>{t("ot.completeDialogTitle")}</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          {completeError && <Alert severity="error">{completeError}</Alert>}
          <Typography variant="body2" color="text.secondary">
            {activeSchedule?.patient_name} · {activeSchedule?.procedure_name} ({activeSchedule?.theatre_number})
          </Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            <TextField
              label={t("ot.startedAt")}
              type="datetime-local"
              value={completeForm.started_at}
              onChange={(e) => setCompleteForm({ ...completeForm, started_at: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
              required
              error={Boolean(completeError && !completeForm.started_at)}
              fullWidth
            />
            <TextField
              label={t("ot.endedAt")}
              type="datetime-local"
              value={completeForm.ended_at}
              onChange={(e) => setCompleteForm({ ...completeForm, ended_at: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
              fullWidth
            />
          </Box>
          <Typography variant="caption" color="text.secondary">
            {t("ot.surgeonIsYou", { name: me?.full_name ?? "" })}
          </Typography>

          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            <TextField
              label={t("ot.preOpDiagnosis")}
              value={completeForm.pre_op_diagnosis}
              onChange={(e) => setCompleteForm({ ...completeForm, pre_op_diagnosis: e.target.value })}
              fullWidth
            />
            <TextField
              label={t("ot.postOpDiagnosis")}
              value={completeForm.post_op_diagnosis}
              onChange={(e) => setCompleteForm({ ...completeForm, post_op_diagnosis: e.target.value })}
              fullWidth
            />
          </Box>

          <TextField
            label={t("ot.procedurePerformed")}
            required
            error={Boolean(completeError && !completeForm.procedure_performed.trim())}
            value={completeForm.procedure_performed}
            onChange={(e) => setCompleteForm({ ...completeForm, procedure_performed: e.target.value })}
            fullWidth
          />

          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            <TextField
              label={t("ot.anaesthesiaType")}
              value={completeForm.anesthesia_type}
              onChange={(e) => setCompleteForm({ ...completeForm, anesthesia_type: e.target.value })}
              fullWidth
            />
            <TextField
              label={t("ot.recoveryStatus")}
              value={completeForm.recovery_status}
              onChange={(e) => setCompleteForm({ ...completeForm, recovery_status: e.target.value })}
              fullWidth
            />
          </Box>

          <Box sx={{ p: 1.5, bgcolor: "#e8f5e9", borderRadius: 1.5, border: "1px solid #c8e6c9" }}>
            <FormControlLabel
              control={
                <Checkbox
                  checked={completeForm.sponge_needle_count_correct}
                  onChange={(e) => setCompleteForm({ ...completeForm, sponge_needle_count_correct: e.target.checked })}
                />
              }
              label={
                <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "#2e7d32" }}>
                  {t("ot.countsCorrect")}
                </Typography>
              }
            />
          </Box>

          <TextField
            label={t("ot.operativeNotes")}
            multiline
            rows={3}
            value={completeForm.notes}
            onChange={(e) => setCompleteForm({ ...completeForm, notes: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setCompleteModalOpen(false)}>{t("common.cancel")}</Button>
          <Button variant="contained" color="success" onClick={handleCompleteCase} sx={{ fontWeight: 700 }}>
            {t("ot.saveRecord")}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cancel Case Dialog */}
      <Dialog open={cancelModalOpen} onClose={() => setCancelModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>{t("ot.cancelDialogTitle")}</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField
            label={t("ot.cancelReason")}
            multiline
            rows={3}
            placeholder={t("ot.cancelReasonPlaceholder")}
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
            fullWidth
            required
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setCancelModalOpen(false)}>{t("common.back")}</Button>
          <Button variant="contained" color="error" onClick={handleCancelCase} sx={{ fontWeight: 700 }}>
            {t("ot.confirmCancellation")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
