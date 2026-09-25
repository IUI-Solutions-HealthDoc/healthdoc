"use client";

import Box from "@mui/material/Box";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { doctorPanelSx } from "../panelSx";

export interface ChiefComplaintPanelProps {
  value: string;
  onChange: (value: string) => void;
}

export function ChiefComplaintPanel({ value, onChange }: ChiefComplaintPanelProps) {
  const { t } = useLocale();
  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 1.5 }}>
      <Box>
        <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.chiefComplaintTitle")}</Typography>
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
          {t("doctor.chiefComplaintSubtitle")}
        </Typography>
      </Box>
      <TextField
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("doctor.chiefComplaintPlaceholder")}
        multiline
        minRows={2}
        fullWidth
      />
    </Box>
  );
}
