"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import Link from "next/link";

import { meridian } from "@/styles/theme";
import { adminPanelSx } from "../panelSx";
import { AdminPageHeader } from "./AdminPageHeader";

const LINKS = [
  {
    href: "/admin/users",
    title: "Users",
    subtitle: "Create staff accounts and manage active access",
  },
  {
    href: "/admin/account-requests",
    title: "Account requests",
    subtitle: "Review staff account requests with two-person approval",
  },
  {
    href: "/admin/permissions",
    title: "Permissions",
    subtitle: "Manage facility modules and role access",
  },
  {
    href: "/admin/departments",
    title: "Departments & rooms",
    subtitle: "Facility departments, active status and room configuration",
  },
  {
    href: "/admin/abdm-sync",
    title: "ABDM identity links",
    subtitle: "Inspect and unlink verified ABHA records",
  },
  {
    href: "/admin/data-protection",
    title: "Data protection",
    subtitle: "DPO, grievances and consent-manager governance",
  },
  {
    href: "/admin/maintenance",
    title: "Equipment maintenance",
    subtitle: "Machine service and maintenance register",
  },
  {
    href: "/audit-viewer",
    title: "Audit trail",
    subtitle: "Review facility activity and integrity records",
  },
] as const;

export function AdminHub() {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <AdminPageHeader
        eyebrow="Governance"
        title="Admin"
        subtitle="Manage staff accounts, facility access, departments, and governance."
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
                {item.title}
              </Typography>
              <Typography
                sx={{ m: 0, mt: 0.5, fontSize: "0.8125rem", color: meridian.textSecondary }}
              >
                {item.subtitle}
              </Typography>
            </Box>
            <ChevronRightIcon sx={{ color: meridian.textSecondary, flexShrink: 0 }} />
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
