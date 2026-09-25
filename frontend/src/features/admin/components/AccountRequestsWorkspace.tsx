"use client";

import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { toast } from "@/components/ui/toast";
import { useCurrentUser } from "@/features/session/useCurrentUser";
import { useLocale } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { approveAccountRequest, rejectAccountRequest } from "../api";
import { REALM_ROLE_LABELS } from "../constants";
import { useAccountRequests } from "../hooks/useAccountRequests";
import { adminPanelSx, adminStickyActionsSx } from "../panelSx";
import type { UserAccountRequest } from "../types";
import { AdminPageHeader } from "./AdminPageHeader";
import { ApprovalStatusChip } from "./ApprovalStatusChip";
import { CreateAccountRequestModal } from "./CreateAccountRequestModal";

export function AccountRequestsWorkspace() {
  const { t } = useLocale();
  const { user: currentUser } = useCurrentUser();
  const { items, loading, error: loadError, status, setStatus, refresh } = useAccountRequests("pending");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [rejection_reason, setRejectionReason] = useState("");
  /**
   * Approval creates the Keycloak account, so it needs the temporary password
   * the new member of staff will first sign in with. The fixture needed none
   * because it created nothing — this field is new with the real endpoint.
   */
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);

  const selected: UserAccountRequest | null =
    items.find((r) => r.id === selectedId) ?? null;
  const isOwnRequest = Boolean(selected && currentUser?.id === selected.requested_by);

  useEffect(() => {
    setDecision(null);
    setTemporaryPassword("");
    setRejectionReason("");
  }, [selectedId]);

  const onApprove = async () => {
    if (!selected) return;
    if (temporaryPassword.trim().length < 8) {
      toast.error(t("admin.accountRequests.temporaryPasswordRequired"));
      return;
    }
    setBusy(true);
    try {
      await approveAccountRequest(selected.id, temporaryPassword);
      toast.success(t("admin.accountRequests.approveSuccess"), t("admin.accountRequests.approveSuccessDetail"));
      setTemporaryPassword("");
      setDecision(null);
      setSelectedId(null);
      void refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("admin.accountRequests.approveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const onReject = async () => {
    if (!selected) return;
    if (!rejection_reason.trim()) {
      toast.error(t("admin.accountRequests.rejectReasonRequired"));
      return;
    }
    setBusy(true);
    try {
      await rejectAccountRequest(selected.id, rejection_reason);
      toast.success(t("admin.accountRequests.rejectSuccess"));
      setRejectionReason("");
      setDecision(null);
      setSelectedId(null);
      void refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("admin.accountRequests.rejectFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <AdminPageHeader
        backHref="/admin"
        eyebrow={t("admin.eyebrow")}
        title={t("admin.hub.accountRequestsTitle")}
        subtitle={t("admin.hub.accountRequestsSubtitle")}
        actions={
          <Button
            variant="contained"
            color="primary"
            onClick={() => setCreateOpen(true)}
            sx={{
              textTransform: "none",
              fontWeight: 700,
              borderRadius: "10px",
              bgcolor: meridian.brandPrimary,
              color: "#ffffff",
              "&:hover": { bgcolor: meridian.brandDeep },
            }}
          >
            {t("admin.accountRequests.newRequest")}
          </Button>
        }
      />

      {loadError ? (
        <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
          {loadError}
        </Typography>
      ) : null}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "360px 1fr" },
          gap: 2.5,
          alignItems: "stretch",
        }}
      >
        <Box
          sx={{
            ...adminPanelSx,
            p: 0,
            overflow: "hidden",
            minHeight: 420,
            height: "100%",
          }}
        >
          <Box sx={{ p: 2.5, pb: 1.5 }}>
            <TextField
              select
              size="small"
              fullWidth
              label={t("common.status")}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as typeof status);
                setSelectedId(null);
              }}
            >
              <MenuItem value="all">{t("common.all")}</MenuItem>
              <MenuItem value="pending">{t("admin.accountRequests.status.pending")}</MenuItem>
              <MenuItem value="approved">{t("admin.accountRequests.status.approved")}</MenuItem>
              <MenuItem value="rejected">{t("admin.accountRequests.status.rejected")}</MenuItem>
            </TextField>
          </Box>
          <Box sx={{ borderTop: `1px solid ${meridian.border}`, maxHeight: 520, overflowY: "auto" }}>
            {loading ? (
              <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
                {t("common.loading")}
              </Typography>
            ) : items.length === 0 ? (
              <Typography sx={{ p: 2.5, color: meridian.textSecondary, fontSize: "0.875rem" }}>
                {t("admin.accountRequests.noRequests")}
              </Typography>
            ) : (
              items.map((row) => (
                <Box
                  key={row.id}
                  component="button"
                  type="button"
                  onClick={() => setSelectedId(row.id)}
                  sx={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    border: 0,
                    borderBottom: `1px solid ${meridian.border}`,
                    borderLeft:
                      row.id === selectedId
                        ? `3px solid ${meridian.brandPrimary}`
                        : "3px solid transparent",
                    px: 2.5,
                    py: 1.5,
                    cursor: "pointer",
                    backgroundColor: row.id === selectedId ? "#e8eef5" : "transparent",
                    "&:hover": {
                      backgroundColor:
                        row.id === selectedId ? "#e8eef5" : meridian.muted,
                    },
                  }}
                >
                  <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1 }}>
                    <Box>
                      <Typography sx={{ m: 0, fontWeight: 600, color: meridian.textPrimary }}>
                        {row.requested_for_full_name}
                      </Typography>
                      <Typography
                        sx={{
                          m: 0,
                          mt: 0.35,
                          fontSize: "0.75rem",
                          fontFamily: "var(--font-ibm-plex-mono), monospace",
                          color: meridian.brandPrimary,
                        }}
                      >
                        {row.requested_username}
                      </Typography>
                    </Box>
                    <ApprovalStatusChip status={row.status} />
                  </Stack>
                </Box>
              ))
            )}
          </Box>
        </Box>

        {!selected ? (
          <Box
            sx={{
              borderRadius: "16px",
              border: `1px dashed ${meridian.border}`,
              background: `linear-gradient(180deg, ${meridian.muted} 0%, #eef3f8 100%)`,
              p: 4,
              minHeight: 420,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              gap: 1,
              color: meridian.textSecondary,
            }}
          >
            <Typography sx={{ m: 0, fontWeight: 700, fontSize: "1rem", color: meridian.textPrimary }}>
              {t("admin.accountRequests.noRequestSelected")}
            </Typography>
            <Typography sx={{ m: 0, fontSize: "0.875rem", maxWidth: 300 }}>
              {t("admin.accountRequests.selectFromQueue")}
            </Typography>
          </Box>
        ) : (
          <Box
            sx={{
              ...adminPanelSx,
              p: 0,
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              minHeight: 420,
            }}
          >
            <Box sx={{ px: 2.5, pt: 2.5, pb: 2, borderBottom: `1px solid ${meridian.border}` }}>
              <Stack direction="row" sx={{ justifyContent: "space-between", gap: 2, mb: 1 }}>
                <Typography
                  sx={{ m: 0, fontSize: "1.125rem", fontWeight: 700, color: meridian.textPrimary }}
                >
                  {selected.requested_for_full_name}
                </Typography>
                <ApprovalStatusChip status={selected.status} />
              </Stack>
              <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>
                username {selected.requested_username} · roles{" "}
                {selected.requested_roles.map((r) => REALM_ROLE_LABELS[r]).join(", ")}
              </Typography>
            </Box>

            <Box sx={{ px: 2.5, py: 2.5, flex: 1 }}>
              <Typography sx={{ fontSize: "0.875rem", color: meridian.textPrimary, mb: 1.5 }}>
                <Box component="span" sx={{ fontWeight: 700 }}>{t("admin.accountRequests.justification")} </Box>
                {selected.justification}
              </Typography>
              <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary, mb: 2 }}>
                requested_by {selected.requested_by}
                {selected.decided_by ? ` · decided_by ${selected.decided_by}` : ""}
                {selected.created_user_id ? ` · created_user_id ${selected.created_user_id}` : ""}
                {selected.rejection_reason
                  ? ` · rejection_reason ${selected.rejection_reason}`
                  : ""}
              </Typography>

              {selected.status === "pending" ? (
                <>
                  {isOwnRequest ? (
                    <Box
                      role="status"
                      sx={{
                        borderRadius: "10px",
                        border: `1px solid ${meridian.border}`,
                        bgcolor: meridian.muted,
                        p: 2,
                        color: meridian.textSecondary,
                        fontSize: "0.875rem",
                      }}
                    >
                      {t("admin.accountRequests.makerCheckerOwnRequest")}
                    </Box>
                  ) : decision === "approve" ? (
                    <TextField
                      autoFocus
                      label={t("admin.accountRequests.temporaryPassword")}
                      type="password"
                      size="small"
                      fullWidth
                      value={temporaryPassword}
                      onChange={(e) => setTemporaryPassword(e.target.value)}
                      helperText={t("admin.accountRequests.temporaryPasswordHint")}
                    />
                  ) : decision === "reject" ? (
                    <TextField
                      autoFocus
                      label={t("admin.accountRequests.rejectionReason")}
                      size="small"
                      fullWidth
                      value={rejection_reason}
                      onChange={(e) => setRejectionReason(e.target.value)}
                      helperText={t("admin.accountRequests.rejectionReasonHint")}
                    />
                  ) : (
                    <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary }}>
                      {t("admin.accountRequests.chooseDecision")}
                    </Typography>
                  )}
                </>
              ) : null}
            </Box>

            {selected.status === "pending" && !isOwnRequest ? (
              <Box sx={adminStickyActionsSx}>
                <Typography
                  sx={{ m: 0, fontSize: "0.8125rem", fontWeight: 600, color: meridian.textSecondary }}
                >
                  {t("admin.accountRequests.makerCheckerNote")}
                </Typography>
                <Stack direction="row" useFlexGap sx={{ gap: 1.25, flexWrap: "wrap" }}>
                  {decision ? (
                    <Button
                      variant="text"
                      disabled={busy}
                      onClick={() => setDecision(null)}
                      sx={{ textTransform: "none", fontWeight: 600 }}
                    >
                      {t("common.cancel")}
                    </Button>
                  ) : null}
                  <Button
                    variant="outlined"
                    color="error"
                    disabled={busy}
                    onClick={() => {
                      if (decision === "reject") void onReject();
                      else setDecision("reject");
                    }}
                    sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
                  >
                    {decision === "reject" ? t("admin.accountRequests.confirmRejection") : t("common.reject")}
                  </Button>
                  <Button
                    variant="contained"
                    color="primary"
                    disabled={busy}
                    onClick={() => {
                      if (decision === "approve") void onApprove();
                      else setDecision("approve");
                    }}
                    sx={{
                      textTransform: "none",
                      fontWeight: 700,
                      borderRadius: "10px",
                      bgcolor: meridian.brandPrimary,
                      color: "#ffffff",
                      "&:hover": { bgcolor: meridian.brandDeep },
                    }}
                  >
                    {decision === "approve" ? t("admin.accountRequests.confirmApproval") : t("common.approve")}
                  </Button>
                </Stack>
              </Box>
            ) : null}
          </Box>
        )}
      </Box>

      <CreateAccountRequestModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(row) => {
          void refresh();
          setSelectedId(row.id);
          setStatus("pending");
        }}
      />
    </Box>
  );
}
