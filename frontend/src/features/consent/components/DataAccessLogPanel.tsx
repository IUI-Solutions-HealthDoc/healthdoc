"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import type { AccessChannel, DataAccessLog } from "../types";
import { BreakGlassBadge } from "./BreakGlassBadge";
import { formatDateTime } from "../lib/formatters";

type Props = {
  rows: DataAccessLog[];
  loading: boolean;
  channels: Record<AccessChannel, string>;
};

export function DataAccessLogPanel({ rows, loading, channels }: Props) {
  const columns: DataTableColumn<DataAccessLog>[] = [
    {
      key: "accessed_at",
      label: "Accessed",
      render: (r) => formatDateTime(r.accessed_at),
    },
    {
      key: "user_display",
      label: "User",
      render: (r) => (
        <Stack spacing={0.5}>
          <Typography sx={{ fontSize: "0.8125rem" }}>{r.user_display ?? r.user_id}</Typography>
          <Typography sx={{ fontSize: "0.6875rem", color: meridian.textSecondary }}>
            {r.role ?? "—"}
          </Typography>
        </Stack>
      ),
    },
    {
      key: "resource_type",
      label: "Resource",
      render: (r) => `${r.resource_type}${r.resource_id ? ` / ${r.resource_id}` : ""}`,
    },
    {
      key: "access_channel",
      label: "Channel",
      render: (r) => channels[r.access_channel] ?? r.access_channel,
    },
    {
      key: "flags",
      label: "Flags",
      render: (r) => (
        <Stack direction="row" useFlexGap sx={{ gap: 0.75, flexWrap: "wrap" }}>
          {r.emergency_access ? <BreakGlassBadge /> : null}
          {r.consent_required && !r.consent_verified ? (
            <StatusChip status="failed" label="Consent not verified" />
          ) : null}
          {r.consent_verified ? <StatusChip status="verified" label="Verified" /> : null}
        </Stack>
      ),
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
          A permanent history of record access, with emergency access highlighted.
        </Typography>
      </Box>

      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        loading={loading}
        emptyMessage="No data access events for this consent."
      />
    </Box>
  );
}
