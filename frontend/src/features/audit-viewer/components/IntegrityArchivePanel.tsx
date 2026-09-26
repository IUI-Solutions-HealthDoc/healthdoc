"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { VERIFICATION_STATUS_LABELS } from "../constants";
import { formatDateTime, truncateHash } from "../lib/formatters";
import type { AuditIntegrityCheck, AuditLogArchive } from "../types";

type Props = {
  checks: AuditIntegrityCheck[];
  archives: AuditLogArchive[];
  loading: boolean;
};

export function IntegrityArchivePanel({ checks, archives, loading }: Props) {
  const { t } = useLocale();
  if (loading) {
    return (
      <Typography sx={{ color: meridian.textSecondary, p: 2 }}>{t("audit.integrity.loading")}</Typography>
    );
  }

  return (
    <Stack spacing={2.5}>
      <Box
        sx={{
          borderRadius: "16px",
          border: `1px solid ${meridian.border}`,
          background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
          boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
          p: 2.5,
        }}
      >
        <Typography sx={{ m: 0, mb: 1.5, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
          {t("audit.integrity.checksTitle")}
        </Typography>
        {checks.length === 0 ? (
          <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>{t("audit.integrity.noChecks")}</Typography>
        ) : (
          <Stack spacing={1.5}>
            {checks.map((c) => (
              <Box
                key={c.id}
                sx={{
                  p: 1.75,
                  borderRadius: "12px",
                  border: `1px solid ${meridian.border}`,
                  bgcolor: c.chain_valid ? meridian.surface : "#fef2f2",
                }}
              >
                <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1, mb: 0.75 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: "0.875rem" }}>{c.partition_name}</Typography>
                  <StatusChip
                    status={c.chain_valid ? "verified" : "failed"}
                    label={c.chain_valid ? "Chain valid" : "Chain broken"}
                  />
                </Stack>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  Checked {formatDateTime(c.checked_at)} · {c.rows_checked.toLocaleString("en-IN")} rows
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  Signatures valid {c.signatures_valid} / invalid {c.signatures_invalid}
                  {c.first_mismatch_id ? ` · first mismatch ${c.first_mismatch_id}` : ""}
                  {c.alerted ? " · alerted" : ""}
                </Typography>
              </Box>
            ))}
          </Stack>
        )}
      </Box>

      <Box
        sx={{
          borderRadius: "16px",
          border: `1px solid ${meridian.border}`,
          background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
          boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
          p: 2.5,
        }}
      >
        <Typography sx={{ m: 0, mb: 1.5, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
          Archives
        </Typography>
        {archives.length === 0 ? (
          <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>No archives.</Typography>
        ) : (
          <Stack spacing={1.5}>
            {archives.map((a) => (
              <Box
                key={a.id}
                sx={{
                  p: 1.75,
                  borderRadius: "12px",
                  border: `1px solid ${meridian.border}`,
                }}
              >
                <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1, mb: 0.75 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: "0.875rem" }}>{a.partition_name}</Typography>
                  <StatusChip
                    status={a.verification_status}
                    label={VERIFICATION_STATUS_LABELS[a.verification_status]}
                  />
                </Stack>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  {a.period_start} → {a.period_end} · {a.row_count.toLocaleString("en-IN")} rows
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary, fontFamily: "ui-monospace, monospace" }}>
                  {a.object_storage_bucket}/{a.object_storage_key}
                </Typography>
                <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
                  hash {truncateHash(a.archive_file_hash)} · archived {formatDateTime(a.archived_at)}
                </Typography>
              </Box>
            ))}
          </Stack>
        )}
      </Box>
    </Stack>
  );
}
