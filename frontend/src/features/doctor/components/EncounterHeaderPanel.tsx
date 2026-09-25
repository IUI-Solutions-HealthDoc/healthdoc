"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { useLocale, type MessageKey } from "@/lib/i18n";
import { ENCOUNTER_TYPE_OPTIONS } from "../constants";
import { formatAgeSex, formatTime } from "../lib/formatters";
import { doctorPanelSx } from "../panelSx";
import type { EncounterContext, EncounterType } from "../types";

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Box>
      <Typography
        sx={{
          fontSize: "0.6875rem",
          fontWeight: 600,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: meridian.textSecondary,
        }}
      >
        {label}
      </Typography>
      <Typography sx={{ fontSize: "0.875rem", fontWeight: 600, mt: 0.25 }}>{value}</Typography>
    </Box>
  );
}

export interface EncounterHeaderPanelProps {
  context: EncounterContext;
  startedAt: string;
  encounterType: EncounterType;
  onEncounterTypeChange: (value: EncounterType) => void;
}

export function EncounterHeaderPanel({
  context,
  startedAt,
  encounterType,
  onEncounterTypeChange,
}: EncounterHeaderPanelProps) {
  const { t, localizeField } = useLocale();
  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{context.patient_name}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {formatAgeSex(context.age_years, context.sex)} · UHID {context.uhid} · Token {context.token_display}
          </Typography>
        </Box>
        <TextField
          select
          size="small"
          label={t("doctor.encounterType")}
          value={encounterType}
          onChange={(e) => onEncounterTypeChange(e.target.value as EncounterType)}
          sx={{ minWidth: 190 }}
        >
          {ENCOUNTER_TYPE_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {t(("doctor.encounterType." + o.value) as MessageKey)}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Stack direction="row" spacing={4} useFlexGap sx={{ flexWrap: "wrap" }}>
        <Meta label={t("common.doctor")} value={context.provider_name} />
        <Meta
          label={t("receptionist.department")}
          value={localizeField(context.department, context.department_hi)}
        />
        <Meta label={t("doctor.visitId")} value={context.visit_id} />
        <Meta label={t("doctor.startedAt")} value={formatTime(startedAt)} />
      </Stack>
    </Box>
  );
}
