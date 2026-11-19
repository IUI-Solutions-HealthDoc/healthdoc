"use client";

import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import type { StatusStep } from "./types";
import { useLocale } from "@/lib/i18n";

interface StatusAlertProps {
  status: string;
  workflow: StatusStep[];
  reason?: string;
}

export default function StatusAlert({
  status,
  workflow,
  reason,
}: StatusAlertProps) {
  const { t } = useLocale();
  const currentStatus = workflow.find((step) => step.value === status);

  if (!currentStatus?.alert) {
    return null;
  }

  return (
    <Alert
      severity={currentStatus.alert.severity}
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: "fit-content",
        maxWidth: 260,
        minHeight: 32,
        px: 1.25,
        py: 0.5,
        mx: "auto",
        borderRadius: "12px",
        border: `1px solid ${meridian.border}`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04)",
        "& .MuiAlert-icon": {
          alignSelf: "center",
          mr: 0.75,
          fontSize: 18,
        },
        "& .MuiAlert-message": {
          width: "100%",
          py: 0,
          textAlign: "center",
        },
      }}
    >
      <Typography
        variant="caption"
        sx={{
          display: "block",
          width: "100%",
          textAlign: "center",
          fontWeight: 600,
          lineHeight: 1.3,
          color: meridian.textPrimary,
        }}
      >
        {currentStatus.alert.message}
      </Typography>

      {reason ? (
        <Typography
          variant="caption"
          sx={{
            display: "block",
            width: "100%",
            mt: 0.5,
            textAlign: "center",
            lineHeight: 1.3,
            color: meridian.textSecondary,
          }}
        >{t("common.ui.reasonReason", { reason })}</Typography>
      ) : null}
    </Alert>
  );
}
