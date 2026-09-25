"use client";

import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { formatDateTime, formatJson, truncateHash } from "../lib/formatters";
import type { AuditLog } from "../types";
import { AuditActionChip } from "./AuditActionChip";

type Props = {
  entry: AuditLog | null;
  loading?: boolean;
};

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Box>
      <Typography sx={{ fontSize: "0.6875rem", fontWeight: 600, color: meridian.textSecondary, mb: 0.35 }}>
        {label}
      </Typography>
      <Typography
        component="div"
        sx={{
          fontSize: "0.8125rem",
          color: meridian.textPrimary,
          fontFamily: typeof value === "string" && value.length > 40 ? "ui-monospace, monospace" : "inherit",
          wordBreak: "break-all",
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}

export function AuditEntryDetail({ entry, loading }: Props) {
  const { t } = useLocale();

  async function copyText(label: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("audit.detail.copied"), label);
    } catch {
      toast.error(t("audit.detail.copyFailed"));
    }
  }

  if (loading) {
    return (
      <Typography sx={{ color: meridian.textSecondary, p: 2 }}>{t("audit.detail.loading")}</Typography>
    );
  }

  if (!entry) {
    return (
      <Box
        sx={{
          borderRadius: "16px",
          border: `1px dashed ${meridian.border}`,
          p: 4,
          textAlign: "center",
          color: meridian.textSecondary,
        }}
      >
        {t("audit.detail.selectPrompt")}
      </Box>
    );
  }

  return (
    <Box
      sx={{
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
        p: 2.5,
      }}
    >
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "flex-start", mb: 2, gap: 2 }}>
        <Box>
          <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
            {entry.id}
          </Typography>
          <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
            {formatDateTime(entry.created_at)} · {entry.role ?? "—"}
          </Typography>
        </Box>
        <AuditActionChip action={entry.action} />
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
          gap: 1.75,
          mb: 2.5,
        }}
      >
        <Field label="Resource" value={`${entry.resource_type} / ${entry.resource_id ?? "—"}`} />
        <Field label="User" value={entry.user_display ?? entry.user_id ?? "—"} />
        <Field label="Patient" value={entry.patient_display ?? entry.patient_id ?? "—"} />
        {entry.ip_address ? <Field label="IP address" value={entry.ip_address} /> : null}
        <Field
          label="entry_hash"
          value={
            <Stack direction="row" useFlexGap sx={{ gap: 1, alignItems: "center" }}>
              <span>{truncateHash(entry.entry_hash)}</span>
              {entry.entry_hash ? (
                <Button
                  size="small"
                  onClick={() => void copyText("entry_hash", entry.entry_hash!)}
                  sx={{ textTransform: "none" }}
                >
                  {t("audit.detail.copy")}
                </Button>
              ) : null}
            </Stack>
          }
        />
      </Box>

      <Typography sx={{ m: 0, mb: 1, fontSize: "0.75rem", color: meridian.textSecondary }}>
        Live GET /audit/logs returns this slim §4.4 shape (no prev_hash / signature /
        visit_id / IP on the wire).
      </Typography>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          gap: 2,
        }}
      >
        <Box>
          <Typography sx={{ mb: 0.75, fontSize: "0.8125rem", fontWeight: 700 }}>old_value</Typography>
          <Box
            component="pre"
            sx={{
              m: 0,
              p: 1.5,
              borderRadius: "12px",
              bgcolor: meridian.muted,
              fontSize: "0.75rem",
              overflow: "auto",
              maxHeight: 220,
            }}
          >
            {formatJson(entry.old_value)}
          </Box>
        </Box>
        <Box>
          <Typography sx={{ mb: 0.75, fontSize: "0.8125rem", fontWeight: 700 }}>new_value</Typography>
          <Box
            component="pre"
            sx={{
              m: 0,
              p: 1.5,
              borderRadius: "12px",
              bgcolor: meridian.muted,
              fontSize: "0.75rem",
              overflow: "auto",
              maxHeight: 220,
            }}
          >
            {formatJson(entry.new_value)}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
