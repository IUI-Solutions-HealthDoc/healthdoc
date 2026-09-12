"use client";

import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";

import { useAuth } from "@/providers/auth-provider";
import { ACCESS_CHANNEL_LABELS } from "../constants";
import { useDataAccessLogs } from "../hooks/useDataAccessLogs";
import { DataAccessLogPanel } from "./DataAccessLogPanel";

export function ConsentAccessHistory({ consentId }: { consentId: string }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <Typography role="status">Checking access-history permissions…</Typography>;
  // Creating or reviewing consent does not grant access to the audit ledger.
  // The server retains its independent auditor/admin authorization check.
  if (user?.role !== "auditor" && user?.role !== "admin") {
    return <Typography>Data access history is available to facility administrators and auditors.</Typography>;
  }
  return <AuthorizedAccessHistory key={`${user.id}:${user.role}:${consentId}`} consentId={consentId} />;
}

function AuthorizedAccessHistory({ consentId }: { consentId: string }) {
  const access = useDataAccessLogs(consentId);
  if (access.error) {
    return <div>
      <Typography role="alert">Access history could not be loaded. {access.error}</Typography>
      <Button onClick={() => void access.refresh()}>Retry access history</Button>
    </div>;
  }
  return <DataAccessLogPanel rows={access.rows} loading={access.loading} channels={ACCESS_CHANNEL_LABELS} />;
}
