"use client";

import Chip from "@mui/material/Chip";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

export interface ExpiryChipProps {
  daysLeft: number;
}

export default function ExpiryChip({ daysLeft }: ExpiryChipProps) {
  let label: string;
  let bg: string;
  let fg: string;
  let border: string;

  if (daysLeft <= 0) {
    label = translate("receptionist.scanShare.statusExpired");
    bg = "#fee2e2";
    fg = meridian.danger;
    border = "rgb(185 28 28 / 0.18)";
  } else if (daysLeft <= 30) {
    label = `${daysLeft} Days Left`;
    bg = "#ffedd5";
    fg = "#c2410c";
    border = "rgb(194 65 12 / 0.2)";
  } else if (daysLeft <= 90) {
    label = `${daysLeft} Days Left`;
    bg = "#fef3c7";
    fg = meridian.warning;
    border = "rgb(180 83 9 / 0.2)";
  } else {
    label = `${daysLeft} Days Left`;
    bg = "#dcfce7";
    fg = meridian.success;
    border = "rgb(22 101 52 / 0.18)";
  }

  return (
    <Chip
      size="small"
      label={label}
      sx={{
        height: 24,
        borderRadius: "999px",
        fontWeight: 600,
        fontSize: "0.6875rem",
        letterSpacing: "0.01em",
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
        "& .MuiChip-label": { px: 1.25 },
      }}
    />
  );
}
