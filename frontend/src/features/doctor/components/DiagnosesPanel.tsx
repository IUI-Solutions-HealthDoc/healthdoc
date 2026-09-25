"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { SearchAutocomplete } from "@/components/ui/SearchAutocomplete";
import { useLocale } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { DIAGNOSIS_TYPE_OPTIONS } from "../constants";
import { useDiagnoses } from "../hooks/useDiagnoses";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import type { ActiveEncounter, DiagnosisType, IcdConcept, IcdVersion } from "../types";

export interface DiagnosesPanelProps {
  encounter: ActiveEncounter;
}

const DIAGNOSIS_TYPE_KEYS: Record<DiagnosisType, MessageKey> = {
  provisional: "doctor.diagnosisType.provisional",
  final: "doctor.diagnosisType.final",
  differential: "doctor.diagnosisType.differential",
};

export function DiagnosesPanel({ encounter }: DiagnosesPanelProps) {
  const { t } = useLocale();
  const { rows, options, loading, search, addConcept, updateRow, setPrimary, removeRow, saving, save } =
    useDiagnoses(encounter);
  const [pick, setPick] = React.useState<IcdConcept | null>(null);
  const [system, setSystem] = React.useState<"all" | "icd10" | "icd11" | "snomed">("all");
  const [currentQuery, setCurrentQuery] = React.useState("");
  const pendingCount = rows.filter((row) => !row.persisted).length;
  const persistedPrimary = rows.some((row) => row.persisted && row.is_primary);

  const available = options.filter(
    (c) => !rows.some((r) => r.icd_code === c.code && r.icd_version === c.version),
  );

  const handleSystemChange = (newSys: "all" | "icd10" | "icd11" | "snomed") => {
    setSystem(newSys);
    if (currentQuery) {
      void search(currentQuery, newSys);
    }
  };

  const handleSearch = (q: string) => {
    setCurrentQuery(q);
    void search(q, system);
  };

  const formatSystemBadge = (ver: IcdVersion | string, code: string) => {
    if (ver === "snomed") return t("doctor.diagnosisBadgeSnomed", { code });
    if (ver === "icd10") return t("doctor.diagnosisBadgeIcd10", { code });
    return t("doctor.diagnosisBadgeIcd11", { code });
  };

  const systemFilters = [
    { id: "all" as const, label: t("doctor.diagnosesSystemAll") },
    { id: "icd10" as const, label: "ICD-10" },
    { id: "icd11" as const, label: "ICD-11" },
    { id: "snomed" as const, label: "SNOMED CT" },
  ];

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.diagnosesTitle")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {t("doctor.diagnosesSubtitle")}
          </Typography>
        </Box>
        <Button variant="outlined" size="small" sx={doctorButtonSx} disabled={pendingCount === 0 || loading || saving} onClick={save}>
          {saving ? t("doctor.statusSaving") : t("doctor.diagnosesSave")}
        </Button>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 0.75 }}>
        {systemFilters.map((s) => (
          <Box
            key={s.id}
            component="button"
            type="button"
            onClick={() => handleSystemChange(s.id)}
            sx={{
              px: 1.5,
              py: 0.5,
              borderRadius: "9999px",
              fontSize: "0.75rem",
              fontWeight: 600,
              cursor: "pointer",
              border: `1px solid ${system === s.id ? meridian.brandPrimary : meridian.border}`,
              backgroundColor: system === s.id ? meridian.brandPrimary : "transparent",
              color: system === s.id ? "#ffffff" : meridian.textSecondary,
              transition: "all 0.15s ease",
              "&:hover": {
                borderColor: meridian.brandPrimary,
              },
            }}
          >
            {s.label}
          </Box>
        ))}
      </Stack>

      <SearchAutocomplete<IcdConcept>
        label={t("doctor.diagnosesSearchLabel")}
        placeholder={t("doctor.diagnosesSearchPlaceholder")}
        options={available}
        value={pick}
        onChange={(c) => {
          if (c) addConcept(c);
          setPick(null);
        }}
        onInputChange={handleSearch}
        getOptionLabel={(c) => c.title}
        getOptionSubtext={(c) => formatSystemBadge(c.version, c.code)}
        isOptionEqualToValue={(a, b) => a.code === b.code && a.version === b.version}
      />

      {loading ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.diagnosesLoading")}
        </Typography>
      ) : rows.length === 0 ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.diagnosesEmpty")}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {rows.map((r) => (
            <Box
              key={r.tempId}
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
                <Badge variant="outline">{formatSystemBadge(r.icd_version, r.icd_code)}</Badge>
                {r.is_primary && <Badge variant="default">{t("doctor.diagnosisPrimaryBadge")}</Badge>}
                {r.persisted && <Badge variant="secondary">{t("doctor.diagnosisSavedBadge")}</Badge>}
                <Box sx={{ flex: 1 }} />
                {!r.persisted && (
                  <IconButton size="small" onClick={() => removeRow(r.tempId)} aria-label={t("doctor.diagnosisRemoveA11y")}>
                    ×
                  </IconButton>
                )}
              </Stack>

              <TextField
                label={t("doctor.diagnosisText")}
                value={r.diagnosis_text}
                onChange={(e) => updateRow(r.tempId, { diagnosis_text: e.target.value })}
                disabled={r.persisted}
                size="small"
                fullWidth
              />

              <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", gap: 1.5 }}>
                <TextField
                  select
                  label={t("doctor.diagnosisTypeLabel")}
                  value={r.diagnosis_type}
                  onChange={(e) => updateRow(r.tempId, { diagnosis_type: e.target.value as DiagnosisType })}
                  disabled={r.persisted}
                  size="small"
                  sx={{ minWidth: 160 }}
                >
                  {DIAGNOSIS_TYPE_OPTIONS.map((o) => (
                    <MenuItem key={o.value} value={o.value}>
                      {t(DIAGNOSIS_TYPE_KEYS[o.value])}
                    </MenuItem>
                  ))}
                </TextField>
                <Button
                  variant={r.is_primary ? "contained" : "outlined"}
                  size="small"
                  sx={doctorButtonSx}
                  disabled={r.persisted || r.is_primary || persistedPrimary}
                  onClick={() => setPrimary(r.tempId)}
                >
                  {r.is_primary ? t("doctor.diagnosisPrimaryLabel") : t("doctor.diagnosisSetPrimary")}
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}
