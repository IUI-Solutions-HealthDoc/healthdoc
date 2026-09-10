"use client";

import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { doctorPageHeaderSx } from "../panelSx";
import { useResults } from "../hooks/useResults";
import { ResultDetailPanel } from "./ResultDetailPanel";
import { ResultsWorklistPanel } from "./ResultsWorklistPanel";
import { ExternalReferralInbox } from "./ExternalReferralInbox";

export function ResultsWorkspace() {
  const [source, setSource] = useState("local");
  return <Box>
    <Tabs value={source} onChange={(_event, value: string) => setSource(value)} aria-label="Results source" sx={{ mb: 2 }}>
      <Tab id="local-results-tab" aria-controls="local-results-panel" value="local" label="Local results" />
      <Tab id="external-results-tab" aria-controls="external-results-panel" value="external" label="External referrals" />
    </Tabs>
    <Box role="tabpanel" id={`${source}-results-panel`} aria-labelledby={`${source}-results-tab`}>
      {source === "local" ? <LocalResultsWorkspace /> : <ExternalReferralInbox />}
    </Box>
  </Box>;
}

/**
 * Week 5 — result viewers + doctor sign-off. Stacked single-purpose panels,
 * same treatment as the consultation screen: worklist on top, the opened
 * result below it.
 */
function LocalResultsWorkspace() {
  const {
    items,
    counts,
    loading,
    error,
    filter,
    setFilter,
    selected,
    select,
    detailLoading,
    labResult,
    radReport,
    labVersions,
    radVersions,
    viewingVersion,
    setViewingVersion,
    viewingIsCurrent,
    review,
    signing,
    advance,
  } = useResults();

  const versions = (selected?.order_type === "lab" ? labVersions : radVersions).map((v) => ({
    version: v.version,
    is_current: v.is_current,
    status: v.status,
    created_at: v.created_at,
  }));

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Box sx={doctorPageHeaderSx}>
        <Typography
          sx={{
            m: 0,
            mb: 0.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: meridian.textSecondary,
          }}
        >
          OPD · Doctor
        </Typography>
        <Typography
          component="h1"
          sx={{
            m: 0,
            fontSize: { xs: "1.375rem", md: "1.5rem" },
            fontWeight: 700,
            letterSpacing: "-0.03em",
            color: meridian.textPrimary,
            lineHeight: 1.2,
          }}
        >
          Results review
        </Typography>
        <Typography
          sx={{
            m: 0,
            mt: 0.6,
            fontSize: "0.875rem",
            color: meridian.textSecondary,
            maxWidth: 620,
            lineHeight: 1.45,
          }}
        >
          Lab and radiology results for your orders. Critical values surface first — open a result,
          review it, then sign it off.
        </Typography>
      </Box>

      {error ? (
        <Alert severity="error" sx={{ borderRadius: "12px" }}>
          {error}
        </Alert>
      ) : null}

      <ResultsWorklistPanel
        items={items}
        loading={loading}
        filter={filter}
        counts={counts}
        selectedId={selected?.id ?? null}
        onFilterChange={setFilter}
        onSelect={select}
      />

      <ResultDetailPanel
        item={selected}
        loading={detailLoading}
        labResult={labResult}
        radReport={radReport}
        versions={versions}
        viewingVersion={viewingVersion}
        onVersionChange={setViewingVersion}
        viewingIsCurrent={viewingIsCurrent}
        review={review}
        
        signing={signing}
        onSign={(notes?: string) => advance("signed_off", notes)}
        onMarkReviewed={() => advance("reviewed")}
      />
    </Box>
  );
}
