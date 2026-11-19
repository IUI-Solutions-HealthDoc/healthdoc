"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { DataTable, type DataTableColumn } from "@/components/tables/DataTable";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { StatusChip } from "@/components/ui/StatusChip";
import { meridian } from "@/styles/theme";
import { formatDateTime } from "../lib/formatters";
import { doctorPanelSx, doctorButtonSx } from "../panelSx";
import type { OrderPriority, ResultWorklistItem } from "../types";
import type { ResultsFilter } from "../hooks/useResults";
import { CriticalBadge } from "./CriticalBadge";
import { useLocale, translate } from "@/lib/i18n";

const PRIORITY_BADGE: Record<OrderPriority, BadgeVariant> = {
  routine: "secondary",
  urgent: "outline",
  stat: "destructive",
};

export interface ResultsWorklistPanelProps {
  items: ResultWorklistItem[];
  loading: boolean;
  filter: ResultsFilter;
  counts: { total: number; unread: number; critical: number };
  selectedId: string | null;
  onFilterChange: (f: ResultsFilter) => void;
  onSelect: (item: ResultWorklistItem) => void;
}

export function ResultsWorklistPanel({
  items,
  loading,
  filter,
  counts,
  selectedId,
  onFilterChange,
  onSelect,
}: ResultsWorklistPanelProps) {
  const { t } = useLocale();
  const filters: { value: ResultsFilter; label: string; count: number }[] = [
    { value: "all", label: "All", count: counts.total },
    { value: "unread", label: translate("doctor.ui.awaitingSignOff"), count: counts.unread },
    { value: "critical", label: translate("equipment.critical"), count: counts.critical },
  ];

  const columns: DataTableColumn<ResultWorklistItem>[] = [
    {
      key: "accession_number",
      label: translate("lab.col.accession"),
      sortable: true,
      width: 170,
      render: (row) => (
        <Box>
          <Typography sx={{ fontSize: "0.8125rem", fontWeight: 600 }}>
            {row.accession_number}
          </Typography>
          <Typography sx={{ fontSize: "0.6875rem", color: meridian.textSecondary }}>
            {row.order_number}
          </Typography>
        </Box>
      ),
    },
    {
      key: "patient_name",
      label: translate("common.patient"),
      sortable: true,
      render: (row) => (
        <Box>
          <Typography sx={{ fontWeight: 600, fontSize: "0.875rem" }}>{row.patient_name}</Typography>
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
            {row.uhid}
          </Typography>
        </Box>
      ),
    },
    {
      key: "test_name",
      label: translate("doctor.msg.testStudy"),
      sortable: true,
      render: (row) => (
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", gap: 0.75 }}>
          <Typography sx={{ fontSize: "0.875rem" }}>{row.test_name}</Typography>
          <Badge variant="outline">
            {row.order_type === "lab" ? t("doctor.orderType.lab") : (row.modality?.toUpperCase() ?? t("sidebar.radiology"))}
          </Badge>
        </Stack>
      ),
    },
    {
      key: "priority",
      label: translate("receptionist.priority"),
      width: 110,
      render: (row) =>
        row.priority === "routine" ? null : (
          <Badge variant={PRIORITY_BADGE[row.priority]}>
            {row.priority === "stat" ? "STAT" : t("doctor.orderPriority.urgent")}
          </Badge>
        ),
    },
    {
      key: "result_status",
      label: translate("common.ui.result"),
      width: 170,
      render: (row) => (
        <Stack direction="row" spacing={0.75} sx={{ alignItems: "center", flexWrap: "wrap", gap: 0.5 }}>
          {row.result_status ? (
            <StatusChip status={row.result_status} />
          ) : (
            <StatusChip status={row.status} />
          )}
          {false && <CriticalBadge />}
        </Stack>
      ),
    },
    {
      key: "reported_at",
      label: translate("nurse.msg.reported"),
      sortable: true,
      align: "right",
      width: 150,
      render: (row) =>
        row.reported_at ? (
          <Box>
            <Typography sx={{ fontSize: "0.75rem" }}>{formatDateTime(row.reported_at)}</Typography>
            {row.review_status === "signed_off" ? (
              <Typography sx={{ fontSize: "0.6875rem", color: meridian.success, fontWeight: 600 }}>{t("doctor.ui.signedOff")}</Typography>
            ) : (
              <Typography sx={{ fontSize: "0.6875rem", color: meridian.warning, fontWeight: 600 }}>{t("doctor.ui.awaitingSignOff")}</Typography>
            )}
          </Box>
        ) : (
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>—</Typography>
        ),
    },
  ];

  return (
    <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 2 }}>
      <Stack direction="row" spacing={2} sx={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <Box>
          <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("sidebar.results")}</Typography>
          <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, mt: 0.25 }}>{t("doctor.ui.labAndRadiologyResultsForYour")}</Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          {filters.map((f) => (
            <Button
              key={f.value}
              size="small"
              variant={filter === f.value ? "contained" : "outlined"}
              sx={doctorButtonSx}
              onClick={() => onFilterChange(f.value)}
            >
              {f.label} ({f.count})
            </Button>
          ))}
        </Stack>
      </Stack>

      <DataTable<ResultWorklistItem>
        columns={columns}
        rows={items}
        loading={loading}
        getRowId={(r) => r.id}
        onRowClick={onSelect}
        selectedRowId={selectedId}
        emptyMessage={t("doctor.ui.noResultsInThisView")}
      />
    </Box>
  );
}
