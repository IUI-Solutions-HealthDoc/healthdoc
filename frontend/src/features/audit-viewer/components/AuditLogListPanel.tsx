"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import {
  COMMON_AUDIT_ACTIONS,
  COMMON_RESOURCE_TYPES,
} from "../constants";
import { formatDateTime } from "../lib/formatters";
import type { AuditLog } from "../types";
import { AuditActionChip } from "./AuditActionChip";

type Props = {
  rows: AuditLog[];
  loading: boolean;
  query: string;
  action: string;
  resourceType: string;
  from?: string;
  to?: string;
  selectedKey: string | null;
  onQueryChange: (q: string) => void;
  onActionChange: (a: string) => void;
  onResourceTypeChange: (r: string) => void;
  onFromChange?: (v: string) => void;
  onToChange?: (v: string) => void;
  onSelect: (row: AuditLog) => void;
};

export function AuditLogListPanel({
  rows,
  loading,
  query,
  action,
  resourceType,
  from,
  to,
  selectedKey,
  onQueryChange,
  onActionChange,
  onResourceTypeChange,
  onFromChange,
  onToChange,
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
        minHeight: 480,
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
        <Typography
          sx={{
            m: 0,
            fontSize: "1.0625rem",
            fontWeight: 700,
            color: meridian.textPrimary,
          }}
        >
          Audit logs
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Search and filter activity recorded for this facility.
        </Typography>
      </Box>

      <Stack spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search user, patient, resource…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
        <Stack direction="row" spacing={1}>
          <TextField
            select
            size="small"
            label="Action"
            value={action}
            onChange={(e) => onActionChange(e.target.value)}
            fullWidth
          >
            <MenuItem value="all">All</MenuItem>
            {COMMON_AUDIT_ACTIONS.map((a) => (
              <MenuItem key={a} value={a}>
                {a}
              </MenuItem>
            ))}
            <MenuItem value="delete_attempt">delete_attempt</MenuItem>
          </TextField>
          <TextField
            select
            size="small"
            label="Resource"
            value={resourceType}
            onChange={(e) => onResourceTypeChange(e.target.value)}
            fullWidth
          >
            <MenuItem value="all">All</MenuItem>
            {COMMON_RESOURCE_TYPES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
            <MenuItem value="audit_logs">audit_logs</MenuItem>
          </TextField>
        </Stack>
        {onFromChange && onToChange ? (
          <Stack direction="row" spacing={1}>
            <TextField
              size="small"
              type="date"
              label="From"
              value={from ?? ""}
              onChange={(e) => onFromChange(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
              fullWidth
            />
            <TextField
              size="small"
              type="date"
              label="To"
              value={to ?? ""}
              onChange={(e) => onToChange(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
              fullWidth
            />
          </Stack>
        ) : null}
      </Stack>

      <Box sx={{ flex: 1, overflow: "auto", borderTop: `1px solid rgb(0 31 84 / 0.08)` }}>
        {loading ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            Loading…
          </Typography>
        ) : rows.length === 0 ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            No audit entries match.
          </Typography>
        ) : (
          rows.map((row) => {
            const key = `${row.id}::${row.created_at}`;
            const selected = key === selectedKey;
            return (
              <Button
                key={key}
                onClick={() => onSelect(row)}
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
                    {row.resource_type}
                  </Typography>
                  <AuditActionChip action={row.action} />
                </Stack>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {row.user_display ?? row.user_id ?? "—"} · {formatDateTime(row.created_at)}
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {row.patient_display ?? row.patient_id ?? "No patient"} · {row.id}
                </Typography>
              </Button>
            );
          })
        )}
      </Box>
    </Box>
  );
}
