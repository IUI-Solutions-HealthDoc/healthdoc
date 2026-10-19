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
import { useLocale, translate } from "@/lib/i18n";

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
  { key: "full_name", get label() { return translate("field.fullName"); } },
  { key: "email", get label() { return translate("admin.ui.email"); } },
  { key: "mobile", get label() { return translate("field.mobile"); } },
  { key: "designation", get label() { return translate("common.ui.designation"); } },
  { key: "employee_id", get label() { return translate("admin.ui.employeeId2"); } },
  { key: "registration_number", get label() { return translate("admin.ui.registrationNumber"); } },
  { key: "registration_identifier_type", get label() { return translate("admin.msg.abdmRegistrationIdentifierType"); } },
  { key: "registration_identifier_system", get label() { return translate("admin.msg.issuingRegistryUri"); } },
  { key: "qualification", get label() { return translate("common.ui.qualification"); } },
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
