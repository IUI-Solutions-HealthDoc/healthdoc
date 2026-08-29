"use client";

import { useState } from "react";
import Box from "@mui/material/Box";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { ExportButton } from "@/components/ui/ExportButton";
import { toast } from "@/components/ui/toast";
import { meridian } from "@/styles/theme";
import { exportAuditLogsCsv } from "../api";
import { useAuditEntry } from "../hooks/useAuditEntry";
import { useAuditLogs } from "../hooks/useAuditLogs";
import { useDataAccessLogs } from "../hooks/useDataAccessLogs";
import { useFileAccessLogs } from "../hooks/useFileAccessLogs";
import { useIntegritySummary } from "../hooks/useIntegritySummary";
import { auditRowKey } from "../lib/formatters";
import type { AuditLog } from "../types";
import { AuditEntryDetail } from "./AuditEntryDetail";
import { AuditLogListPanel } from "./AuditLogListPanel";
import { DataAccessLogPanel } from "./DataAccessLogPanel";
import { FileAccessLogPanel } from "./FileAccessLogPanel";
import { IntegrityArchivePanel } from "./IntegrityArchivePanel";

type TabKey = "audit" | "data_access" | "files" | "integrity";

export function AuditTrailDashboard() {
  const [tab, setTab] = useState<TabKey>("audit");
  const [selected, setSelected] = useState<{ id: string; created_at: string } | null>(null);
  const [exporting, setExporting] = useState(false);

  const logs = useAuditLogs({ action: "all", resource_type: "all" });
  const detail = useAuditEntry(selected?.id ?? null, selected?.created_at ?? null);
  const dataAccess = useDataAccessLogs({ access_channel: "all" });
  const files = useFileAccessLogs({ action: "all" });
  const integrity = useIntegritySummary();

  const selectedKey = selected ? auditRowKey(selected.id, selected.created_at) : null;

  const handleSelect = (row: AuditLog) => {
    setSelected({ id: row.id, created_at: row.created_at });
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const csv = await exportAuditLogsCsv(logs.filters);
      const blobUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
      toast.success("Audit CSV downloaded");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Audit export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 2 }}>
        <Box>
          <Typography
            component="h1"
            sx={{
              m: 0,
              fontSize: "1.5rem",
              fontWeight: 700,
              letterSpacing: "-0.03em",
              color: meridian.textPrimary,
            }}
          >
            Audit trail
          </Typography>
          <Typography sx={{ m: 0, mt: 0.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            Facility-scoped audit, data-access, file-access and integrity records from the live APIs.
          </Typography>
        </Box>
        <ExportButton
          formats={["csv"]}
          label="Export audit CSV"
          loading={exporting}
          onExport={handleExport}
        />
      </Box>

      <Box
        sx={{
          px: 2,
          py: 1.25,
          borderRadius: "12px",
          backgroundColor: "#e8eef5",
          color: meridian.brandPrimary,
          fontSize: "0.875rem",
          fontWeight: 600,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 2,
          flexWrap: "wrap",
        }}
      >
        <span>UPDATE/DELETE are blocked by trg_audit_logs_block_update — viewer is read-only.</span>
      </Box>

      <Tabs
        value={tab}
        onChange={(_, v: TabKey) => setTab(v)}
        sx={{
          minHeight: 40,
          "& .MuiTab-root": { textTransform: "none", fontWeight: 600, minHeight: 40 },
        }}
      >
        <Tab value="audit" label="Audit logs" />
        <Tab value="data_access" label="Access log" />
        <Tab value="files" label="File access" />
        <Tab value="integrity" label="Integrity" />
      </Tabs>

      {tab === "audit" ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", lg: "340px 1fr" },
            gap: 2.5,
            alignItems: "start",
          }}
        >
          <AuditLogListPanel
            rows={logs.rows}
            loading={logs.loading}
            query={logs.filters.query ?? ""}
            action={logs.filters.action ?? "all"}
            resourceType={logs.filters.resource_type ?? "all"}
            from={logs.filters.from ?? ""}
            to={logs.filters.to ?? ""}
            selectedKey={selectedKey}
            onQueryChange={logs.setQuery}
            onActionChange={logs.setAction}
            onResourceTypeChange={logs.setResourceType}
            onFromChange={logs.setFrom}
            onToChange={logs.setTo}
            onSelect={handleSelect}
          />
          <AuditEntryDetail entry={detail.entry} loading={detail.loading} />
        </Box>
      ) : null}

      {tab === "data_access" ? (
        <DataAccessLogPanel
          rows={dataAccess.rows}
          loading={dataAccess.loading}
          query={dataAccess.filters.query ?? ""}
          accessChannel={dataAccess.filters.access_channel ?? "all"}
          onQueryChange={dataAccess.setQuery}
          onAccessChannelChange={dataAccess.setAccessChannel}
        />
      ) : null}

      {tab === "files" ? (
        <FileAccessLogPanel
          rows={files.rows}
          loading={files.loading}
          query={files.filters.query ?? ""}
          action={files.filters.action ?? "all"}
          onQueryChange={files.setQuery}
          onActionChange={files.setAction}
        />
      ) : null}

      {tab === "integrity" ? (
        <IntegrityArchivePanel
          checks={integrity.checks}
          archives={integrity.archives}
          loading={integrity.loading}
        />
      ) : null}
    </Box>
  );
}
