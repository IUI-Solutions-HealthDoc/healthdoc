"use client";

import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Badge } from "@/components/ui/Badge";
import { meridian } from "@/styles/theme";
import { FREQUENCIES_WITHOUT_DURATION, FREQUENCY_OPTIONS, ROUTE_OPTIONS } from "../constants";
import type { DraftPrescriptionItem, FrequencyCode, RouteCode } from "../types";
import { useLocale } from "@/lib/i18n";

export interface PrescriptionItemRowProps {
  item: DraftPrescriptionItem;
  onChange: (patch: Partial<DraftPrescriptionItem>) => void;
  onRemove: () => void;
}

export function PrescriptionItemRow({ item, onChange, onRemove }: PrescriptionItemRowProps) {
  const { t } = useLocale();
  const noDuration = FREQUENCIES_WITHOUT_DURATION.includes(item.frequency as never);

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: "12px",
        border: `1px solid ${meridian.border}`,
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
      }}
    >
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1, alignItems: "center" }}>
        <Typography sx={{ fontSize: "0.9375rem", fontWeight: 700 }}>{item.medicine_name}</Typography>
        {item.strength && (
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>{item.strength}</Typography>
        )}
        {item.is_controlled_drug && <Badge variant="destructive">{t("doctor.ui.controlled")}</Badge>}
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={onRemove} aria-label={t("doctor.ui.removeMedicine")}>
          ×
        </IconButton>
      </Stack>

      <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", gap: 1.5 }}>
        <TextField
          label={t("common.ui.dosage")}
          placeholder={t("doctor.ui.eG1Tab")}
          value={item.dosage}
          onChange={(e) => onChange({ dosage: e.target.value })}
          size="small"
          sx={{ minWidth: 130 }}
        />
        <TextField
          select
          label={t("doctor.ui.frequency")}
          value={item.frequency}
          onChange={(e) => onChange({ frequency: e.target.value as FrequencyCode })}
          size="small"
          sx={{ minWidth: 200 }}
        >
          {FREQUENCY_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label={t("doctor.ui.duration")}
          type="number"
          value={noDuration ? "" : item.duration_days ?? ""}
          onChange={(e) =>
            onChange({ duration_days: e.target.value === "" ? undefined : Number(e.target.value) })
          }
          size="small"
          disabled={noDuration}
          helperText={noDuration ? t("doctor.ui.asNeeded") : "days"}
          sx={{ width: 120 }}
        />
        <TextField
          select
          label={t("immunization.col.route")}
          value={item.route}
          onChange={(e) => onChange({ route: e.target.value as RouteCode })}
          size="small"
          sx={{ minWidth: 170 }}
        >
          {ROUTE_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <TextField
        label={t("doctor.ui.instructionsOptional")}
        placeholder={t("doctor.ui.eGAfterFood")}
        value={item.instructions ?? ""}
        onChange={(e) => onChange({ instructions: e.target.value })}
        size="small"
        fullWidth
      />
    </Box>
  );
}
