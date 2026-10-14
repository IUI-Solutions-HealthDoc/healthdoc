"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { InvoiceStatusChip } from "./InvoiceStatusChip";
import type { InvoiceWithItems } from "../types";

export function InvoiceHeader({ invoice }: { invoice: InvoiceWithItems }) {
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
      <Stack
        direction={{ xs: "column", sm: "row" }}
        sx={{ justifyContent: "space-between", gap: 2, alignItems: { sm: "center" } }}
      >
        <Box>
          <Typography
            sx={{
              m: 0,
              fontSize: "1.25rem",
              fontWeight: 700,
              letterSpacing: "-0.02em",
              color: meridian.textPrimary,
            }}
          >
            {invoice.patient?.full_name ?? "Patient"}
          </Typography>
          <Typography sx={{ mt: 0.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            UHID {invoice.patient?.uhid ?? "—"} · Visit {invoice.visit?.visit_number ?? "—"} (
            {invoice.visit?.visit_type
              ? invoice.visit.visit_type.toUpperCase()
              : "—"}
            )
          </Typography>
          <Typography
            sx={{
              mt: 0.75,
              fontSize: "0.8125rem",
              fontFamily: 'var(--font-ibm-plex-mono), monospace',
              color: meridian.brandPrimary,
              fontWeight: 600,
            }}
          >
            {invoice.invoice_number}
          </Typography>
        </Box>
        <InvoiceStatusChip status={invoice.status} />
      </Stack>
    </Box>
  );
}
