"use client";

import { memo } from "react";
import Barcode from "react-barcode";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { useLocale } from "@/lib/i18n";

interface BarcodeDisplayProps {
  value: string;
  width?: number;
  height?: number;
  displayValue?: boolean;
  lineColor?: string;
  background?: string;
}

function BarcodeDisplay({
  value,
  width = 2,
  height = 80,
  displayValue = true,
  lineColor = meridian.brandPrimary,
  background = meridian.surface,
}: BarcodeDisplayProps) {
  const { t } = useLocale();
  if (!value.trim()) {
    return (
      <Typography sx={{ color: meridian.danger, fontSize: "0.875rem" }}>{t("common.ui.barcodeValueIsRequired")}</Typography>
    );
  }

  return (
    <Paper
      elevation={0}
      role="img"
      aria-label={`Barcode for ${value}`}
      sx={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow:
          "0 1px 2px rgb(0 31 84 / 0.04), 0 8px 24px rgb(0 31 84 / 0.06)",
      }}
    >
      <Box>
        <Barcode
          value={value}
          format="CODE128"
          width={width}
          height={height}
          displayValue={displayValue}
          lineColor={lineColor}
          background={background}
          font="IBM Plex Mono"
          fontSize={13}
        />
      </Box>
    </Paper>
  );
}

export default memo(BarcodeDisplay);
