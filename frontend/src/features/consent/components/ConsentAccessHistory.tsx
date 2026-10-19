"use client";

import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";

import { useLocale } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { accessChannelLabels } from "../i18nLabels";
import { useDataAccessLogs } from "../hooks/useDataAccessLogs";
import { DataAccessLogPanel } from "./DataAccessLogPanel";

export function ConsentAccessHistory({ consentId }: { consentId: string }) {
  const { t } = useLocale();
  const { user, isLoading } = useAuth();
  if (isLoading) return <Typography role="status">{t("consent.ui.checkingAccessHistoryPermissions")}</Typography>;
  // Creating or reviewing consent does not grant access to the audit ledger.
  // The server retains its independent auditor/admin authorization check.
  if (user?.role !== "auditor" && user?.role !== "admin") {
    return <Typography>{t("consent.ui.dataAccessHistoryIsAvailableTo")}</Typography>;
  }
  return <AuthorizedAccessHistory key={`${user.id}:${user.role}:${consentId}`} consentId={consentId} />;
}

function AuthorizedAccessHistory({ consentId }: { consentId: string }) {
  const { t } = useLocale();
  const access = useDataAccessLogs(consentId);
  if (access.error) {
    return <div>
      <Typography role="alert">{t("consent.ui.accessHistoryCouldNotBeLoaded", { error: access.error })}</Typography>
      <Button onClick={() => void access.refresh()}>{t("consent.ui.retryAccessHistory")}</Button>
    </div>;
  }
  return (
    <DataAccessLogPanel
      rows={access.rows}
      loading={access.loading}
      channels={accessChannelLabels(t)}
    />
  );
}
