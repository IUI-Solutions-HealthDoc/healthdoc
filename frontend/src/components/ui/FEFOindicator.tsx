"use client";

import Chip from "@mui/material/Chip";
import { meridian } from "@/styles/theme";
import { useLocale } from "@/lib/i18n";

export interface FEFOIndicatorProps {
  fefo: boolean;
}

export default function FEFOIndicator({ fefo }: FEFOIndicatorProps) {
  const { t } = useLocale();
  return (
    <Chip
      size="small"
      label={fefo ? "FEFO" : t("common.ui.notFefo")}
      sx={{
        height: 24,
        borderRadius: "999px",
        fontWeight: 600,
        fontSize: "0.6875rem",
        letterSpacing: "0.01em",
        backgroundColor: fefo ? "#dcfce7" : "#fee2e2",
        color: fefo ? meridian.success : meridian.danger,
        border: `1px solid ${fefo ? "rgb(22 101 52 / 0.18)" : "rgb(185 28 28 / 0.18)"}`,
        "& .MuiChip-label": { px: 1.25 },
      }}
    />
  );
}
