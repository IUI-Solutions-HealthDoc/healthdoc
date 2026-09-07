"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { formatINR } from "../lib/formatters";
import { InvoiceStatusChip } from "./InvoiceStatusChip";
import type { InvoiceStatus, InvoiceWithItems } from "../types";

type Props = {
  invoices: InvoiceWithItems[];
  loading: boolean;
  query: string;
  status: InvoiceStatus | "all";
  selectedId: string | null;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onQueryChange: (q: string) => void;
  onStatusChange: (s: InvoiceStatus | "all") => void;
  onSelect: (id: string) => void;
};

export function InvoiceListPanel({
  invoices,
  loading,
  query,
  status,
  selectedId,
  page,
  pageSize,
  total,
  onPageChange,
  onQueryChange,
  onStatusChange,
  onSelect,
}: Props) {
  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        minHeight: 420,
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
        <Typography
          sx={{
            m: 0,
            fontSize: "1.0625rem",
            fontWeight: 700,
            color: meridian.textPrimary,
            letterSpacing: "-0.02em",
          }}
        >
          Invoices
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          One invoice per visit — open a draft to build charges
        </Typography>
      </Box>

      <Stack spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search UHID, name, INV-…"
          label="Search invoices"
          slotProps={{ htmlInput: { maxLength: 120 } }}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
        <TextField
          select
          size="small"
          label="Status"
          value={status}
          onChange={(e) => onStatusChange(e.target.value as InvoiceStatus | "all")}
        >
          <MenuItem value="all">All</MenuItem>
          <MenuItem value="draft">Draft</MenuItem>
          <MenuItem value="issued">Issued</MenuItem>
          <MenuItem value="partially_paid">Partially Paid</MenuItem>
          <MenuItem value="paid">Paid</MenuItem>
          <MenuItem value="waived">Waived</MenuItem>
          <MenuItem value="cancelled">Cancelled</MenuItem>
        </TextField>
      </Stack>

      <Box sx={{ flex: 1, overflow: "auto", borderTop: `1px solid rgb(0 31 84 / 0.08)` }}>
        {loading ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            Loading…
          </Typography>
        ) : invoices.length === 0 ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            No invoices match.
          </Typography>
        ) : (
          invoices.map((inv) => {
            const selected = inv.id === selectedId;
            return (
              <Button
                key={inv.id}
                onClick={() => onSelect(inv.id)}
                sx={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  textTransform: "none",
                  borderRadius: 0,
                  px: 2.5,
                  py: 1.5,
                  borderBottom: `1px solid rgb(0 31 84 / 0.06)`,
                  backgroundColor: selected ? "rgb(0 31 84 / 0.06)" : "transparent",
                  "&:hover": { backgroundColor: "rgb(0 31 84 / 0.04)" },
                }}
              >
                <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1, mb: 0.5 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: "0.875rem", color: meridian.textPrimary }}>
                    {inv.patient?.full_name ?? inv.patient_id}
                  </Typography>
                  <InvoiceStatusChip status={inv.status} />
                </Stack>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {inv.invoice_number}
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {inv.patient?.uhid} ·{" "}
                  {inv.visit?.visit_type ? inv.visit.visit_type.toUpperCase() : "—"} ·{" "}
                  {formatINR(inv.net_amount)}
                </Typography>
              </Button>
            );
          })
        )}
      </Box>
      <Stack direction="row" sx={{ p: 1.5, gap: 1, alignItems: "center", justifyContent: "space-between" }}>
        <Button disabled={loading || page <= 1} onClick={() => onPageChange(page - 1)}>Previous</Button>
        <Typography variant="caption">Page {page} of {Math.max(1, Math.ceil(total / pageSize))} · {total} invoices</Typography>
        <Button disabled={loading || page * pageSize >= total} onClick={() => onPageChange(page + 1)}>Next</Button>
      </Stack>
    </Box>
  );
}
