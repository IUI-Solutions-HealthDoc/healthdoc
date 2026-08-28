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
        >
          Profile
        </Typography>
        <Typography sx={{ m: 0, mb: 2, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Schema columns only — username / keycloak_sub are identity keys (not edited here)
        </Typography>

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
            label="Department"
            size="small"
            sx={{ width: { xs: "100%", sm: "calc(50% - 6px)" } }}
            value={draft.department_id ?? ""}
            onChange={(event) => onChange("department_id", event.target.value)}
            disabled={busy}
            helperText="Optional for facility-wide roles"
          >
            <MenuItem value="">No department</MenuItem>
            {departments.filter((department) => department.is_active).map((department) => (
              <MenuItem key={department.id} value={department.id}>
                {department.name} ({department.code})
              </MenuItem>
            ))}
          </TextField>
        </Stack>

        <Typography sx={{ mt: 2, mb: 0, fontSize: "0.75rem", color: meridian.textSecondary }}>
          facility_id {draft.facility_id} · keycloak_sub {draft.keycloak_sub}
        </Typography>
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
          {isDirty ? "Unsaved changes" : "No changes"}
        </Typography>
        <Stack direction="row" useFlexGap sx={{ gap: 1.25, flexWrap: "wrap" }}>
          <Button
            variant="outlined"
            disabled={busy}
            onClick={onToggleActive}
            sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            {draft.is_active ? "Deactivate" : "Activate"}
          </Button>
          <Button
            color="primary"
            variant={isDirty ? "contained" : "outlined"}
            disabled={saveDisabled}
            onClick={onSave}
            sx={adminSaveButtonSx(isDirty, saveDisabled)}
          >
            Save profile
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}
