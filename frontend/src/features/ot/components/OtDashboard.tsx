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

import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";

import {
  cancelOtCase,
  completeOtCase,
  createOtSchedule,
  listOtSchedules,
  startOtCase,
  updateWhoChecklist,
} from "../api";
import type { OtSchedule } from "../types";

export function OtDashboard() {
  const { t } = useLocale();
  const [schedules, setSchedules] = useState<OtSchedule[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [theatreTab, setTheatreTab] = useState<string>("ALL");

  // Modals state
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [checklistModalOpen, setChecklistModalOpen] = useState(false);
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [activeSchedule, setActiveSchedule] = useState<OtSchedule | null>(null);

  // Form states
  const [newSchedule, setNewSchedule] = useState(() => ({
    patient_id: "00000000-0000-0000-0000-000000000001",
    visit_id: "00000000-0000-0000-0000-000000000002",
    theatre_number: "OT-1",
    scheduled_start: new Date(Date.now() + 3600000).toISOString().slice(0, 16),
    scheduled_end: new Date(Date.now() + 7200000).toISOString().slice(0, 16),
    procedure_name: "Laparoscopic Cholecystectomy",
  }));

  const [checklist, setChecklist] = useState({
    sign_in: true,
    time_out: true,
    sign_out: false,
    notes: "Patient identity, surgical site, consent, pulse oximeter, antibiotic prophylaxis verified.",
  });

  const [completeForm, setCompleteForm] = useState(() => ({
    started_at: new Date(Date.now() - 3600000).toISOString().slice(0, 16),
    ended_at: new Date().toISOString().slice(0, 16),
    surgeon_user_id: "00000000-0000-0000-0000-000000000003",
    pre_op_diagnosis: "Symptomatic cholelithiasis",
    post_op_diagnosis: "Chronic cholecystitis with gallstones",
    procedure_performed: "Laparoscopic Cholecystectomy with 4-port technique",
    anesthesia_type: "General Endotracheal Anesthesia",
    sponge_needle_count_correct: true,
    recovery_status: "stable_in_pacu",
    notes: "Uncomplicated procedure, haemostasis secured, port sites closed in layers.",
  }));

  const [cancelReason, setCancelReason] = useState("");

  const loadSchedules = async () => {
    setLoading(true);
    try {
      const data = await listOtSchedules();
      setSchedules(data);
    } catch {
      // Mock fallback data for offline / preview
      setSchedules([
        {
          id: "ot-sch-1",
          facility_id: "fac-1",
          patient_id: "pat-1",
          patient_name: "Rajesh Sharma",
          patient_uhid: "HD-2026-00412",
          visit_id: "vis-1",
          theatre_number: "OT-1",
          scheduled_start: new Date(Date.now() - 1800000).toISOString(),
          scheduled_end: new Date(Date.now() + 5400000).toISOString(),
          procedure_name: "Laparoscopic Cholecystectomy",
          status: "in_progress",
          surgical_safety_confirmed: true,
          created_at: new Date().toISOString(),
        },
        {
          id: "ot-sch-2",
          facility_id: "fac-1",
          patient_id: "pat-2",
          patient_name: "Priya Devi",
          patient_uhid: "HD-2026-00583",
          visit_id: "vis-2",
          theatre_number: "OT-2",
          scheduled_start: new Date(Date.now() + 3600000).toISOString(),
          scheduled_end: new Date(Date.now() + 7200000).toISOString(),
          procedure_name: "Total Knee Arthroplasty (Right)",
          status: "scheduled",
          surgical_safety_confirmed: false,
          created_at: new Date().toISOString(),
        },
        {
          id: "ot-sch-3",
          facility_id: "fac-1",
          patient_id: "pat-3",
          patient_name: "Sunita Verma",
          patient_uhid: "HD-2026-00391",
          visit_id: "vis-3",
          theatre_number: "OT-1",
          scheduled_start: new Date(Date.now() - 14400000).toISOString(),
          scheduled_end: new Date(Date.now() - 7200000).toISOString(),
          procedure_name: "Emergency Appendectomy",
          status: "completed",
          surgical_safety_confirmed: true,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSchedules();
  }, []);

  const filteredSchedules = useMemo(() => {
    if (theatreTab === "ALL") return schedules;
    return schedules.filter((s) => s.theatre_number === theatreTab);
  }, [schedules, theatreTab]);

  const handleCreateSchedule = async () => {
    try {
      await createOtSchedule({
        ...newSchedule,
        scheduled_start: new Date(newSchedule.scheduled_start).toISOString(),
        scheduled_end: new Date(newSchedule.scheduled_end).toISOString(),
      });
      toast.success(t("ot.toast.scheduled"));
      setScheduleModalOpen(false);
      void loadSchedules();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("ot.toast.scheduleFailed"));
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
      toast.error(e instanceof Error ? e.message : t("ot.toast.completeFailed"));
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
            onClick={() => setScheduleModalOpen(true)}
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
                    <Typography variant="caption" color="text.secondary">{sch.patient_uhid || sch.patient_id.slice(0, 8)}</Typography>
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
                            sign_in: sch.pre_op_checklist?.sign_in ?? true,
                            time_out: sch.pre_op_checklist?.time_out ?? true,
                            sign_out: sch.pre_op_checklist?.sign_out ?? false,
                            notes: sch.pre_op_checklist?.notes ?? "",
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
        <DialogTitle sx={{ fontWeight: 800 }}>Schedule Operating Theatre Case</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField
            label="Theatre Room"
            select
            value={newSchedule.theatre_number}
            onChange={(e) => setNewSchedule({ ...newSchedule, theatre_number: e.target.value })}
            fullWidth
          >
            <MenuItem value="OT-1">OT-1 (Main Laparoscopic)</MenuItem>
            <MenuItem value="OT-2">OT-2 (Orthopaedic Suite)</MenuItem>
            <MenuItem value="Minor-OT">Minor OT (Day Procedures)</MenuItem>
          </TextField>

          <TextField
            label="Procedure Name"
            value={newSchedule.procedure_name}
            onChange={(e) => setNewSchedule({ ...newSchedule, procedure_name: e.target.value })}
            fullWidth
          />

          <TextField
            label="Scheduled Start"
            type="datetime-local"
            value={newSchedule.scheduled_start}
            onChange={(e) => setNewSchedule({ ...newSchedule, scheduled_start: e.target.value })}
            fullWidth
          />

          <TextField
            label="Scheduled End"
            type="datetime-local"
            value={newSchedule.scheduled_end}
            onChange={(e) => setNewSchedule({ ...newSchedule, scheduled_end: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setScheduleModalOpen(false)}>{t("common.cancel")}</Button>
          <Button variant="contained" onClick={handleCreateSchedule} sx={{ fontWeight: 700 }}>
            Confirm Booking
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
        <DialogTitle sx={{ fontWeight: 800 }}>Complete Surgery & Operative Record</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Procedure: {activeSchedule?.procedure_name} ({activeSchedule?.theatre_number})
          </Typography>

          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            <TextField
              label="Pre-operative Diagnosis"
              value={completeForm.pre_op_diagnosis}
              onChange={(e) => setCompleteForm({ ...completeForm, pre_op_diagnosis: e.target.value })}
              fullWidth
            />
            <TextField
              label="Post-operative Diagnosis"
              value={completeForm.post_op_diagnosis}
              onChange={(e) => setCompleteForm({ ...completeForm, post_op_diagnosis: e.target.value })}
              fullWidth
            />
          </Box>

          <TextField
            label="Procedure Performed"
            value={completeForm.procedure_performed}
            onChange={(e) => setCompleteForm({ ...completeForm, procedure_performed: e.target.value })}
            fullWidth
          />

          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
            <TextField
              label="Anesthesia Type"
              value={completeForm.anesthesia_type}
              onChange={(e) => setCompleteForm({ ...completeForm, anesthesia_type: e.target.value })}
              fullWidth
            />
            <TextField
              label="Recovery Status"
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
                  Sponge, Swab, and Needle Count Correct (Verified by Scrub & Circulating Nurse)
                </Typography>
              }
            />
          </Box>

          <TextField
            label="Operative Summary & Findings"
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
            Commit Operative Record
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cancel Case Dialog */}
      <Dialog open={cancelModalOpen} onClose={() => setCancelModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>Cancel OT Case</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField
            label="Cancellation Reason"
            multiline
            rows={3}
            placeholder="e.g. Patient haemodynamically unstable, elective postponement..."
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
            fullWidth
            required
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setCancelModalOpen(false)}>{t("common.back")}</Button>
          <Button variant="contained" color="error" onClick={handleCancelCase} sx={{ fontWeight: 700 }}>
            Confirm Cancellation
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
