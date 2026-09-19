"use client";

import { useEffect, useState } from "react";
import AddIcon from "@mui/icons-material/Add";
import EventNoteIcon from "@mui/icons-material/EventNote";
import HistoryIcon from "@mui/icons-material/History";
import MonitorHeartOutlinedIcon from "@mui/icons-material/MonitorHeartOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { toast } from "@/components/ui/toast";

import {
  enrolPatient,
  exitEnrolment,
  getEnrolmentTimeline,
  listCarePrograms,
  listEnrolments,
  recordProgramVisit,
} from "../api";
import type { CareProgram, ProgramEnrolment, ProgramTimeline } from "../types";

export function ProgramsDashboard() {
  const [programs, setPrograms] = useState<CareProgram[]>([]);
  const [enrolments, setEnrolments] = useState<ProgramEnrolment[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Modals
  const [enrolModalOpen, setEnrolModalOpen] = useState(false);
  const [visitModalOpen, setVisitModalOpen] = useState(false);
  const [timelineModalOpen, setTimelineModalOpen] = useState(false);
  const [exitModalOpen, setExitModalOpen] = useState(false);

  const [activeEnrolment, setActiveEnrolment] = useState<ProgramEnrolment | null>(null);
  const [activeTimeline, setActiveTimeline] = useState<ProgramTimeline | null>(null);

  // Form states
  const [enrolForm, setEnrolForm] = useState({
    patient_id: "00000000-0000-0000-0000-000000000001",
    program_code: "DIABETES_T2",
    target_hba1c: "7.0",
    target_bp: "130/80",
  });

  const [visitForm, setVisitForm] = useState({
    scheduled_date: new Date().toISOString().slice(0, 10),
    hba1c: "7.2",
    bp_systolic: "128",
    bp_diastolic: "82",
    weight_kg: "72.5",
    clinical_summary: "Glycaemic targets approaching optimal threshold; continue Metformin 500mg BD.",
  });

  const [exitReason, setExitReason] = useState("");

  const loadData = async () => {
    setLoading(true);
    try {
      const [progs, enrs] = await Promise.all([listCarePrograms(), listEnrolments()]);
      setPrograms(progs);
      setEnrolments(enrs);
    } catch {
      // Mock fallback data for offline / preview
      setPrograms([
        {
          id: "cp-1",
          program_code: "DIABETES_T2",
          program_name: "Type 2 Diabetes Mellitus Care Program",
          category: "chronic",
          description: "Glycaemic surveillance and end-organ monitoring",
          is_active: true,
        },
        {
          id: "cp-2",
          program_code: "HYPERTENSION",
          program_name: "Essential Hypertension Care Program",
          category: "chronic",
          description: "Blood pressure surveillance and cardiovascular risk stratification",
          is_active: true,
        },
        {
          id: "cp-3",
          program_code: "ANC_MATERNAL",
          program_name: "Antenatal & Maternal Longitudinal Care",
          category: "maternal",
          description: "Trimester milestones and fetal growth surveillance",
          is_active: true,
        },
        {
          id: "cp-4",
          program_code: "CKD_RENAL",
          program_name: "Chronic Kidney Disease Care Program",
          category: "chronic",
          description: "eGFR progression monitoring and renal protection",
          is_active: true,
        },
      ]);
      setEnrolments([
        {
          id: "enr-1",
          facility_id: "fac-1",
          patient_id: "pat-1",
          patient_name: "Rajesh Sharma",
          patient_uhid: "HD-2026-00412",
          program_code: "DIABETES_T2",
          program_name: "Type 2 Diabetes Mellitus Care Program",
          enrolment_date: "2026-08-15",
          status: "active",
          target_outcomes: { target_hba1c: 7.0, target_bp: "130/80" },
          enrolled_by: "usr-1",
          created_at: new Date().toISOString(),
        },
        {
          id: "enr-2",
          facility_id: "fac-1",
          patient_id: "pat-2",
          patient_name: "Priya Devi",
          patient_uhid: "HD-2026-00583",
          program_code: "ANC_MATERNAL",
          program_name: "Antenatal & Maternal Longitudinal Care",
          enrolment_date: "2026-07-10",
          status: "active",
          target_outcomes: { gestational_age_weeks: 24, target_weight_gain_kg: 10 },
          enrolled_by: "usr-2",
          created_at: new Date().toISOString(),
        },
        {
          id: "enr-3",
          facility_id: "fac-1",
          patient_id: "pat-3",
          patient_name: "Sunita Verma",
          patient_uhid: "HD-2026-00391",
          program_code: "HYPERTENSION",
          program_name: "Essential Hypertension Care Program",
          enrolment_date: "2026-06-01",
          status: "active",
          target_outcomes: { target_systolic: 130, target_diastolic: 80 },
          enrolled_by: "usr-1",
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleEnrol = async () => {
    try {
      await enrolPatient({
        patient_id: enrolForm.patient_id,
        program_code: enrolForm.program_code,
        target_outcomes: {
          target_hba1c: enrolForm.target_hba1c,
          target_bp: enrolForm.target_bp,
        },
      });
      toast.success("Patient enrolled into care program successfully");
      setEnrolModalOpen(false);
      void loadData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to enrol patient");
    }
  };

  const handleRecordVisit = async () => {
    if (!activeEnrolment) return;
    try {
      await recordProgramVisit(activeEnrolment.id, {
        scheduled_date: visitForm.scheduled_date,
        completed_date: visitForm.scheduled_date,
        metrics: {
          hba1c: visitForm.hba1c,
          bp: `${visitForm.bp_systolic}/${visitForm.bp_diastolic}`,
          weight_kg: visitForm.weight_kg,
        },
        clinical_summary: visitForm.clinical_summary,
      });
      toast.success("Follow-up visit and indicators recorded");
      setVisitModalOpen(false);
      void loadData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to record visit");
    }
  };

  const handleOpenTimeline = async (enrolment: ProgramEnrolment) => {
    setActiveEnrolment(enrolment);
    try {
      const timeline = await getEnrolmentTimeline(enrolment.id);
      setActiveTimeline(timeline);
    } catch {
      setActiveTimeline({
        enrolment,
        visits: [
          {
            id: "v-1",
            enrolment_id: enrolment.id,
            scheduled_date: "2026-08-15",
            completed_date: "2026-08-15",
            status: "completed",
            metrics: { hba1c: 8.4, bp: "142/90", weight_kg: 76.0 },
            clinical_summary: "Baseline enrolment evaluation. Initiated lifestyle and oral hypoglycaemic therapy.",
            created_at: new Date().toISOString(),
          },
          {
            id: "v-2",
            enrolment_id: enrolment.id,
            scheduled_date: "2026-09-15",
            completed_date: "2026-09-15",
            status: "completed",
            metrics: { hba1c: 7.2, bp: "128/82", weight_kg: 74.5 },
            clinical_summary: "1-month trajectory review. HbA1c reduced by 1.2 points, BP target achieved.",
            created_at: new Date().toISOString(),
          },
        ],
      });
    }
    setTimelineModalOpen(true);
  };

  const handleExit = async () => {
    if (!activeEnrolment || !exitReason.trim()) return;
    try {
      await exitEnrolment(activeEnrolment.id, {
        exit_date: new Date().toISOString().slice(0, 10),
        exit_reason: exitReason.trim(),
      });
      toast.success("Patient discharged from program");
      setExitModalOpen(false);
      void loadData();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to exit program");
    }
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1380, mx: "auto" }}>
      {/* Header */}
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
            <MonitorHeartOutlinedIcon color="primary" sx={{ fontSize: 32 }} />
            <Typography variant="h5" sx={{ fontWeight: 800 }}>
              Longitudinal Care Programs & Registries
            </Typography>
            <Chip label="CHRONIC CARE & ANC" color="success" size="small" sx={{ fontWeight: 700 }} />
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Standardized registries for T2D, Hypertension, Maternal ANC, and CKD with clinical trajectory tracking.
          </Typography>
        </Box>

        <Box sx={{ display: "flex", gap: 1.5 }}>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadData} disabled={loading}>
            Refresh
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setEnrolModalOpen(true)}
            sx={{ fontWeight: 700 }}
          >
            Enrol Patient
          </Button>
        </Box>
      </Box>

      {/* Cohort Statistics */}
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
              ACTIVE ENROLMENTS
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#2e7d32" }}>
              {enrolments.filter((e) => e.status === "active").length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              DIABETES COHORT
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#1565c0" }}>
              {enrolments.filter((e) => e.program_code === "DIABETES_T2").length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              HYPERTENSION COHORT
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#e65100" }}>
              {enrolments.filter((e) => e.program_code === "HYPERTENSION").length}
            </Typography>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ borderRadius: 2 }}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
              MATERNAL ANC COHORT
            </Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, mt: 0.5, color: "#8e24aa" }}>
              {enrolments.filter((e) => e.program_code === "ANC_MATERNAL").length}
            </Typography>
          </CardContent>
        </Card>
      </Box>

      {/* Enrolments Table */}
      <TableContainer component={Card} variant="outlined" sx={{ borderRadius: 2 }}>
        <Table>
          <TableHead sx={{ bgcolor: "action.hover" }}>
            <TableRow>
              <TableCell sx={{ fontWeight: 700 }}>Patient</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Program Registry</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Enrolment Date</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Target Indicators</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>Status</TableCell>
              <TableCell align="right" sx={{ fontWeight: 700 }}>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {enrolments.map((enr) => (
              <TableRow key={enr.id} hover>
                <TableCell>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{enr.patient_name || "—"}</Typography>
                  <Typography variant="caption" color="text.secondary">{enr.patient_uhid || enr.patient_id.slice(0, 8)}</Typography>
                </TableCell>

                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>{enr.program_name}</Typography>
                  <Typography variant="caption" color="text.secondary">{enr.program_code}</Typography>
                </TableCell>

                <TableCell>
                  <Typography variant="body2">{enr.enrolment_date}</Typography>
                </TableCell>

                <TableCell>
                  {enr.target_outcomes ? (
                    <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap" }}>
                      {Object.entries(enr.target_outcomes).map(([k, v]) => (
                        <Chip
                          key={k}
                          label={`${k.replace("target_", "")}: ${v}`}
                          size="small"
                          variant="outlined"
                          sx={{ fontSize: "0.7rem" }}
                        />
                      ))}
                    </Box>
                  ) : (
                    <Typography variant="caption" color="text.secondary">Standard Protocol</Typography>
                  )}
                </TableCell>

                <TableCell>
                  {enr.status === "active" ? (
                    <Chip label="ACTIVE" color="success" size="small" sx={{ fontWeight: 700 }} />
                  ) : (
                    <Chip label={enr.status.toUpperCase()} size="small" />
                  )}
                </TableCell>

                <TableCell align="right">
                  <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
                    {enr.status === "active" && (
                      <Button
                        size="small"
                        variant="contained"
                        startIcon={<EventNoteIcon />}
                        onClick={() => {
                          setActiveEnrolment(enr);
                          setVisitModalOpen(true);
                        }}
                      >
                        Record Visit
                      </Button>
                    )}

                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<HistoryIcon />}
                      onClick={() => handleOpenTimeline(enr)}
                    >
                      Trajectory
                    </Button>

                    {enr.status === "active" && (
                      <Button
                        size="small"
                        color="error"
                        onClick={() => {
                          setActiveEnrolment(enr);
                          setExitModalOpen(true);
                        }}
                      >
                        Exit
                      </Button>
                    )}
                  </Box>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Enrol Patient Modal */}
      <Dialog open={enrolModalOpen} onClose={() => setEnrolModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>Enrol Patient in Longitudinal Care Program</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField
            label="Care Program Registry"
            select
            value={enrolForm.program_code}
            onChange={(e) => setEnrolForm({ ...enrolForm, program_code: e.target.value })}
            fullWidth
          >
            {programs.map((p) => (
              <MenuItem key={p.program_code} value={p.program_code}>
                {p.program_name} ({p.category})
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Target Indicator 1 (e.g. Target HbA1c / Gestational weeks)"
            value={enrolForm.target_hba1c}
            onChange={(e) => setEnrolForm({ ...enrolForm, target_hba1c: e.target.value })}
            fullWidth
          />

          <TextField
            label="Target Indicator 2 (e.g. Target BP mmHg)"
            value={enrolForm.target_bp}
            onChange={(e) => setEnrolForm({ ...enrolForm, target_bp: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setEnrolModalOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleEnrol} sx={{ fontWeight: 700 }}>
            Confirm Enrolment
          </Button>
        </DialogActions>
      </Dialog>

      {/* Record Follow-up Visit Modal */}
      <Dialog open={visitModalOpen} onClose={() => setVisitModalOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>Record Longitudinal Follow-up Visit</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Patient: {activeEnrolment?.patient_name} — {activeEnrolment?.program_name}
          </Typography>

          <TextField
            label="Visit Date"
            type="date"
            value={visitForm.scheduled_date}
            onChange={(e) => setVisitForm({ ...visitForm, scheduled_date: e.target.value })}
            fullWidth
          />

          <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 1.5 }}>
            <TextField
              label="HbA1c (%)"
              value={visitForm.hba1c}
              onChange={(e) => setVisitForm({ ...visitForm, hba1c: e.target.value })}
              fullWidth
            />
            <TextField
              label="BP Systolic"
              value={visitForm.bp_systolic}
              onChange={(e) => setVisitForm({ ...visitForm, bp_systolic: e.target.value })}
              fullWidth
            />
            <TextField
              label="BP Diastolic"
              value={visitForm.bp_diastolic}
              onChange={(e) => setVisitForm({ ...visitForm, bp_diastolic: e.target.value })}
              fullWidth
            />
          </Box>

          <TextField
            label="Weight (kg)"
            value={visitForm.weight_kg}
            onChange={(e) => setVisitForm({ ...visitForm, weight_kg: e.target.value })}
            fullWidth
          />

          <TextField
            label="Clinical Summary & Medication Adherence"
            multiline
            rows={3}
            value={visitForm.clinical_summary}
            onChange={(e) => setVisitForm({ ...visitForm, clinical_summary: e.target.value })}
            fullWidth
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setVisitModalOpen(false)}>Cancel</Button>
          <Button variant="contained" color="success" onClick={handleRecordVisit} sx={{ fontWeight: 700 }}>
            Commit Visit Metrics
          </Button>
        </DialogActions>
      </Dialog>

      {/* Trajectory / Timeline Modal */}
      <Dialog open={timelineModalOpen} onClose={() => setTimelineModalOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>
          Clinical Trajectory & Metric Timeline: {activeEnrolment?.patient_name}
        </DialogTitle>
        <DialogContent sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Program: {activeEnrolment?.program_name} | Enrolled: {activeEnrolment?.enrolment_date}
          </Typography>

          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {activeTimeline?.visits.map((v, idx) => (
              <Card key={v.id} variant="outlined" sx={{ borderRadius: 1.5, p: 2, bgcolor: "action.hover" }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    Visit Encounter #{idx + 1} — {v.completed_date || v.scheduled_date}
                  </Typography>
                  <Chip label="COMPLETED" size="small" color="success" sx={{ fontWeight: 700 }} />
                </Box>

                {v.metrics && (
                  <Box sx={{ display: "flex", gap: 1.5, flexWrap: "wrap", mb: 1 }}>
                    {Object.entries(v.metrics).map(([mk, mv]) => (
                      <Chip
                        key={mk}
                        label={`${mk.toUpperCase()}: ${mv}`}
                        size="small"
                        color="primary"
                        sx={{ fontWeight: 700 }}
                      />
                    ))}
                  </Box>
                )}

                <Typography variant="body2" color="text.primary">
                  {v.clinical_summary || "No clinical narrative recorded."}
                </Typography>
              </Card>
            ))}
          </Box>
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setTimelineModalOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Exit Program Dialog */}
      <Dialog open={exitModalOpen} onClose={() => setExitModalOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>Exit / Discharge from Program</DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <TextField
            label="Exit Reason"
            multiline
            rows={3}
            placeholder="e.g. Clinical targets achieved, transferred care, patient request..."
            value={exitReason}
            onChange={(e) => setExitReason(e.target.value)}
            fullWidth
            required
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setExitModalOpen(false)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleExit} sx={{ fontWeight: 700 }}>
            Confirm Exit
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
