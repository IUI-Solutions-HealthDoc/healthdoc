"use client";

import { formatAgeSexShort } from "@/lib/format-age";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Link from "next/link";

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

/**
 * Minutes waited. The wait ends when the patient is called or seen: counting
 * on to "now" made a completed patient's wait keep rising (QA 12 Oct 2026).
 */
export function waitMinutes(row: Pick<QueueToken, "status" | "created_at" | "called_at" | "completed_at">, now = Date.now()): number {
  const start = Date.parse(row.created_at);
  const stillWaiting = row.status === "waiting" || row.status === "recalled";
  const end = stillWaiting ? now : Date.parse(row.called_at ?? row.completed_at ?? "") || now;
  return Math.max(0, Math.round((end - start) / 60000));
}

export function DoctorQueuePanel({
  patients,
  loading,
  selectedId = null,
  onSelect,
}: DoctorQueuePanelProps) {
  const { t } = useLocale();
  // The facility's day, not UTC's: before 05:30 IST a UTC date is yesterday.
  const istDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const today = istDay(new Date());
  const waiting = patients.filter(
    (r) => r.status === "waiting" || r.status === "called" || r.status === "recalled",
  ).length;
  const inService = patients.filter((r) => r.status === "in_service").length;
  const completed = patients.filter(
    (r) => r.status === "completed" && (!r.completed_at || istDay(new Date(r.completed_at)) === today),
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
            {row.uhid} · {formatAgeSexShort(row.age_years, row.sex)}
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
      render: (row) => `${waitMinutes(row)} min`,
    },
    {
      key: "id",
      label: t("doctor.queueColAction"),
      // Every waiting row needs a way in; the row click only selected it for
      // the summary, and nothing said so (QA 10 Oct 2026).
      render: (row) =>
        row.status === "completed" || row.status === "cancelled" ? null : (
          <Link
            href={`/doctor/consultation?token=${row.id}`}
            onClick={(event) => event.stopPropagation()}
            className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-white"
          >
            {row.status === "in_service" ? t("doctor.queueContinue") : t("doctor.queueStartConsultation")}
          </Link>
        ),
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
