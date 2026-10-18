"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { useVitals, type VitalsForm } from "../hooks/useVitals";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import type { ActiveEncounter } from "../types";
import type { MessageKey } from "@/lib/i18n";

const gridSx = { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 2 } as const;

const VITAL_LABEL_KEYS: Record<keyof VitalsForm, MessageKey> = {
  temp_c: "doctor.vitalTemp",
  pulse_bpm: "doctor.vitalPulse",
  resp_rate: "doctor.vitalRespRate",
  spo2_pct: "doctor.vitalSpo2",
  bp_systolic: "doctor.vitalBpSystolic",
  bp_diastolic: "doctor.vitalBpDiastolic",
  pain_score: "doctor.vitalPainScore",
  height_cm: "doctor.vitalHeight",
  weight_kg: "doctor.vitalWeight",
  waist_cm: "doctor.vitalWaist",
  hip_cm: "doctor.vitalHip",
};

export interface VitalsPanelProps {
  encounter: ActiveEncounter;
}

export function VitalsPanel({ encounter }: VitalsPanelProps) {
  const { t } = useLocale();
  const { form, setField, bmi, whr, anyEntered, saving, record, history, historyFailed, errors } = useVitals(encounter);

  // The unit is part of the label: as an end adornment inside a quarter-width
  // field it ran into the label text (QA 12 Oct 2026).
  const field = (key: keyof VitalsForm, unit?: string) => (
    <TextField
      label={unit ? `${t(VITAL_LABEL_KEYS[key])} (${unit})` : t(VITAL_LABEL_KEYS[key])}
      value={form[key]}
      onChange={(e) => setField(key, e.target.value)}
      size="small"
      type="number"
      error={Boolean(errors[key])}
      helperText={errors[key] ? t("doctor.vitalAllowed", { range: errors[key] as string }) : undefined}
      slotProps={{ inputLabel: { shrink: true } }}
    />
  );
  const latest = (history ?? []).slice(0, 3);
  const show = (v: string | number | null) => (v === null || v === "" ? "—" : String(v));

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.vitalsTitle")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {t("doctor.vitalsSubtitle")}
          </Typography>
        </Box>
        <Button variant="outlined" size="small" sx={doctorButtonSx} disabled={!anyEntered || saving} onClick={record}>
          {saving ? t("doctor.vitalsRecording") : t("doctor.vitalsRecord")}
        </Button>
      </Stack>

      <Box sx={gridSx}>
        {field("temp_c", "°C")}
        {field("pulse_bpm", "bpm")}
        {field("resp_rate", "/min")}
        {field("spo2_pct", "%")}
        {field("bp_systolic", "mmHg")}
        {field("bp_diastolic", "mmHg")}
        {field("pain_score", "/10")}
      </Box>

      <Typography sx={{ fontSize: "0.75rem", fontWeight: 600, color: meridian.textSecondary, mt: 0.5 }}>
        {t("doctor.vitalsAnthropometry")}
      </Typography>
      <Box sx={gridSx}>
        {field("height_cm", "cm")}
        {field("weight_kg", "kg")}
        {field("waist_cm", "cm")}
        {field("hip_cm", "cm")}
      </Box>

      <Stack direction="row" spacing={3} sx={{ mt: 0.5 }}>
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.vitalsBmiAuto")}: <strong>{bmi ?? "—"}</strong>
        </Typography>
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.vitalsWhrAuto")}: <strong>{whr ?? "—"}</strong>
        </Typography>
      </Stack>

      <Box>
        <Typography sx={{ fontSize: "0.75rem", fontWeight: 600, color: meridian.textSecondary, mb: 0.5 }}>
          {t("doctor.vitalsRecent")}
        </Typography>
        {historyFailed ? (
          <Typography sx={{ fontSize: "0.8125rem", color: "error.main" }}>{t("doctor.vitalsHistoryFailed")}</Typography>
        ) : history === null ? (
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("common.loading")}</Typography>
        ) : latest.length === 0 ? (
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("doctor.vitalsNoneYet")}</Typography>
        ) : (
          <Box component="table" sx={{ width: "100%", fontSize: "0.8125rem", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["", "°C", "bpm", "/min", "SpO₂ %", "BP mmHg", "kg", "BMI"].map((h) => (
                  <Box component="th" key={h} sx={{ textAlign: "left", fontWeight: 600, color: meridian.textSecondary, pr: 1 }}>{h}</Box>
                ))}
              </tr>
            </thead>
            <tbody>
              {latest.map((v) => (
                <tr key={v.id}>
                  <Box component="td" sx={{ pr: 1, whiteSpace: "nowrap" }}>{formatDateTime(v.measured_at)}</Box>
                  <td>{show(v.temp_c)}</td>
                  <td>{show(v.pulse_bpm)}</td>
                  <td>{show(v.resp_rate)}</td>
                  <td>{show(v.spo2_pct)}</td>
                  <td>{v.bp_systolic !== null && v.bp_diastolic !== null ? `${v.bp_systolic}/${v.bp_diastolic}` : "—"}</td>
                  <td>{show(v.weight_kg)}</td>
                  <td>{show(v.bmi)}</td>
                </tr>
              ))}
            </tbody>
          </Box>
        )}
      </Box>
    </Box>
  );
}
