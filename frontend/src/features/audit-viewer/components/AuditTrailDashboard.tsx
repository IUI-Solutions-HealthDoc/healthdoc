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
import { toCsv } from "../lib/toCsv.mjs";
import { useAuditEntry } from "../hooks/useAuditEntry";
import { useAuditLogs } from "../hooks/useAuditLogs";
import { useAuditResourceTypes } from "../hooks/useAuditResourceTypes";
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
  const resourceTypes = useAuditResourceTypes();

  const selectedKey = selected ? auditRowKey(selected.id, selected.created_at) : null;

  const handleSelect = (row: AuditLog) => {
    setSelected({ id: row.id, created_at: row.created_at });
  };

  /**
   * Export what the reader is looking at.
   *
   * This button used to sit above the tabs and always call
   * exportAuditLogsCsv(logs.filters) — so viewing Access log and pressing
   * Export handed you AUDIT rows, filtered by the AUDIT tab's dropdowns, with
   * a toast saying it worked. The other three tabs had no export at all.
   *
   * The audit tab keeps the server endpoint on purpose: that request writes
   * its own audit_logs row ("the export itself is the compliance event", per
   * app/audit/router.py), and it reads the whole result set rather than the
   * page the screen happens to hold. The other tabs have no such endpoint, so
   * they serialise the rows already on screen.
   */
  const download = (csv: string, name: string) => {
    const blobUrl = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `${name}_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      if (tab === "audit") {
        const csv = await exportAuditLogsCsv(logs.filters);
        download(csv, "audit_logs");
        // Say which rows were NOT covered rather than let the file quietly
        // disagree with the screen. `action` and `query` are client-side only,
        // so the server cannot honour them and the CSV is wider than the view.
        const clientOnly =
          (logs.filters.action && logs.filters.action !== "all") || logs.filters.query?.trim();
        toast.success(
          clientOnly
            ? "Audit CSV downloaded — server filters only; Action/Search are not applied to the file"
            : "Audit CSV downloaded",
        );
        return;
      }

      const { rows, name } =
        tab === "data_access"
          ? { rows: dataAccess.rows as Record<string, unknown>[], name: "data_access_log" }
          : tab === "files"
            ? { rows: files.rows as unknown as Record<string, unknown>[], name: "file_access_log" }
            : { rows: integrity.checks as unknown as Record<string, unknown>[], name: "integrity_checks" };

      if (rows.length === 0) {
        // Never hand over a headers-only file and call it a success. An empty
        // evidence export that reports "downloaded" is how an inspection gets
        // nothing and nobody notices.
        toast.error("Nothing to export on this tab with the current filters");
        return;
      }
      download(toCsv(rows), name);
      toast.success(`${rows.length} row(s) exported`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Export failed");
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
          label={
            tab === "audit"
              ? "Export audit CSV"
              : tab === "data_access"
                ? "Export access log CSV"
                : tab === "files"
                  ? "Export file access CSV"
                  : "Export integrity CSV"
          }
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
        {/* Was: "UPDATE/DELETE are blocked by trg_audit_logs_block_update —
            viewer is read-only." A database trigger name shown to an auditor.
            The fact is worth stating — an assessor specifically wants to know
            the trail cannot be edited — but it has to be stated in a way the
            reader can act on. The trigger name belongs in the schema docs. */}
        <span>
          Audit records cannot be edited or deleted, including by administrators.
        </span>
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
        <>
        {logs.error || detail.error ? (
          <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
            {logs.error ?? detail.error}
          </Typography>
        ) : null}
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
          resourceTypes={resourceTypes}
            onFromChange={logs.setFrom}
            onToChange={logs.setTo}
            onSelect={handleSelect}
          />
          <AuditEntryDetail entry={detail.entry} loading={detail.loading} />
        </Box>
        </>
      ) : null}

      {tab === "data_access" ? (
        <>
        {dataAccess.error ? (
          <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
            {dataAccess.error}
          </Typography>
        ) : null}
        <DataAccessLogPanel
          rows={dataAccess.rows}
          loading={dataAccess.loading}
          query={dataAccess.filters.query ?? ""}
          accessChannel={dataAccess.filters.access_channel ?? "all"}
          onQueryChange={dataAccess.setQuery}
          onAccessChannelChange={dataAccess.setAccessChannel}
        />
        </>
      ) : null}

      {tab === "files" ? (
        <>
        {files.error ? (
          <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
            {files.error}
          </Typography>
        ) : null}
        <FileAccessLogPanel
          rows={files.rows}
          loading={files.loading}
          query={files.filters.query ?? ""}
          action={files.filters.action ?? "all"}
          onQueryChange={files.setQuery}
          onActionChange={files.setAction}
        />
        </>
      ) : null}

      {tab === "integrity" ? (
        <>
        {integrity.error ? (
          <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
            {integrity.error}
          </Typography>
        ) : null}
        <IntegrityArchivePanel
          checks={integrity.checks}
          archives={integrity.archives}
          loading={integrity.loading}
        />
        </>
      ) : null}
    </Box>
  );
}
