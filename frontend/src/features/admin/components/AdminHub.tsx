"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import Link from "next/link";

import { useLocale, type MessageKey } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { adminPanelSx } from "../panelSx";
import { AdminPageHeader } from "./AdminPageHeader";

const LINKS: { href: string; titleKey: MessageKey; subtitleKey: MessageKey }[] = [
  {
    href: "/admin/users",
    titleKey: "admin.hub.usersTitle",
    subtitleKey: "admin.hub.usersSubtitle",
  },
  {
    href: "/admin/account-requests",
    titleKey: "admin.hub.accountRequestsTitle",
    subtitleKey: "admin.hub.accountRequestsSubtitle",
  },
  {
    href: "/admin/permissions",
    titleKey: "admin.hub.permissionsTitle",
    subtitleKey: "admin.hub.permissionsSubtitle",
  },
  {
    href: "/admin/departments",
    titleKey: "admin.hub.departmentsTitle",
    subtitleKey: "admin.hub.departmentsSubtitle",
  },
  {
    href: "/admin/abdm-sync",
    titleKey: "admin.hub.abdmTitle",
    subtitleKey: "admin.hub.abdmSubtitle",
  },
  {
    href: "/admin/data-protection",
    titleKey: "admin.hub.dataProtectionTitle",
    subtitleKey: "admin.hub.dataProtectionSubtitle",
  },
  {
    href: "/admin/maintenance",
    titleKey: "admin.hub.maintenanceTitle",
    subtitleKey: "admin.hub.maintenanceSubtitle",
  },
  {
    href: "/audit-viewer",
    titleKey: "admin.hub.auditTitle",
    subtitleKey: "admin.hub.auditSubtitle",
  },
];

export function AdminHub() {
  const { t } = useLocale();
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <AdminPageHeader
        eyebrow={t("admin.hub.eyebrow")}
        title={t("admin.overviewTitle")}
      />

      <Stack spacing={1.5}>
        {LINKS.map((item) => (
          <Box
            key={item.href}
            component={Link}
            href={item.href}
            sx={{
              ...adminPanelSx,
              textDecoration: "none",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 2,
              position: "relative",
              overflow: "hidden",
              pl: 3,
              transition: "box-shadow 140ms ease, transform 140ms ease",
              "&::before": {
                content: '""',
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: 4,
                background: `linear-gradient(180deg, ${meridian.brandPrimary} 0%, #3d6a9c 100%)`,
              },
              "&:hover": {
                transform: "translateY(-1px)",
                boxShadow:
                  "0 1px 2px rgb(0 31 84 / 0.06), 0 16px 40px rgb(0 31 84 / 0.1)",
              },
            }}
          >
            <Box>
              <Typography
                sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}
              >
                {t(item.titleKey)}
              </Typography>
              <Typography
                sx={{ m: 0, mt: 0.5, fontSize: "0.8125rem", color: meridian.textSecondary }}
              >
                {t(item.subtitleKey)}
              </Typography>
            </Box>
            <ChevronRightIcon sx={{ color: meridian.textSecondary, flexShrink: 0 }} />
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
