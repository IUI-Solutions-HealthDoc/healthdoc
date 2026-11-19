import * as React from "react";
import Chip, { ChipProps } from "@mui/material/Chip";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

type StatusTone = {
  bg: string;
  fg: string;
  border: string;
  label?: string;
};

/**
 * Shared status tones. Queue tokens use QueueTokenStatus
 * (waiting|called|in_service|skipped|no_show|recalled|transferred|completed|cancelled).
 * Billing / audit / consent keys are also mapped for cross-module reuse.
 */
const STATUS_TONE_MAP: Record<string, StatusTone> = {
  waiting: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
  },
  called: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("common.msg.called"); },
  },
  in_service: {
    bg: "#e8eef5",
    fg: meridian.brandPrimary,
    border: "rgb(0 31 84 / 0.18)",
    get label() { return translate("doctor.queueInService"); },
  },
  skipped: {
    bg: "#fef3c7",
    fg: meridian.warning,
    border: "rgb(180 83 9 / 0.2)",
    get label() { return translate("ipd.checklist.statusSkipped"); },
  },
  no_show: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    get label() { return translate("appointment.status.no_show"); },
  },
  transferred: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("nurse.msg.transferred"); },
  },
  completed: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
  },
  cancelled: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
  },
  draft: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
    get label() { return translate("billing.invoiceStatus.draft"); },
  },
  issued: {
    bg: "#e8eef5",
    fg: meridian.brandPrimary,
    border: "rgb(0 31 84 / 0.18)",
    get label() { return translate("billing.invoiceStatus.issued"); },
  },
  partially_paid: {
    bg: "#fef3c7",
    fg: meridian.warning,
    border: "rgb(180 83 9 / 0.2)",
    get label() { return translate("billing.invoiceStatus.partially_paid"); },
  },
  paid: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("billing.invoiceStatus.paid"); },
  },
  waived: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("billing.invoiceStatus.waived"); },
  },
  recalled: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
  },
  // Audit / consent / verification (B7 viewers)
  verified: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("consent.verified"); },
  },
  failed: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    get label() { return translate("bloodBank.screening.failed"); },
  },
  pending: {
    bg: "#fef3c7",
    fg: meridian.warning,
    border: "rgb(180 83 9 / 0.2)",
    get label() { return translate("doctor.soapStatusPending"); },
  },
  requested: {
    bg: "#fef3c7",
    fg: meridian.warning,
    border: "rgb(180 83 9 / 0.2)",
    get label() { return translate("consent.status.requested"); },
  },
  granted: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("consent.status.granted"); },
  },
  denied: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    get label() { return translate("consent.status.denied"); },
  },
  active: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("monitor.activeToday"); },
  },
  expired: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
    get label() { return translate("receptionist.scanShare.statusExpired"); },
  },
  revoked: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    get label() { return translate("consent.status.revoked"); },
  },
  create: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("audit.msg.create"); },
  },
  update: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("audit.msg.update"); },
  },
  merge: {
    bg: "#fef3c7",
    fg: meridian.warning,
    border: "rgb(180 83 9 / 0.2)",
    get label() { return translate("common.msg.merge"); },
  },
  login: {
    bg: "#e8eef5",
    fg: meridian.brandPrimary,
    border: "rgb(0 31 84 / 0.18)",
    get label() { return translate("audit.msg.login"); },
  },
  logout: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
    get label() { return translate("audit.msg.logout"); },
  },
  view: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("audit.msg.view"); },
  },
  export: {
    bg: "#e8eef5",
    fg: meridian.brandPrimary,
    border: "rgb(0 31 84 / 0.18)",
    get label() { return translate("consent.access.export"); },
  },
  download: {
    bg: "#e8eef5",
    fg: meridian.info,
    border: "rgb(0 31 84 / 0.14)",
    get label() { return translate("forms.ui.download"); },
  },
  upload: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("audit.msg.upload"); },
  },
  delete_attempt: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    get label() { return translate("audit.msg.deleteAttempt"); },
  },
  emergency: {
    bg: "#fee2e2",
    fg: meridian.danger,
    border: "rgb(185 28 28 / 0.18)",
    label: "Break-glass",
  },
  success: {
    bg: "#dcfce7",
    fg: meridian.success,
    border: "rgb(22 101 52 / 0.18)",
    get label() { return translate("billing.paymentStatus.success"); },
  },
  reversed: {
    bg: meridian.muted,
    fg: meridian.textSecondary,
    border: meridian.border,
    get label() { return translate("billing.paymentStatus.reversed"); },
  },
};

const FALLBACK_TONE: StatusTone = {
  bg: meridian.muted,
  fg: meridian.textSecondary,
  border: meridian.border,
};

export interface StatusChipProps extends Omit<ChipProps, "color" | "label"> {
  /** e.g. "in_service", "skipped" — snake_case status key from the API */
  status: string;
  /** Override the auto-generated label if the API sends a different display string */
  label?: string;
}

function toTitleCase(key: string) {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function StatusChip({
  status,
  label,
  size = "small",
  sx,
  ...props
}: StatusChipProps) {
  const normalized = status?.toLowerCase().replace(/\s+/g, "_") ?? "";
  const tone = STATUS_TONE_MAP[normalized] ?? FALLBACK_TONE;

  return (
    <Chip
      size={size}
      label={label ?? tone.label ?? toTitleCase(normalized || "unknown")}
      sx={{
        height: size === "small" ? 24 : 28,
        borderRadius: "999px",
        fontWeight: 600,
        fontSize: size === "small" ? "0.6875rem" : "0.75rem",
        letterSpacing: "0.01em",
        backgroundColor: tone.bg,
        color: tone.fg,
        border: `1px solid ${tone.border}`,
        "& .MuiChip-label": {
          px: 1.25,
        },
        ...((sx as object) ?? {}),
      }}
      {...props}
    />
  );
}
