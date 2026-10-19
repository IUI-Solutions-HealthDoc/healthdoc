"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { formatINR } from "../lib/formatters";
import { fromMoney, type Money } from "../lib/money";
import { useLocale } from "@/lib/i18n";

type Props = {
  gross_amount: Money;
  discount_amount: Money;
  scheme_adjustment: Money;
  net_amount: Money;
  canEdit: boolean;
  onDiscountChange: (n: number) => void;
};

function Row({ label, value, emphasize }: { label: string; value: string; emphasize?: boolean }) {
  return (
    <Stack direction="row" sx={{ justifyContent: "space-between", gap: 2 }}>
      <Typography
        sx={{
          fontSize: emphasize ? "0.9375rem" : "0.875rem",
          fontWeight: emphasize ? 700 : 500,
          color: emphasize ? meridian.textPrimary : meridian.textSecondary,
        }}
      >
        {label}
      </Typography>
      <Typography
        sx={{
          fontSize: emphasize ? "1.125rem" : "0.875rem",
          fontWeight: emphasize ? 700 : 600,
          color: meridian.textPrimary,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </Typography>
    </Stack>
  );
}

export function InvoiceTotals({
  gross_amount,
  discount_amount,
  scheme_adjustment,
  net_amount,
  canEdit,
  onDiscountChange,
}: Props) {
  const { t } = useLocale();
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
          mb: 2,
          fontSize: "1.0625rem",
          fontWeight: 700,
          color: meridian.textPrimary,
        }}
      >{t("billing.ui.totals")}</Typography>

      <Stack spacing={1.5}>
        <Row label={t("billing.ui.grossAmount")} value={formatINR(gross_amount)} />
        {canEdit ? (
          <TextField
            type="number"
            size="small"
            label={t("billing.ui.discountAmount")}
            value={fromMoney(discount_amount)}
            onChange={(e) => onDiscountChange(Number(e.target.value) || 0)}
            slotProps={{ htmlInput: { min: 0, step: 1 } }}
            fullWidth
          />
        ) : (
          <Row label={t("billing.ui.discountAmount2")} value={formatINR(discount_amount)} />
        )}
        <Row label={t("billing.ui.schemeAdjustment")} value={formatINR(scheme_adjustment)} />
        <Box sx={{ borderTop: `1px solid ${meridian.border}`, pt: 1.5 }}>
          <Row label={t("billing.ui.netAmount")} value={formatINR(net_amount)} emphasize />
        </Box>
      </Stack>
    </Box>
  );
}
