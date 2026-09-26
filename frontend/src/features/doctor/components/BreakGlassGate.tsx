"use client";

import * as React from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { Button } from "@/components/ui/Button";
import { useLocale } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { meridian } from "@/styles/theme";
import { useBreakGlass } from "../hooks/useBreakGlass";
import { doctorButtonSx, doctorPanelSx } from "../panelSx";
import type { QueueToken, RecordAccessBlockedReason } from "../types";
import { BreakGlassBanner } from "./BreakGlassBanner";
import { BreakGlassWarningModal } from "./BreakGlassWarningModal";

const BLOCKED_KEYS: Record<RecordAccessBlockedReason, MessageKey> = {
  consent_absent: "doctor.breakGlassConsentAbsent",
  consent_expired: "doctor.breakGlassConsentExpired",
  consent_revoked: "doctor.breakGlassConsentRevoked",
};

/**
 * Break-glass is an interception, not a destination: the clinician opens a
 * record and is stopped here. Wrap whatever reads the record; children render
 * only once access is allowed, by consent or by an open grant.
 */
type Props = {
  patient: QueueToken | null;
  children: React.ReactNode;
};

export function BreakGlassGate(props: Props) {
  // Consent, emergency grants and the confirmation dialog belong to one
  // patient. A late access result must never unlock a different patient's
  // children, even temporarily while that patient's own check is pending.
  return <PatientRecordGate key={props.patient?.patient_id ?? "none"} {...props} />;
}

function PatientRecordGate({ patient, children }: Props) {
  const { t } = useLocale();
  const {
    loading,
    submitting,
    allowed,
    blockedReason,
    grant,
    msRemaining,
    mfaVerified,
    stepUpError,
    beginStepUp,
    requestAccess,
    revoke,
  } = useBreakGlass(patient?.patient_id ?? null);
  const [modalOpen, setModalOpen] = React.useState(false);

  // Nothing selected — the child owns its own empty state.
  if (!patient) return <>{children}</>;

  if (loading) {
    return (
      <Box sx={{ ...doctorPanelSx, display: "flex", justifyContent: "center", py: 4 }}>
        <CircularProgress size={22} />
      </Box>
    );
  }

  if (allowed) {
    return (
      <Stack spacing={2}>
        {grant && (
          <BreakGlassBanner
            grant={grant}
            msRemaining={msRemaining}
            busy={submitting}
            onRevoke={revoke}
          />
        )}
        {children}
      </Stack>
    );
  }

  return (
    <>
      <Box sx={{ ...doctorPanelSx, display: "flex", flexDirection: "column", gap: 1.5 }}>
        <Typography sx={{ fontSize: "1.0625rem", fontWeight: 700 }}>{t("doctor.breakGlassRecordLocked")}</Typography>
        <Typography sx={{ fontSize: "0.875rem", color: meridian.textSecondary, lineHeight: 1.55 }}>
          {blockedReason ? t(BLOCKED_KEYS[blockedReason]) : t("doctor.breakGlassCannotView")}
        </Typography>
        <Typography sx={{ fontSize: "0.8125rem", color: meridian.textSecondary, lineHeight: 1.55 }}>
          {t("doctor.breakGlassEmergencyHint")}
        </Typography>
        {stepUpError ? <Alert severity="error">{stepUpError}</Alert> : null}
        <Box>
          <Button
            variant="contained"
            color="error"
            sx={doctorButtonSx}
            loading={submitting}
            onClick={() => {
              if (mfaVerified) setModalOpen(true);
              else void beginStepUp();
            }}
          >
            {mfaVerified ? t("doctor.breakGlassEmergencyAccess") : t("doctor.breakGlassVerifyKeycloak")}
          </Button>
        </Box>
      </Box>

      <BreakGlassWarningModal
        open={modalOpen}
        busy={submitting}
        patientName={patient.full_name}
        onClose={() => setModalOpen(false)}
        onConfirm={requestAccess}
      />
    </>
  );
}
