"use client";

import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { CONSENT_STATUS_LABELS } from "../constants";
import { formatDate } from "../lib/formatters";
import type { ConsentRecord, ConsentStatus } from "../types";

type Props = {
  rows: ConsentRecord[];
  loading: boolean;
  query: string;
  status: ConsentStatus | "all";
  selectedId: string | null;
  onQueryChange: (q: string) => void;
  onStatusChange: (s: ConsentStatus | "all") => void;
  onSelect: (id: string) => void;
};

export function ConsentListPanel({
  rows,
  loading,
  query,
  status,
  selectedId,
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
        minHeight: 480,
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
        <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
          Consent records
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Open a record to review its decision and expiry.
        </Typography>
      </Box>

      <Stack spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search UHID, name, purpose…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
        <TextField
          select
          size="small"
          label="Status"
          value={status}
          onChange={(e) => onStatusChange(e.target.value as ConsentStatus | "all")}
        >
          <MenuItem value="all">All</MenuItem>
          {(Object.keys(CONSENT_STATUS_LABELS) as ConsentStatus[]).map((s) => (
            <MenuItem key={s} value={s}>
              {CONSENT_STATUS_LABELS[s]}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <Box sx={{ flex: 1, overflow: "auto", borderTop: `1px solid rgb(0 31 84 / 0.08)` }}>
        {loading ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            Loading…
          </Typography>
        ) : rows.length === 0 ? (
          <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
            No consent records match.
          </Typography>
        ) : (
          rows.map((row) => {
            const selected = row.id === selectedId;
            return (
              <Button
                key={row.id}
                onClick={() => onSelect(row.id)}
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
                    {row.patient?.name ?? row.patient_id}
                  </Typography>
                  <StatusChip status={row.status} label={CONSENT_STATUS_LABELS[row.status]} />
                </Stack>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {row.purpose_label ?? row.purpose_code} · {row.channel} · {row.id}
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {row.patient?.uhid} · granted {formatDate(row.granted_at)}
                  {row.expires_at ? ` · expires ${formatDate(row.expires_at)}` : " · no expiry"}
                </Typography>
              </Button>
            );
          })
        )}
      </Box>
    </Box>
  );
}
