"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";

import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import {
  getSpecialtyTemplates,
  getEncounterSpecialty,
  saveEncounterSpecialty,
  type SpecialtyTemplate,
  type SpecialtyTemplateField,
  type SpecialtyAssessmentRecord,
} from "../api";
import type { ActiveEncounter } from "../types";

export interface SpecialtyEncounterPanelProps {
  encounter: ActiveEncounter;
}

export function SpecialtyEncounterPanel({ encounter }: SpecialtyEncounterPanelProps) {
  const { t } = useLocale();
  const [templates, setTemplates] = React.useState<SpecialtyTemplate[]>([]);
  const [selectedType, setSelectedType] = React.useState<string>("pediatric");
  const [formData, setFormData] = React.useState<Record<string, unknown>>({});
  const [savedRecord, setSavedRecord] = React.useState<SpecialtyAssessmentRecord | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);

  // Load templates and existing assessment
  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getSpecialtyTemplates(), getEncounterSpecialty(encounter.id)])
      .then(([tmplList, existing]) => {
        if (cancelled) return;
        setTemplates(tmplList);
        if (existing) {
          setSavedRecord(existing);
          setSelectedType(existing.specialty_type);
          setFormData(existing.clinical_data || {});
        } else if (tmplList.length > 0) {
          setSelectedType(tmplList[0].specialty_type);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(err instanceof Error ? err.message : t("doctor.toast.loadSpecialtyTemplatesFailed"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [encounter.id, t]);

  const activeTemplate = templates.find((t) => t.specialty_type === selectedType);

  const handleFieldChange = (fieldName: string, val: unknown) => {
    setFormData((prev) => ({
      ...prev,
      [fieldName]: val,
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const record = await saveEncounterSpecialty(encounter.id, selectedType, formData);
      setSavedRecord(record);
      toast.success(
        t("doctor.toast.specialtyAssessmentSaved", {
          title: activeTemplate?.title ?? "Specialty",
        }),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("doctor.toast.saveSpecialtyAssessmentFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleTypeSelect = (type: string) => {
    if (type === selectedType) return;
    setSelectedType(type);
    if (savedRecord && savedRecord.specialty_type === type) {
      setFormData(savedRecord.clinical_data || {});
    } else {
      setFormData({});
    }
  };

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.specialtyTitle")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>
            {t("doctor.specialtySubtitle")}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          {savedRecord && savedRecord.specialty_type === selectedType && (
            <Badge variant="secondary">{t("doctor.diagnosisSavedBadge")}</Badge>
          )}
          <Button
            variant="contained"
            size="small"
            sx={doctorButtonSx}
            disabled={loading || saving}
            onClick={() => void handleSave()}
          >
            {saving ? t("doctor.statusSaving") : t("doctor.specialtySaveAssessment")}
          </Button>
        </Stack>
      </Stack>

      {/* Specialty Switcher Tabs */}
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        {[
          { id: "pediatric", label: t("doctor.specialtyPediatric"), icon: "🧸" },
          { id: "cardiology", label: t("doctor.specialtyCardiology"), icon: "❤️" },
          { id: "obstetrics", label: t("doctor.specialtyObstetrics"), icon: "🤰" },
        ].map((spec) => {
          const isSelected = selectedType === spec.id;
          return (
            <Box
              key={spec.id}
              component="button"
              type="button"
              onClick={() => handleTypeSelect(spec.id)}
              sx={{
                px: 2,
                py: 1,
                borderRadius: "8px",
                fontSize: "0.8125rem",
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 1,
                border: `1px solid ${isSelected ? meridian.brandPrimary : meridian.border}`,
                backgroundColor: isSelected ? `${meridian.brandPrimary}12` : "transparent",
                color: isSelected ? meridian.brandPrimary : meridian.textSecondary,
                transition: "all 0.15s ease",
                "&:hover": {
                  borderColor: meridian.brandPrimary,
                },
              }}
            >
              <span>{spec.icon}</span>
              <span>{spec.label}</span>
            </Box>
          );
        })}
      </Stack>

      {loading ? (
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary }}>
          {t("doctor.specialtyLoadingTemplate")}
        </Typography>
      ) : activeTemplate ? (
        <Box
          sx={{
            p: 2,
            borderRadius: "12px",
            border: `1px solid ${meridian.border}`,
            backgroundColor: meridian.surface,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <Typography sx={{ fontSize: "0.875rem", fontWeight: 600, color: meridian.brandPrimary }}>
            {activeTemplate.title}
          </Typography>
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
            {activeTemplate.description}
          </Typography>

          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
              gap: 2,
            }}
          >
            {activeTemplate.fields.map((field: SpecialtyTemplateField) => {
              const val = (formData[field.name] as string | number | undefined) ?? "";

              if (field.type === "select" && field.options) {
                return (
                  <TextField
                    key={field.name}
                    select
                    label={field.label + (field.unit ? ` (${field.unit})` : "")}
                    value={val}
                    onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    size="small"
                    fullWidth
                    helperText={field.help_text}
                  >
                    <MenuItem value="">{t("doctor.specialtySelectOption")}</MenuItem>
                    {field.options.map((opt: { label: string; value: string }) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </TextField>
                );
              }

              if (field.type === "textarea") {
                return (
                  <Box key={field.name} sx={{ gridColumn: { sm: "span 2" } }}>
                    <TextField
                      label={field.label}
                      multiline
                      rows={2}
                      value={val}
                      onChange={(e) => handleFieldChange(field.name, e.target.value)}
                      size="small"
                      fullWidth
                      helperText={field.help_text}
                    />
                  </Box>
                );
              }

              return (
                <TextField
                  key={field.name}
                  type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
                  label={field.label + (field.unit ? ` (${field.unit})` : "")}
                  value={val}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  size="small"
                  fullWidth
                  slotProps={field.type === "date" ? { inputLabel: { shrink: true } } : undefined}
                  helperText={field.help_text}
                />
              );
            })}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
}
