"use client";

import { useRef, useState } from "react";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { useConsultation } from "../hooks/useConsultation";
import { doctorButtonSx } from "../panelSx";
import type { EncounterContext } from "../types";
import { ChiefComplaintPanel } from "./ChiefComplaintPanel";
import { DiagnosesPanel } from "./DiagnosesPanel";
import { EncounterHeaderPanel } from "./EncounterHeaderPanel";
import { OrdersPanel } from "./OrdersPanel";
import { PatientAllergyBanner } from "./PatientAllergyBanner";
import { PrescriptionWorkspace } from "./PrescriptionWorkspace";
import { SoapNotePanel } from "./SoapNotePanel";
import { SpecialtyEncounterPanel } from "./SpecialtyEncounterPanel";
import { StaleWritePanel } from "./StaleWritePanel";
import { VitalsPanel } from "./VitalsPanel";
import { ClinicalDispositionPanel } from "@/features/ipd/components/ClinicalDispositionPanel";
import { useLocale } from "@/lib/i18n";

export interface ConsultationWorkspaceProps {
  context: EncounterContext;
}

/**
 * Week 3 consultation — single-purpose panels + a sticky bar for the encounter
 * row. Owns only encounters columns (encounter_type + chief_complaint); vitals,
 * diagnoses and orders each own their state and their own save. SOAP is saved
 * on the PATCH; vitals stay their own table.
 */
export function ConsultationWorkspace({ context }: ConsultationWorkspaceProps) {
  const {
    encounter,
    startedAt,
    loading,
    encounterType,
    setEncounterType,
    chiefComplaint,
    setChiefComplaint,
    status,
    saving,
    completing,
    canComplete,
    canWriteChildren,
    saveEncounter,
    soap,
    patchSoap,
    noteStatus,
    conflict,
    dirty,
    autoSaveStatus,
    complete,
  } = useConsultation(context);
  const { t } = useLocale();

  const ended = status === "completed";
  // Save with an empty chief complaint said nothing on the page itself
  // (QA 10 Oct 2026): the field now says why and takes the focus.
  const [complaintError, setComplaintError] = useState<string | null>(null);
  const complaintRef = useRef<HTMLTextAreaElement>(null);
  const save = () => {
    if (chiefComplaint.trim() === "") {
      setComplaintError(t("doctor.toast.chiefComplaintRequired"));
      complaintRef.current?.focus();
      return;
    }
    setComplaintError(null);
    void saveEncounter();
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <PatientAllergyBanner patientId={context.patient_id} />
      <EncounterHeaderPanel
        context={context}
        startedAt={startedAt}
        encounterType={encounterType}
        onEncounterTypeChange={setEncounterType}
      />
      <ChiefComplaintPanel
        value={chiefComplaint}
        onChange={(value) => {
          setChiefComplaint(value);
          if (value.trim()) setComplaintError(null);
        }}
        error={complaintError}
        inputRef={complaintRef}
        readOnly={ended}
      />
      {conflict && <StaleWritePanel yours={soap} theirs={conflict} />}
      <SoapNotePanel value={soap} noteStatus={noteStatus} onChange={patchSoap} readOnly={ended} />
      {canWriteChildren && encounter ? (
        <>
          <VitalsPanel encounter={encounter} />
          <DiagnosesPanel encounter={encounter} />
          <SpecialtyEncounterPanel encounter={encounter} />
          <OrdersPanel encounter={encounter} patientLabel={`${context.patient_name} · ${context.uhid || context.patient_id}`} />
          <PrescriptionWorkspace context={context} encounter={encounter} />
          <ClinicalDispositionPanel context={context} encounter={encounter} />
        </>
      ) : !ended ? (
        <Alert severity="info">{t("doctor.saveBeforeChildren")}</Alert>
      ) : null}

      <Box
        sx={{
          borderRadius: "16px",
          border: `1px solid ${meridian.border}`,
          backgroundColor: meridian.surface,
          boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
          px: 3,
          py: 2,
        }}
      >
        <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
            <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("doctor.encounter")}</Typography>
            {ended ? (
              <StatusChip status="completed" label={t("doctor.statusCompleted")} />
            ) : saving || autoSaveStatus === "saving" ? (
              <StatusChip status="pending" label={t("doctor.statusSaving")} />
            ) : autoSaveStatus === "failed" ? (
              <StatusChip status="failed" label={t("doctor.statusAutosaveFailed")} />
            ) : dirty ? (
              <StatusChip status="draft" label={t("doctor.statusUnsavedChanges")} />
            ) : status === "saved" ? (
              <StatusChip status="issued" label={t("doctor.statusSavedToServer")} />
            ) : (
              <StatusChip status="draft" label={t("doctor.statusNotSaved")} />
            )}
          </Stack>
          <Stack direction="row" spacing={1.5}>
            {/* Visually hidden live region. In sx, width: 1 means 100%, so this
                sat off-screen 735 px wide and gave the page a permanent
                horizontal scrollbar (QA 10 Oct 2026); 1px is what was meant. */}
            <Typography aria-live="polite" sx={{ position: "absolute", width: "1px", height: "1px", overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap" }}>
              {saving
                ? t("doctor.a11ySavingConsultation")
                : dirty
                  ? t("doctor.a11yConsultationUnsaved")
                  : t("doctor.a11yConsultationSaved")}
            </Typography>
            <Button variant="contained" sx={doctorButtonSx} disabled={loading || saving || ended} onClick={save}>
              {saving ? t("doctor.statusSaving") : t("doctor.saveEncounter")}
            </Button>
            <Button variant="outlined" sx={doctorButtonSx} disabled={!canComplete || completing || ended} onClick={complete}>
              {completing ? t("doctor.completing") : t("doctor.completeConsultation")}
            </Button>
          </Stack>
        </Stack>
      </Box>
    </Box>
  );
}
