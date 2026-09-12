"use client";

import { useCallback, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { StatusChip } from "@/components/ui/StatusChip";
import { toast } from "@/components/ui/toast";
import { meridian } from "@/styles/theme";
import { transitionConsentStatus, withdrawConsent } from "../api/consent";
import { CONSENT_STATUS_LABELS } from "../constants";
import { formatDate, formatDateTime } from "../lib/formatters";
import type { ConsentRecord } from "../types";
import { ConsentAccessHistory } from "./ConsentAccessHistory";

type Props = {
  record: ConsentRecord | null;
  loading?: boolean;
  onRecordUpdated?: (next: ConsentRecord) => void;
};

export function ConsentRecordDetail({
  record,
  loading,
  onRecordUpdated,
}: Props) {
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [busy, setBusy] = useState(false);

  const handleWithdraw = useCallback(async () => {
    if (!record) return;
    setBusy(true);
    try {
      const next = await withdrawConsent(record.id, {
        withdrawn_by_type: "patient",
        reason: withdrawReason || null,
      });
      toast.success("Consent withdrawn");
      setWithdrawOpen(false);
      setWithdrawReason("");
      onRecordUpdated?.(next);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Withdrawal failed");
    } finally {
      setBusy(false);
    }
  }, [record, withdrawReason, onRecordUpdated]);

  const handleTransition = useCallback(
    async (status: "granted" | "denied") => {
      if (!record) return;
      setBusy(true);
      try {
        const next = await transitionConsentStatus(record.id, { status });
        toast.success(`Consent ${status}`);
        onRecordUpdated?.(next);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Transition failed");
      } finally {
        setBusy(false);
      }
    },
    [record, onRecordUpdated],
  );
  if (loading) {
    return (
      <Typography sx={{ color: meridian.textSecondary, p: 2 }}>Loading consent…</Typography>
    );
  }

  if (!record) {
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
        Select a consent record to review the decision and expiry.
      </Box>
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
        <Stack direction="row" sx={{ justifyContent: "space-between", gap: 2, mb: 2 }}>
          <Box>
            <Typography sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}>
              {record.patient?.name ?? record.patient_id}
            </Typography>
            <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
              {record.patient?.uhid} · {record.id}
            </Typography>
          </Box>
          <StatusChip status={record.status} label={CONSENT_STATUS_LABELS[record.status]} />
        </Stack>

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 1.75,
          }}
        >
          <Meta label="Purpose" value={record.purpose_label ?? record.purpose_code ?? record.purpose_id} />
          <Meta label="Channel" value={record.channel} />
          <Meta
            label="Expires"
            value={record.expires_at ? formatDate(record.expires_at) : "open-ended"}
          />
          <Meta label="Granted" value={formatDateTime(record.granted_at)} />
          <Meta label="Granted by" value={String(record.granted_by_type)} />
          <Meta
            label="Status changed"
            value={formatDateTime(record.status_changed_at)}
          />
        </Box>

        {record.status === "granted" ? (
          <Button
            size="small"
            variant="outlined"
            color="error"
            disabled={busy}
            onClick={() => setWithdrawOpen(true)}
            sx={{ mt: 1, textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
          >
            Withdraw consent
          </Button>
        ) : null}

        {record.status === "requested" ? (
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Button
              size="small"
              variant="contained"
              color="success"
              disabled={busy}
              onClick={() => void handleTransition("granted")}
              sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
            >
              Approve
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="error"
              disabled={busy}
              onClick={() => void handleTransition("denied")}
              sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
            >
              Deny
            </Button>
          </Stack>
        ) : null}
      </Box>

      <Dialog open={withdrawOpen} onClose={() => setWithdrawOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>Withdraw consent</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 1.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            This will revoke the consent record. The action is logged in the audit trail.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            size="small"
            label="Reason (optional)"
            value={withdrawReason}
            onChange={(e) => setWithdrawReason(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setWithdrawOpen(false)} sx={{ textTransform: "none" }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            disabled={busy}
            onClick={() => void handleWithdraw()}
            sx={{ textTransform: "none", fontWeight: 600 }}
          >
            Confirm withdrawal
          </Button>
        </DialogActions>
      </Dialog>

      <ConsentAccessHistory consentId={record.id} />
    </Stack>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography sx={{ fontSize: "0.6875rem", fontWeight: 600, color: meridian.textSecondary, mb: 0.35 }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: "0.8125rem", color: meridian.textPrimary }}>{value}</Typography>
    </Box>
  );
}
