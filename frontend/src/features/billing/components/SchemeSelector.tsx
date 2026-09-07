"use client";

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { SCHEME_OPTIONS } from "../constants";
import type { SchemeOptionCode } from "../types";

type Props = {
  value: SchemeOptionCode;
  schemeAdjustment: number;
  disabled?: boolean;
  onChange: (code: SchemeOptionCode) => void;
  onSchemeAdjustmentChange: (n: number) => void;
};

export function SchemeSelector({
  value,
  schemeAdjustment,
  disabled,
  onChange,
  onSchemeAdjustmentChange,
}: Props) {
  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        p: 2.5,
      }}
    >
      <Typography
        sx={{
          m: 0,
          mb: 0.5,
          fontSize: "1.0625rem",
          fontWeight: 700,
          color: meridian.textPrimary,
        }}
      >
        Invoice scheme
      </Typography>
      <Typography sx={{ m: 0, mb: 2, fontSize: "0.8125rem", color: meridian.textSecondary }}>
        {disabled ? "Read-only scheme recorded on this invoice." : "Choose the invoice scheme."}
      </Typography>

      <Stack direction="row" useFlexGap sx={{ gap: 1, flexWrap: "wrap", mb: 2 }}>
        {SCHEME_OPTIONS.map((opt) => {
          const selected = value === opt.code;
          return (
            <Chip
              key={opt.code}
              label={opt.label}
              clickable={!disabled}
              onClick={() => !disabled && onChange(opt.code)}
              sx={{
                height: 32,
                borderRadius: "10px",
                fontWeight: 600,
                border: `1px solid ${selected ? meridian.brandPrimary : meridian.border}`,
                backgroundColor: selected ? "#e8eef5" : meridian.surface,
                color: selected ? meridian.brandPrimary : meridian.textPrimary,
                opacity: disabled ? 0.6 : 1,
              }}
            />
          );
        })}
      </Stack>

      <TextField
        type="number"
        size="small"
        label="Scheme adjustment (₹)"
        value={schemeAdjustment}
        disabled={disabled}
        onChange={(e) => onSchemeAdjustmentChange(Number(e.target.value) || 0)}
        slotProps={{ htmlInput: { min: 0, step: 1 } }}
        fullWidth
        helperText="Subtracted from gross along with discount → net_amount"
      />
    </Box>
  );
}
