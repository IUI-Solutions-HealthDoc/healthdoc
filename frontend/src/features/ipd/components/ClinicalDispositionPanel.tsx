"use client";

import * as React from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { meridian } from "@/styles/theme";
import { doctorPanelSx, doctorButtonSx } from "@/features/doctor/panelSx";
import type { ActiveEncounter, EncounterContext } from "@/features/doctor/types";
import {
  createClinicalDisposition,
  getWards,
  type ClinicalDisposition,
} from "@/features/ipd/api/ipd";
import type { Ward } from "@/features/nurse/components/WardSelector/WardSelector.types";

export interface ClinicalDispositionPanelProps {
  context: EncounterContext;
  encounter: ActiveEncounter;
}

export function ClinicalDispositionPanel({
  context,
  encounter,
}: ClinicalDispositionPanelProps) {
  const [dispositionType, setDispositionType] = React.useState<
    "admit" | "discharge" | "transfer" | "follow_up"
  >("admit");
  const [priority, setPriority] = React.useState<"routine" | "urgent" | "emergency">("routine");
  const [recommendedWardId, setRecommendedWardId] = React.useState<string>("");
  const [reason, setReason] = React.useState<string>("");
  const [notes, setNotes] = React.useState<string>("");
  const [wards, setWards] = React.useState<Ward[]>([]);
  const [loadingWards, setLoadingWards] = React.useState<boolean>(false);
  const [saving, setSaving] = React.useState<boolean>(false);
  const [savedDisposition, setSavedDisposition] = React.useState<ClinicalDisposition | null>(null);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    setLoadingWards(true);
    getWards()
      .then((data) => {
        if (active) {
          setWards(data || []);
        }
      })
      .catch((err) => {
        console.error("Failed to load wards:", err);
      })
      .finally(() => {
        if (active) setLoadingWards(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async () => {
    setSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const disp = await createClinicalDisposition({
        patient_id: context.patient_id,
        visit_id: context.visit_id,
        encounter_id: encounter.id,
        disposition_type: dispositionType,
        priority,
        recommended_ward_id: recommendedWardId ? recommendedWardId : null,
        reason: reason.trim() || null,
        notes: notes.trim() || null,
      });
      setSavedDisposition(disp);
      setSuccessMessage(
        dispositionType === "admit"
          ? "Inpatient admission order recorded. Patient has been queued to 'To Admit'."
          : "Clinical disposition recorded successfully."
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to record clinical disposition";
      setErrorMessage(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>
            Clinical Disposition & Handover (HD-13)
          </Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            Direct the patient to IPD admission, safe discharge, inter-facility transfer, or outpatient follow-up.
          </Typography>
        </Box>
        {savedDisposition && (
          <Chip
            size="small"
            label={`Disposition: ${savedDisposition.disposition_type.toUpperCase()} (${savedDisposition.status})`}
            color={savedDisposition.disposition_type === "admit" ? "primary" : "default"}
            sx={{ fontWeight: 600 }}
          />
        )}
      </Stack>

      {errorMessage && (
        <Alert severity="error" onClose={() => setErrorMessage(null)}>
          {errorMessage}
        </Alert>
      )}

      {successMessage && (
        <Alert severity="success" onClose={() => setSuccessMessage(null)}>
          {successMessage}
        </Alert>
      )}

      {/* Disposition Type Selection */}
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        {(
          [
            { key: "admit", label: "Admit to Ward (IPD)" },
            { key: "discharge", label: "Discharge / Home" },
            { key: "transfer", label: "Transfer to Another Facility" },
            { key: "follow_up", label: "Routine Follow-up Only" },
          ] as const
        ).map((item) => {
          const isSelected = dispositionType === item.key;
          return (
            <Button
              key={item.key}
              variant={isSelected ? "contained" : "outlined"}
              size="small"
              onClick={() => setDispositionType(item.key)}
              sx={{
                ...doctorButtonSx,
                textTransform: "none",
                borderRadius: "8px",
                fontWeight: isSelected ? 600 : 500,
                ...(isSelected && {
                  boxShadow: "0 2px 8px rgba(0, 31, 84, 0.15)",
                }),
              }}
            >
              {item.label}
            </Button>
          );
        })}
      </Stack>

      {/* When Admit is selected */}
      {dispositionType === "admit" && (
        <Box
          sx={{
            p: 2,
            borderRadius: "12px",
            backgroundColor: "#f8fafc",
            border: `1px solid ${meridian.border}`,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {/* Priority selector */}
          <Box>
            <Typography sx={{ fontSize: "0.8125rem", fontWeight: 600, mb: 1 }}>
              Admission Priority
            </Typography>
            <Stack direction="row" spacing={1}>
              {(
                [
                  { key: "routine", label: "Routine", color: "#3b82f6" },
                  { key: "urgent", label: "Urgent", color: "#f59e0b" },
                  { key: "emergency", label: "Emergency / STAT", color: "#ef4444" },
                ] as const
              ).map((p) => {
                const isSelected = priority === p.key;
                return (
                  <Chip
                    key={p.key}
                    label={p.label}
                    onClick={() => setPriority(p.key)}
                    variant={isSelected ? "filled" : "outlined"}
                    sx={{
                      cursor: "pointer",
                      fontWeight: 600,
                      borderColor: p.color,
                      ...(isSelected && {
                        backgroundColor: p.color,
                        color: "#ffffff",
                        "&:hover": { backgroundColor: p.color },
                      }),
                    }}
                  />
                );
              })}
            </Stack>
          </Box>

          {/* Recommended Ward */}
          <TextField
            select
            fullWidth
            size="small"
            label="Recommended Ward"
            value={recommendedWardId}
            onChange={(e) => setRecommendedWardId(e.target.value)}
            helperText={loadingWards ? "Loading available wards..." : "Select the target nursing unit / ward"}
          >
            <MenuItem value="">
              <em>-- Unassigned / Any Available Ward --</em>
            </MenuItem>
            {wards.map((ward) => (
              <MenuItem key={ward.id} value={ward.id}>
                {ward.name}
              </MenuItem>
            ))}
          </TextField>

          {/* Reason for Admission */}
          <TextField
            fullWidth
            size="small"
            label="Admission Indication / Primary Reason"
            placeholder="e.g. Acute severe asthma exacerbation; requires oxygen therapy and nebulization"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />

          {/* Nursing Handover Notes */}
          <TextField
            fullWidth
            multiline
            rows={2}
            size="small"
            label="Clinical Handover Notes for Inpatient Nursing"
            placeholder="e.g. Strict intake/output monitoring, fall precautions, check vitals q2h"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Box>
      )}

      {/* When other disposition types are selected */}
      {dispositionType !== "admit" && (
        <Box
          sx={{
            p: 2,
            borderRadius: "12px",
            backgroundColor: "#f8fafc",
            border: `1px solid ${meridian.border}`,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <TextField
            fullWidth
            size="small"
            label="Clinical Justification / Instructions"
            placeholder="e.g. Patient improved; continue oral medication and review in OPD after 7 days"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <TextField
            fullWidth
            multiline
            rows={2}
            size="small"
            label="Additional Disposition Notes"
            placeholder="e.g. Red flag symptoms discussed with patient and attendant"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Box>
      )}

      <Stack direction="row" spacing={2} sx={{ justifyContent: "flex-end" }}>
        <Button
          variant="contained"
          size="small"
          disabled={saving}
          onClick={handleSubmit}
          sx={{ ...doctorButtonSx, minWidth: "160px" }}
        >
          {saving ? "Recording..." : "Record Disposition"}
        </Button>
      </Stack>
    </Box>
  );
}
