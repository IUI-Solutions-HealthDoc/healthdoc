"use client";

import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { ACCESS_CHANNEL_LABELS } from "../constants";
import { formatDateTime } from "../lib/formatters";
import type { AccessChannel, DataAccessLog } from "../types";

type Props = {
  rows: DataAccessLog[];
  loading: boolean;
  query: string;
  accessChannel: AccessChannel | "all";
  onQueryChange: (q: string) => void;
  onAccessChannelChange: (c: AccessChannel | "all") => void;
};

export function DataAccessLogPanel({
  rows,
  loading,
  query,
  accessChannel,
  onQueryChange,
  onAccessChannelChange,
}: Props) {
  const columns: DataTableColumn<DataAccessLog>[] = [
    {
      key: "accessed_at",
      label: "Accessed",
      render: (r) => formatDateTime(r.accessed_at),
    },
    {
      key: "user_display",
      label: "User",
      render: (r) => `${r.user_display ?? r.user_id} (${r.role})`,
    },
    {
      key: "patient_display",
      label: "Patient",
      render: (r) => r.patient_display ?? r.patient_id,
    },
    {
      key: "resource_type",
      label: "Resource",
      render: (r) =>
        r.resource_id ? `${r.resource_type} · ${r.resource_id.slice(0, 8)}…` : r.resource_type,
    },
    {
      key: "purpose_code",
      label: "Purpose",
      render: (r) => r.purpose_code,
    },
    {
      key: "access_channel",
      label: "Channel",
      render: (r) => (
        <StatusChip
          status={r.access_channel}
          label={ACCESS_CHANNEL_LABELS[r.access_channel]}
        />
      ),
    },
    {
      key: "emergency_access",
      label: "Flags",
      render: (r) => {
        const flags = [
          r.emergency_access ? "emergency" : null,
          r.consent_verified ? "consent ok" : "no consent",
        ].filter(Boolean);
        return flags.join(" · ");
      },
    },
  ];

  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        overflow: "hidden",
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
        <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
          Data access log
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Review who accessed patient data, why, and whether consent was verified.
        </Typography>
      </Box>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search patient, user, purpose…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          fullWidth
        />
        <TextField
          select
          size="small"
          label="Channel"
          value={accessChannel}
          onChange={(e) =>
            onAccessChannelChange(e.target.value as AccessChannel | "all")
          }
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          {(Object.keys(ACCESS_CHANNEL_LABELS) as AccessChannel[]).map((c) => (
            <MenuItem key={c} value={c}>
              {ACCESS_CHANNEL_LABELS[c]}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        loading={loading}
        emptyMessage="No data access events."
      />
    </Box>
  );
}
