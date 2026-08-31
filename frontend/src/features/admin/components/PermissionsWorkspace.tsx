"use client";

import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { MODULE_CODE_LABELS, MODULE_CODES } from "../constants";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { useFacilityModules } from "../hooks/useFacilityModules";
import { AdminPageHeader } from "./AdminPageHeader";
import { FacilityModulesPanel } from "./FacilityModulesPanel";
import { RealmRolesMatrixPanel } from "./RealmRolesMatrixPanel";

type PermTab = "modules" | "roles";

export function PermissionsWorkspace() {
  const [tab, setTab] = useState<PermTab>("modules");
  const { modules, capabilities, loading, error, busyCode, toggle } = useFacilityModules();
  const { user: currentUser } = useCurrentUser();

  const enabledCount = useMemo(
    () => modules.filter((m) => m.is_enabled).length,
    [modules],
  );
  const disabledCount = useMemo(
    () => modules.filter((m) => !m.is_enabled).length,
    [modules],
  );

  const capsSummary = useMemo(() => {
    if (!capabilities) return null;
    return MODULE_CODES.map((code) => ({
      code,
      on: capabilities.modules[code],
      label: MODULE_CODE_LABELS[code],
    }));
  }, [capabilities]);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <AdminPageHeader
        backHref="/admin"
        eyebrow="Admin"
        title="Permissions"
        subtitle="Manage facility modules and review the access assigned to each role."
      />

      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          gap: 1,
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1.5,
          borderRadius: "14px",
          border: `1px solid ${meridian.border}`,
          background: `linear-gradient(110deg, ${meridian.muted} 0%, ${meridian.surface} 55%, #eef4fb 100%)`,
        }}
      >
        <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: "wrap", alignItems: "center" }}>
          <Typography
            sx={{
              m: 0,
              mr: 0.5,
              fontSize: "0.6875rem",
              fontWeight: 700,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: meridian.textSecondary,
            }}
          >
            Facility
          </Typography>
          {[
            // The real facility, from GET /users/me — this used to render a
            // hardcoded mock UUID, which is a poor label anyway: an admin
            // checking they are configuring the right hospital wants its name.
            { key: "fac", label: currentUser?.facility.name ?? "…" },
            {
              key: "on",
              label: loading ? "… enabled" : `${enabledCount} enabled`,
            },
            {
              key: "off",
              label: loading ? "… disabled" : `${disabledCount} disabled`,
            },
          ].map((p) => (
            <Chip
              key={p.key}
              size="small"
              label={p.label}
              sx={{
                height: 26,
                fontWeight: 600,
                fontSize: "0.75rem",
                bgcolor: meridian.surface,
                border: `1px solid ${meridian.border}`,
                color: meridian.textPrimary,
              }}
            />
          ))}
        </Stack>
        <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.textSecondary }}>
          Changes apply to this facility. Role access is enforced at sign-in and on every request.
        </Typography>
      </Box>

      {error ? (
        <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
          {error}
        </Typography>
      ) : null}

      {capsSummary ? (
        <Stack direction="row" useFlexGap sx={{ gap: 0.75, flexWrap: "wrap" }}>
          {capsSummary.map((c) => (
            <Chip
              key={c.code}
              size="small"
              label={`${c.label}: ${c.on ? "on" : "off"}`}
              sx={{
                height: 24,
                fontWeight: 600,
                fontSize: "0.6875rem",
                bgcolor: c.on ? "#e8f0e9" : meridian.muted,
                color: meridian.textPrimary,
                border: `1px solid ${meridian.border}`,
              }}
            />
          ))}
        </Stack>
      ) : null}

      <Tabs
        value={tab}
        onChange={(_, next: PermTab) => setTab(next)}
        sx={{
          minHeight: 42,
          borderBottom: `1px solid ${meridian.border}`,
          "& .MuiTab-root": {
            textTransform: "none",
            fontWeight: 700,
            minHeight: 42,
            color: meridian.textSecondary,
          },
          "& .Mui-selected": { color: `${meridian.brandPrimary} !important` },
          "& .MuiTabs-indicator": { bgcolor: meridian.brandPrimary, height: 3, borderRadius: 2 },
        }}
      >
        <Tab value="modules" label="Modules" />
        <Tab value="roles" label="Realm roles" />
      </Tabs>

      {tab === "modules" ? (
        <FacilityModulesPanel
          modules={modules}
          loading={loading}
          busyCode={busyCode}
          onToggle={toggle}
        />
      ) : (
        <RealmRolesMatrixPanel />
      )}
    </Box>
  );
}
