"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import MenuItem from "@mui/material/MenuItem";

import { meridian } from "@/styles/theme";
import {
  adminPanelSx,
  adminSaveButtonSx,
  adminStickyActionsSx,
} from "../panelSx";
import type { User } from "../types";
import type { FieldErrors } from "../validation";
import type { Department } from "../api/departments";
import { UserHeader } from "./UserHeader";
import { useLocale } from "@/lib/i18n";

type Props = {
  draft: User;
  busy: boolean;
  isDirty: boolean;
  errors: FieldErrors;
  departments: Department[];
  onChange: (key: keyof User, value: string) => void;
  onSave: () => void;
  onToggleActive: () => void;
};

const FIELDS: { key: keyof User; label: string }[] = [
  { key: "full_name", label: "Full name" },
  { key: "email", label: "Email" },
  { key: "mobile", label: "Mobile" },
  { key: "designation", label: "Designation" },
  { key: "employee_id", label: "Employee ID" },
  { key: "registration_number", label: "Registration number" },
  { key: "registration_identifier_type", label: "ABDM registration identifier type" },
  { key: "registration_identifier_system", label: "Issuing registry URI" },
  { key: "qualification", label: "Qualification" },
];

export function UserProfileForm({
  draft,
  busy,
  isDirty,
  errors,
  departments,
  onChange,
  onSave,
  onToggleActive,
}: Props) {
  const { t, localizeField } = useLocale();
  const saveDisabled = busy || !isDirty;

  return (
    <Box
      sx={{
        ...adminPanelSx,
        p: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        minHeight: 420,
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.5, pb: 2, borderBottom: `1px solid ${meridian.border}` }}>
        <UserHeader user={draft} isDirty={isDirty} />
      </Box>

      <Box sx={{ px: 2.5, pt: 2, pb: 2.5, flex: 1 }}>
        <Typography
          sx={{
            m: 0,
            mb: 0.5,
            fontSize: "0.9375rem",
            fontWeight: 700,
            color: meridian.textPrimary,
          }}
        >{t("admin.ui.profile")}</Typography>
        <Typography sx={{ m: 0, mb: 2, fontSize: "0.8125rem", color: meridian.textSecondary }}>{t("admin.ui.updateTheStaffMemberSEditable")}{" "}{t("admin.ui.forAbdmConsentRequestsVerifyThe")}</Typography>

        <Stack direction="row" useFlexGap spacing={1.5} sx={{ flexWrap: "wrap" }}>
          {FIELDS.map(({ key, label }) => (
            <TextField
              key={key}
              label={label}
              size="small"
              sx={{ width: { xs: "100%", sm: "calc(50% - 6px)" } }}
              value={(draft[key] as string | null) ?? ""}
              onChange={(e) => onChange(key, e.target.value)}
              disabled={busy}
              error={Boolean(errors[key])}
              helperText={errors[key]}
            />
          ))}
          <TextField
            select
            label={t("monitor.department")}
            size="small"
            sx={{ width: { xs: "100%", sm: "calc(50% - 6px)" } }}
            value={draft.department_id ?? ""}
            onChange={(event) => onChange("department_id", event.target.value)}
            disabled={busy}
            helperText={t("admin.ui.optionalForFacilityWideRoles")}
          >
            <MenuItem value="">{t("admin.ui.noDepartment")}</MenuItem>
            {departments.filter((department) => department.is_active).map((department) => (
              <MenuItem key={department.id} value={department.id}>
                {localizeField(department.name, department.name_hi)} ({department.code})
              </MenuItem>
            ))}
          </TextField>
        </Stack>

      </Box>

      <Box sx={adminStickyActionsSx}>
        <Typography
          sx={{
            m: 0,
            fontSize: "0.8125rem",
            fontWeight: 600,
            color: isDirty ? meridian.warning : meridian.textSecondary,
          }}
        >
          {isDirty ? t("doctor.statusUnsavedChanges") : t("admin.ui.noChanges")}
        </Typography>
        <Stack direction="row" useFlexGap sx={{ gap: 1.25, flexWrap: "wrap" }}>
          <Button
            variant="outlined"
            disabled={busy}
            onClick={onToggleActive}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            {draft.is_active ? t("dpdp.consentManagerDeactivate") : t("admin.ui.activate")}
          </Button>
          <Button
            color="primary"
            variant={isDirty ? "contained" : "outlined"}
            disabled={saveDisabled}
            onClick={onSave}
            sx={adminSaveButtonSx(isDirty, saveDisabled)}
          >{t("admin.ui.saveProfile")}</Button>
        </Stack>
      </Box>
    </Box>
  );
}
