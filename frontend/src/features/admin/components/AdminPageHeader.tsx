"use client";

import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Link from "next/link";

import { meridian } from "@/styles/theme";
import { adminPageStripSx } from "../panelSx";

type Props = {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  backHref?: string;
};

export function AdminPageHeader({ eyebrow, title, subtitle, actions, backHref }: Props) {
  return (
    <Box sx={adminPageStripSx}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        sx={{
          justifyContent: "space-between",
          alignItems: { xs: "stretch", sm: "flex-end" },
          position: "relative",
          zIndex: 1,
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          {backHref ? (
            <Box
              component={Link}
              href={backHref}
              sx={{
                display: "inline-block",
                mb: 1,
                color: meridian.brandPrimary,
                fontSize: "0.8125rem",
                fontWeight: 700,
                textDecoration: "underline",
                textUnderlineOffset: 2,
              }}
            >
              ← Back to administration
            </Box>
          ) : null}
          {eyebrow ? (
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
              {eyebrow}
            </Typography>
          ) : null}
          <Typography
            component="h1"
            sx={{
              m: 0,
              fontSize: { xs: "1.375rem", md: "1.5rem" },
              fontWeight: 700,
              letterSpacing: "-0.03em",
              color: meridian.textPrimary,
              lineHeight: 1.2,
            }}
          >
            {title}
          </Typography>
          {subtitle ? (
            <Typography
              sx={{
                m: 0,
                mt: 0.6,
                fontSize: "0.875rem",
                color: meridian.textSecondary,
                maxWidth: 560,
                lineHeight: 1.45,
              }}
            >
              {subtitle}
            </Typography>
          ) : null}
        </Box>
        {actions ? (
          <Stack
            direction="row"
            useFlexGap
            sx={{ gap: 1.25, flexWrap: "wrap", alignItems: "center" }}
          >
            {actions}
          </Stack>
        ) : null}
      </Stack>
    </Box>
  );
}
