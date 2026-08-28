"use client";

import { useState, type ReactNode } from "react";
import CloseIcon from "@mui/icons-material/Close";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Link from "next/link";

import { toast } from "@/components/ui/toast";
import { meridian } from "@/styles/theme";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { createUser } from "../api";
import { REALM_ROLE_LABELS } from "../constants";
import type { RealmRole, User } from "../types";
import {
  FACILITY_STAFF_ROLES,
  type FieldErrors,
  validateCreateUser,
} from "../validation";

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (user: User) => void;
};

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <Typography
      sx={{
        m: 0,
        mb: 1.25,
        mt: 0.5,
        fontSize: "0.6875rem",
        fontWeight: 700,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: meridian.textSecondary,
      }}
    >
      {children}
    </Typography>
  );
}

export function CreateUserModal({ open, onClose, onCreated }: Props) {
  const { user: currentUser } = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [username, setUsername] = useState("");
  const [full_name, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [designation, setDesignation] = useState("");
  const [employee_id, setEmployeeId] = useState("");
  const [registration_number, setRegistrationNumber] = useState("");
  const [qualification, setQualification] = useState("");
  const [temporary_password, setTemporaryPassword] = useState("");
  const [roles, setRoles] = useState<RealmRole[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});

  const clearError = (field: string) => {
    setErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  };

  const toggleRole = (role: RealmRole) => {
    clearError("roles");
    setRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  const reset = () => {
    setUsername("");
    setFullName("");
    setEmail("");
    setMobile("");
    setDesignation("");
    setEmployeeId("");
    setRegistrationNumber("");
    setQualification("");
    setTemporaryPassword("");
    setRoles([]);
    setErrors({});
  };

  const handleClose = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const submit = async () => {
    const validationErrors = validateCreateUser({
      username,
      fullName: full_name,
      email,
      mobile,
      temporaryPassword: temporary_password,
      roles,
    });
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      toast.error("Please correct the highlighted fields before creating the user.");
      return;
    }
    setBusy(true);
    try {
      const user = await createUser({
        username: username.trim(),
        full_name: full_name.trim(),
        email: email.trim() || null,
        mobile: mobile.trim() || null,
        designation: designation.trim() || null,
        employee_id: employee_id.trim() || null,
        registration_number: registration_number.trim() || null,
        qualification: qualification.trim() || null,
        // No facility_id. The account is created at the authenticated admin's
        // facility, derived from their token. POST /users refuses a body value
        // that disagrees (403), and the value sent here used to be a hardcoded
        // mock constant — so this submitted a foreign facility on every call.
        roles,
        temporary_password,
      });
      toast.success("User created", "Keycloak account + users row (bootstrap)");
      onCreated(user);
      reset();
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  const fieldSx = { width: { xs: "100%", sm: "calc(50% - 6px)" } };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="md"
      slotProps={{
        paper: {
          sx: {
            borderRadius: "16px",
            border: `1px solid ${meridian.border}`,
            boxShadow: "0 16px 48px rgb(0 31 84 / 0.16)",
            overflow: "hidden",
          },
        },
      }}
    >
      <Box
        sx={{
          position: "relative",
          px: 3,
          pt: 2.5,
          pb: 2,
          background: `linear-gradient(110deg, ${meridian.muted} 0%, ${meridian.surface} 50%, #eef4fb 100%)`,
          borderBottom: `1px solid ${meridian.border}`,
        }}
      >
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "flex-start", gap: 2 }}>
          <Box sx={{ minWidth: 0, pr: 1 }}>
            <Typography
              sx={{
                m: 0,
                mb: 0.5,
                fontSize: "0.6875rem",
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: meridian.textSecondary,
              }}
            >
              Bootstrap · POST /users
            </Typography>
            <Typography
              component="h2"
              sx={{
                m: 0,
                fontSize: "1.25rem",
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: meridian.textPrimary,
              }}
            >
              New user
            </Typography>
            <Typography
              sx={{
                m: 0,
                mt: 0.75,
                fontSize: "0.8125rem",
                color: meridian.textSecondary,
                lineHeight: 1.45,
                maxWidth: 520,
              }}
            >
              Creates a Keycloak account (roles + temporary password) and a users profile
              atomically. For day-to-day staffing, prefer{" "}
              <Box
                component={Link}
                href="/admin/account-requests"
                onClick={handleClose}
                sx={{
                  color: meridian.brandPrimary,
                  fontWeight: 700,
                  textDecoration: "underline",
                  textUnderlineOffset: 2,
                }}
              >
                account requests
              </Box>
              .
            </Typography>
          </Box>
          <IconButton
            aria-label="Close"
            onClick={handleClose}
            disabled={busy}
            size="small"
            sx={{ color: meridian.textSecondary }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Box>

      <DialogContent sx={{ px: 3, py: 2.5 }}>
        <SectionLabel>Account</SectionLabel>
        <Stack direction="row" useFlexGap spacing={1.5} sx={{ flexWrap: "wrap", mb: 2.5 }}>
          <TextField
            label="Username"
            size="small"
            required
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              clearError("username");
            }}
            disabled={busy}
            sx={fieldSx}
            error={Boolean(errors.username)}
            helperText={errors.username ?? "Letters, numbers, dots, hyphens or underscores; no spaces"}
          />
          <TextField
            label="Temporary password"
            size="small"
            type="password"
            required
            value={temporary_password}
            onChange={(e) => {
              setTemporaryPassword(e.target.value);
              clearError("temporaryPassword");
            }}
            disabled={busy}
            sx={fieldSx}
            error={Boolean(errors.temporaryPassword)}
            helperText={errors.temporaryPassword ?? "Min 8 chars · Keycloak only — never stored on users"}
          />
        </Stack>

        <SectionLabel>Profile</SectionLabel>
        <Stack direction="row" useFlexGap spacing={1.5} sx={{ flexWrap: "wrap", mb: 2.5 }}>
          <TextField
            label="Full name"
            size="small"
            required
            value={full_name}
            onChange={(e) => {
              setFullName(e.target.value);
              clearError("fullName");
            }}
            disabled={busy}
            sx={fieldSx}
            error={Boolean(errors.fullName)}
            helperText={errors.fullName}
          />
          <TextField
            label="Email"
            size="small"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              clearError("email");
            }}
            disabled={busy}
            sx={fieldSx}
            error={Boolean(errors.email)}
            helperText={errors.email}
          />
          <TextField
            label="Mobile"
            size="small"
            value={mobile}
            onChange={(e) => {
              setMobile(e.target.value);
              clearError("mobile");
            }}
            disabled={busy}
            sx={fieldSx}
            error={Boolean(errors.mobile)}
            helperText={errors.mobile ?? "E.164 e.g. +91XXXXXXXXXX"}
          />
          <TextField
            label="Designation"
            size="small"
            value={designation}
            onChange={(e) => setDesignation(e.target.value)}
            disabled={busy}
            sx={fieldSx}
          />
          <TextField
            label="Employee ID"
            size="small"
            value={employee_id}
            onChange={(e) => setEmployeeId(e.target.value)}
            disabled={busy}
            sx={fieldSx}
          />
          <TextField
            label="Registration number"
            size="small"
            value={registration_number}
            onChange={(e) => setRegistrationNumber(e.target.value)}
            disabled={busy}
            sx={fieldSx}
          />
          <TextField
            label="Qualification"
            size="small"
            value={qualification}
            onChange={(e) => setQualification(e.target.value)}
            disabled={busy}
            sx={{ width: "100%" }}
          />
        </Stack>

        <SectionLabel>Keycloak realm roles</SectionLabel>
        <Box
          sx={{
            p: 1.75,
            borderRadius: "12px",
            border: `1px solid ${meridian.border}`,
            bgcolor: meridian.muted,
          }}
        >
          <Typography sx={{ m: 0, mb: 1.25, fontSize: "0.75rem", color: meridian.textSecondary }}>
            Multiple roles are supported. Patient and platform-superadmin roles are managed
            outside facility staffing.
            {roles.length > 0 ? ` · ${roles.length} selected` : ""}
          </Typography>
          <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", gap: 0.75 }}>
            {FACILITY_STAFF_ROLES.map((role) => {
              const selected = roles.includes(role);
              return (
                <Chip
                  key={role}
                  clickable
                  disabled={busy}
                  label={REALM_ROLE_LABELS[role]}
                  onClick={() => toggleRole(role)}
                  variant={selected ? "filled" : "outlined"}
                  sx={{
                    fontWeight: 600,
                    height: 30,
                    borderColor: selected ? "transparent" : meridian.border,
                    bgcolor: selected ? meridian.brandPrimary : meridian.surface,
                    color: selected ? "#ffffff" : meridian.textPrimary,
                    "&:hover": {
                      bgcolor: selected ? meridian.brandDeep : "#e8eef5",
                    },
                  }}
                />
              );
            })}
          </Stack>
          {errors.roles ? (
            <Typography sx={{ mt: 1, fontSize: "0.75rem", color: meridian.danger }}>
              {errors.roles}
            </Typography>
          ) : null}
        </Box>

        <Typography
          sx={{
            m: 0,
            mt: 2,
            fontSize: "0.75rem",
            color: meridian.textSecondary,
            fontFamily: "var(--font-ibm-plex-mono), monospace",
          }}
        >
          {currentUser
            ? `${currentUser.facility.name} · ${currentUser.facility.code}`
            : "Facility resolved from your account on submit"}
        </Typography>
      </DialogContent>

      <DialogActions
        sx={{
          px: 3,
          py: 2,
          borderTop: `1px solid ${meridian.border}`,
          background: `linear-gradient(180deg, rgb(251 252 254 / 0.92) 0%, ${meridian.muted} 100%)`,
          gap: 1,
        }}
      >
        <Button
          onClick={handleClose}
          disabled={busy}
          variant="outlined"
          sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
        >
          Cancel
        </Button>
        <Button
          variant="contained"
          color="primary"
          disabled={busy}
          onClick={() => void submit()}
          sx={{
            textTransform: "none",
            fontWeight: 700,
            borderRadius: "10px",
            bgcolor: meridian.brandPrimary,
            color: "#ffffff",
            minWidth: 140,
            "&:hover": { bgcolor: meridian.brandDeep },
            "&.Mui-disabled": {
              color: meridian.textSecondary,
              bgcolor: meridian.muted,
              opacity: 1,
            },
          }}
        >
          {busy ? "Creating…" : "Create user"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
