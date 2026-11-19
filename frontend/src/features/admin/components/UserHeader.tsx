"use client";

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import type { User } from "../types";
import { ActiveStatusChip } from "./ActiveStatusChip";
import { useLocale } from "@/lib/i18n";

type Props = {
  user: User;
  isDirty?: boolean;
};

/** Embedded header (no panel chrome) — parent supplies the card. */
export function UserHeader({ user, isDirty = false }: Props) {
  const { t } = useLocale();
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      sx={{ justifyContent: "space-between", gap: 2, alignItems: { sm: "flex-start" } }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography
          sx={{
            m: 0,
            fontSize: "1.25rem",
            fontWeight: 700,
            letterSpacing: "-0.02em",
            color: meridian.textPrimary,
          }}
        >
          {user.full_name}
        </Typography>
        <Typography sx={{ mt: 0.5, fontSize: "0.875rem", color: meridian.textSecondary }}>{t("admin.ui.valueEmployeeIdValue2", { value: user.designation ?? "—", value2: user.employee_id ?? "—" })}</Typography>
        <Typography
          sx={{
            mt: 0.75,
            fontSize: "0.8125rem",
            fontFamily: "var(--font-ibm-plex-mono), monospace",
            color: meridian.brandPrimary,
            fontWeight: 600,
          }}
        >
          {user.username}
        </Typography>
      </Box>
      <Stack direction="row" useFlexGap sx={{ gap: 1, alignItems: "center", flexWrap: "wrap" }}>
        {isDirty ? (
          <Chip
            size="small"
            label={t("admin.ui.unsaved")}
            sx={{
              fontWeight: 700,
              height: 26,
              bgcolor: "rgba(180, 83, 9, 0.12)",
              color: meridian.warning,
              border: `1px solid ${meridian.warning}55`,
            }}
          />
        ) : null}
        <ActiveStatusChip active={user.is_active} />
      </Stack>
    </Stack>
  );
}
