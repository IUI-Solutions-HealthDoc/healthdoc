"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { meridian } from "@/styles/theme";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { usePrescription } from "../hooks/usePrescription";
import { formatAgeSex } from "../lib/formatters";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import type { ActiveEncounter, EncounterContext } from "../types";
import { MedicineSearchModal } from "./MedicineSearchModal";
import { PrescriptionItemRow } from "./PrescriptionItemRow";
import { PrescriptionPrintView } from "./PrescriptionPrintView";
import { SafetyBanner } from "./SafetyBanner";
import { ALLERGY_OVERRIDE_REASON_MIN } from "../constants";
import { useLocale } from "@/lib/i18n";

import "../prescription-print.css";

export interface PrescriptionWorkspaceProps {
  context: EncounterContext;
  /** The encounter this prescription belongs to — prescriptions.encounter_id. */
  encounter: ActiveEncounter;
}

/** Week 4 — e-Prescription: search, dosage/frequency/route, SOS, safety banners, print. */
export function PrescriptionWorkspace({ context, encounter }: PrescriptionWorkspaceProps) {
  const { user: currentUser } = useCurrentUser();
  const {
    items,
    notes,
    setNotes,
    alerts,
    checking,
    hasBlocking,
    needsOverride,
    overrideReason,
    setOverrideReason,
    overrideOk,
    saving,
    addMedicine,
    updateItem,
    removeItem,
    save,
  } = usePrescription(encounter, context);

  const [pickOpen, setPickOpen] = React.useState(false);
  const { t, localizeField } = useLocale();
  const facilityName = localizeField(
    currentUser?.facility.name ?? "",
    currentUser?.facility.name_hi,
  );

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
        <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
          <Box>
            <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.prescription")}</Typography>
            <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
              {context.patient_name} · {formatAgeSex(context.age_years, context.sex)} · UHID {context.uhid} · Token{" "}
              {context.token_display}
            </Typography>
          </Box>
          <Button variant="outlined" size="small" sx={doctorButtonSx} onClick={() => setPickOpen(true)}>
            {t("doctor.addMedicine")}
          </Button>
        </Stack>

        <SafetyBanner alerts={alerts} checking={checking} />

        {needsOverride && !hasBlocking && (
          <TextField
            label={t("doctor.allergyOverrideLabel")}
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            multiline
            minRows={2}
            fullWidth
            error={!overrideOk && overrideReason.length > 0}
            helperText={
              overrideOk
                ? t("doctor.allergyOverrideOk")
                : t("doctor.allergyOverrideChars", {
                    count: ALLERGY_OVERRIDE_REASON_MIN - overrideReason.trim().length,
                  })
            }
          />
        )}

        {items.length === 0 ? (
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {t("doctor.noMedicinesYet")}
          </Typography>
        ) : (
          <Stack spacing={1.5}>
            {items.map((it) => (
              <PrescriptionItemRow
                key={it.tempId}
                item={it}
                onChange={(patch) => updateItem(it.tempId, patch)}
                onRemove={() => removeItem(it.tempId)}
              />
            ))}
          </Stack>
        )}

        <TextField
          label={t("doctor.prescriptionNotesOptional")}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          multiline
          minRows={2}
          fullWidth
        />
      </Box>

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
          <Typography sx={{ fontSize: "0.8125rem", color: hasBlocking ? meridian.danger : meridian.textSecondary }}>
            {items.length === 1
              ? t("doctor.medicineCount", { count: items.length })
              : t("doctor.medicineCountPlural", { count: items.length })}
            {hasBlocking
              ? t("doctor.anaphylaxisBlock")
              : !overrideOk
                ? t("doctor.allergyReasonRequired")
                : ""}
          </Typography>
          <Stack direction="row" spacing={1.5}>
            <Button
              variant="outlined"
              sx={doctorButtonSx}
              disabled={items.length === 0 || !currentUser?.facility.name}
              onClick={() => window.print()}
            >
              {t("doctor.printPdf")}
            </Button>
            <Button
              variant="contained"
              sx={doctorButtonSx}
              disabled={items.length === 0 || saving || hasBlocking || !overrideOk}
              onClick={save}
            >
              {saving ? t("doctor.statusSaving") : t("doctor.savePrescription")}
            </Button>
          </Stack>
        </Stack>
      </Box>

      <MedicineSearchModal open={pickOpen} onClose={() => setPickOpen(false)} onPick={addMedicine} />
      <PrescriptionPrintView
        facilityName={facilityName}
        context={context}
        items={items}
        notes={notes}
        allergyNames={alerts
          .filter((a) => a.kind !== "uncheckable")
          .map((a) => a.allergy?.substance_text)
          .filter((s): s is string => Boolean(s))}
      />
    </Box>
  );
}
