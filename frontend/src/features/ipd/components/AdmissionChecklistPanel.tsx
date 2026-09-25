"use client";

import * as React from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import {
  getAdmissionChecklist,
  updateAdmissionChecklistTask,
  type AdmissionChecklistTask,
} from "@/features/ipd/api/ipd";

export interface AdmissionChecklistPanelProps {
  admissionId: string;
  onUpdate?: () => void;
}

export function AdmissionChecklistPanel({
  admissionId,
  onUpdate,
}: AdmissionChecklistPanelProps) {
  const { t } = useLocale();
  const [tasks, setTasks] = React.useState<AdmissionChecklistTask[]>([]);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [skipDialogOpen, setSkipDialogOpen] = React.useState<boolean>(false);
  const [selectedTask, setSelectedTask] = React.useState<AdmissionChecklistTask | null>(null);
  const [skipReason, setSkipReason] = React.useState<string>("");
  const [skipReasonError, setSkipReasonError] = React.useState<string | null>(null);
  const [updatingTaskId, setUpdatingTaskId] = React.useState<string | null>(null);

  const loadChecklist = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAdmissionChecklist(admissionId);
      setTasks(data || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("ipd.checklist.errLoad"));
    } finally {
      setLoading(false);
    }
  }, [admissionId]);

  React.useEffect(() => {
    loadChecklist();
  }, [loadChecklist]);

  const handleComplete = async (taskId: string) => {
    setUpdatingTaskId(taskId);
    setError(null);
    try {
      await updateAdmissionChecklistTask(admissionId, taskId, {
        status: "completed",
      });
      await loadChecklist();
      onUpdate?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("ipd.checklist.errUpdate"));
    } finally {
      setUpdatingTaskId(null);
    }
  };

  const openSkipModal = (task: AdmissionChecklistTask) => {
    setSelectedTask(task);
    setSkipReason("");
    setSkipReasonError(null);
    setSkipDialogOpen(true);
  };

  const handleConfirmSkip = async () => {
    if (!selectedTask) return;
    if (!skipReason.trim()) {
      setSkipReasonError(t("ipd.checklist.skipReasonRequired"));
      return;
    }
    setUpdatingTaskId(selectedTask.id);
    try {
      await updateAdmissionChecklistTask(admissionId, selectedTask.id, {
        status: "skipped",
        skipped_reason: skipReason.trim(),
      });
      setSkipDialogOpen(false);
      await loadChecklist();
      onUpdate?.();
    } catch (err: unknown) {
      setSkipReasonError(err instanceof Error ? err.message : t("ipd.checklist.errSkip"));
    } finally {
      setUpdatingTaskId(null);
    }
  };

  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const skippedCount = tasks.filter((t) => t.status === "skipped").length;
  const totalCount = tasks.length;
  const progressPercent = totalCount > 0 ? Math.round(((completedCount + skippedCount) / totalCount) * 100) : 0;

  return (
    <Box
      sx={{
        p: 2.5,
        borderRadius: "16px",
        backgroundColor: "#ffffff",
        border: `1px solid ${meridian.border}`,
        boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
      }}
    >
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between", mb: 2 }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>
            {t("ipd.checklist.title")}
          </Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {t("ipd.checklist.subtitle")}
          </Typography>
        </Box>
        <Box sx={{ textAlign: "right" }}>
          <Typography sx={{ fontSize: "0.875rem", fontWeight: 700, color: progressPercent === 100 ? "#16a34a" : "#0284c7" }}>
            {t("ipd.checklist.progress", { completed: completedCount, skipped: skippedCount, total: totalCount })}
          </Typography>
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
            {t("ipd.checklist.reconciled", { percent: progressPercent })}
          </Typography>
        </Box>
      </Stack>

      <Box sx={{ mb: 2.5 }}>
        <LinearProgress
          variant="determinate"
          value={progressPercent}
          sx={{
            height: 8,
            borderRadius: 4,
            backgroundColor: "#e2e8f0",
            "& .MuiLinearProgress-bar": {
              backgroundColor: progressPercent === 100 ? "#16a34a" : "#0284c7",
              borderRadius: 4,
            },
          }}
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary, py: 2, textAlign: "center" }}>
          {t("ipd.checklist.loading")}
        </Typography>
      ) : tasks.length === 0 ? (
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary, py: 2, textAlign: "center" }}>
          {t("ipd.checklist.empty")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {tasks.map((task) => {
            const isCompleted = task.status === "completed";
            const isSkipped = task.status === "skipped";
            const isPending = task.status === "pending";

            return (
              <Box
                key={task.id}
                sx={{
                  p: 2,
                  borderRadius: "12px",
                  border: `1px solid ${isCompleted ? "#bbf7d0" : isSkipped ? "#e2e8f0" : "#fed7aa"}`,
                  backgroundColor: isCompleted ? "#f0fdf4" : isSkipped ? "#f8fafc" : "#fff7ed",
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                  transition: "all 0.2s ease",
                }}
              >
                <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
                  <Box sx={{ flex: 1 }}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 0.5 }}>
                      <Typography sx={{ fontSize: "0.9375rem", fontWeight: 600 }}>
                        {task.title}
                      </Typography>
                      {task.is_mandatory && (
                        <Chip
                          size="small"
                          label={t("ipd.checklist.mandatory")}
                          sx={{
                            height: 20,
                            fontSize: "0.6875rem",
                            fontWeight: 700,
                            backgroundColor: "#fee2e2",
                            color: "#b91c1c",
                          }}
                        />
                      )}
                      <Chip
                        size="small"
                        label={task.category}
                        sx={{
                          height: 20,
                          fontSize: "0.6875rem",
                          backgroundColor: "#f1f5f9",
                          color: "#475569",
                        }}
                      />
                    </Stack>

                    {isCompleted && task.completed_by_name && (
                      <Typography sx={{ fontSize: "0.75rem", color: "#166534" }}>
                        {t("ipd.checklist.completedBy", {
                          name: task.completed_by_name,
                          time:
                            task.completed_at
                              ? new Date(task.completed_at).toLocaleTimeString([], {
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })
                              : "",
                        })}
                      </Typography>
                    )}

                    {isSkipped && (
                      <Box sx={{ mt: 0.5 }}>
                        <Typography sx={{ fontSize: "0.75rem", fontWeight: 600, color: "#64748b" }}>
                          {t("ipd.checklist.skipJustification")}
                        </Typography>
                        <Typography sx={{ fontSize: "0.8125rem", color: "#334155", fontStyle: "italic" }}>
                          &ldquo;{task.skipped_reason}&rdquo;
                        </Typography>
                      </Box>
                    )}
                  </Box>

                  <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                    {isPending ? (
                      <>
                        <Button
                          variant="contained"
                          size="small"
                          disabled={updatingTaskId === task.id}
                          onClick={() => handleComplete(task.id)}
                          sx={{
                            backgroundColor: "#16a34a",
                            "&:hover": { backgroundColor: "#15803d" },
                            fontSize: "0.75rem",
                            py: 0.5,
                            px: 1.5,
                          }}
                        >
                          {t("ipd.checklist.complete")}
                        </Button>
                        <Button
                          variant="outlined"
                          size="small"
                          disabled={updatingTaskId === task.id}
                          onClick={() => openSkipModal(task)}
                          sx={{
                            borderColor: "#cbd5e1",
                            color: "#64748b",
                            fontSize: "0.75rem",
                            py: 0.5,
                            px: 1.5,
                          }}
                        >
                          {t("ipd.checklist.skip")}
                        </Button>
                      </>
                    ) : (
                      <Chip
                        size="small"
                        label={isCompleted ? t("ipd.checklist.statusCompleted") : t("ipd.checklist.statusSkipped")}
                        color={isCompleted ? "success" : "default"}
                        sx={{ fontWeight: 600 }}
                      />
                    )}
                  </Stack>
                </Stack>
              </Box>
            );
          })}
        </Stack>
      )}

      {/* Skip Justification Modal */}
      <Dialog open={skipDialogOpen} onClose={() => setSkipDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>
          {t("ipd.checklist.skipDialogTitle")}
        </DialogTitle>
        <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
          <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>
            {t("ipd.checklist.skipDialogBody", { title: selectedTask?.title ?? "" })}
          </Typography>
          <TextField
            autoFocus
            fullWidth
            multiline
            rows={3}
            label={t("ipd.checklist.skipReasonLabel")}
            placeholder="e.g. Patient arriving in active seizure; baseline vitals deferred for immediate resuscitation"
            value={skipReason}
            onChange={(e) => {
              setSkipReason(e.target.value);
              if (skipReasonError) setSkipReasonError(null);
            }}
            error={Boolean(skipReasonError)}
            helperText={skipReasonError}
          />
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button variant="outlined" onClick={() => setSkipDialogOpen(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={updatingTaskId !== null}
            onClick={handleConfirmSkip}
          >
            {t("ipd.checklist.confirmSkip")}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
