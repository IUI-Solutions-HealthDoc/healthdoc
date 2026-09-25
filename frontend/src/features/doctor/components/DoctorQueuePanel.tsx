"use client";

import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import { Badge } from "@/components/ui/Badge";
import { MetricCard } from "@/components/ui";
import { PRIORITY_META } from "../constants";
import type { QueueToken } from "../types";
import { useLocale } from "@/lib/i18n";

export interface DoctorQueuePanelProps {
  patients: QueueToken[];
  loading: boolean;
  selectedId?: string | null;
  onSelect: (patient: QueueToken) => void;
}

export function DoctorQueuePanel({
  patients,
  loading,
  selectedId = null,
  onSelect,
}: DoctorQueuePanelProps) {
  const { t } = useLocale();
  const today = new Date().toISOString().slice(0, 10);
  const waiting = patients.filter(
    (r) => r.status === "waiting" || r.status === "called" || r.status === "recalled",
  ).length;
  const inService = patients.filter((r) => r.status === "in_service").length;
  const completed = patients.filter(
    (r) => r.status === "completed" && (!r.completed_at || r.completed_at.slice(0, 10) === today),
  ).length;

  const columns: DataTableColumn<QueueToken>[] = [
    { key: "token_display", label: t("doctor.queueColToken"), sortable: true, width: 96 },
    {
      key: "full_name",
      label: t("doctor.queueColPatient"),
      sortable: true,
      render: (row) => (
        <Box>
          <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>{row.full_name}</Typography>
          <Typography sx={{ fontSize: "0.75rem", color: "text.secondary" }}>
            {row.uhid} · {row.age_years}/{row.sex[0].toUpperCase()}
          </Typography>
        </Box>
      ),
    },
    {
      key: "priority",
      label: t("doctor.queueColPriority"),
      render: (row) => {
        const meta = PRIORITY_META[row.priority];
        return meta ? <Badge variant={meta.variant}>{meta.label}</Badge> : null;
      },
    },
    { key: "status", label: t("doctor.queueColStatus"), render: (row) => <StatusChip status={row.status} /> },
    {
      key: "wait_minutes",
      label: t("doctor.queueColWait"),
      sortable: true,
      align: "right",
      render: (row) => `${Math.max(0, Math.round((Date.now() - Date.parse(row.created_at)) / 60000))} min`,
    },
  ];

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 2 }}>
        <MetricCard label={t("doctor.queueWaiting")} value={waiting} size="sm" loading={loading} />
        <MetricCard label={t("doctor.queueInService")} value={inService} size="sm" loading={loading} />
        <MetricCard label={t("doctor.queueCompletedToday")} value={completed} size="sm" loading={loading} />
      </Box>

      <DataTable<QueueToken>
        columns={columns}
        rows={patients}
        loading={loading}
        getRowId={(r) => r.id}
        selectedRowId={selectedId}
        onRowClick={onSelect}
        emptyMessage={t("doctor.queueEmpty")}
      />
    </Box>
  );
}
