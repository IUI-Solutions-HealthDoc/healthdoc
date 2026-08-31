"use client";

import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { FILE_ACCESS_ACTION_LABELS } from "../constants";
import { formatDateTime } from "../lib/formatters";
import type { FileAccessAction, FileAccessLog } from "../types";

type Props = {
  rows: FileAccessLog[];
  loading: boolean;
  query: string;
  action: FileAccessAction | "all";
  onQueryChange: (q: string) => void;
  onActionChange: (a: FileAccessAction | "all") => void;
};

export function FileAccessLogPanel({
  rows,
  loading,
  query,
  action,
  onQueryChange,
  onActionChange,
}: Props) {
  const columns: DataTableColumn<FileAccessLog>[] = [
    {
      key: "accessed_at",
      label: "Accessed",
      render: (r) => formatDateTime(r.accessed_at),
    },
    {
      key: "file_name",
      label: "File",
      render: (r) => r.file_name ?? r.file_id,
    },
    {
      key: "user_display",
      label: "User",
      render: (r) => r.user_display ?? r.user_id,
    },
    {
      key: "action",
      label: "Action",
      render: (r) => (
        <StatusChip status={r.action} label={FILE_ACCESS_ACTION_LABELS[r.action]} />
      ),
    },
    {
      key: "ip_address",
      label: "IP",
      render: (r) => r.ip_address ?? "—",
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
          File access log
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Review uploads, views, downloads, and blocked deletion attempts.
        </Typography>
      </Box>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search file, user…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          fullWidth
        />
        <TextField
          select
          size="small"
          label="Action"
          value={action}
          onChange={(e) => onActionChange(e.target.value as FileAccessAction | "all")}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          {(Object.keys(FILE_ACCESS_ACTION_LABELS) as FileAccessAction[]).map((a) => (
            <MenuItem key={a} value={a}>
              {FILE_ACCESS_ACTION_LABELS[a]}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(r) => r.id}
        loading={loading}
        emptyMessage="No file access events."
      />
    </Box>
  );
}
