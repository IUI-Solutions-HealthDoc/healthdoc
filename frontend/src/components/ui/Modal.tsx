import * as React from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import CircularProgress from "@mui/material/CircularProgress";
import { useLocale } from "@/lib/i18n";

// Inline icon so this component has zero extra dependencies
// (repo doesn't currently install @mui/icons-material).
function CloseGlyph() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M18 6L6 18M6 6l12 12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  /** Buttons rendered bottom-right, e.g. [<Button key="cancel">Cancel</Button>, <Button key="save">Save</Button>] */
  actions?: React.ReactNode;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  /** Block backdrop-click / escape-key close, e.g. while a form is submitting */
  disableClose?: boolean;
  /** Shows a spinner in place of actions — use while an async save/submit is in flight */
  loading?: boolean;
}

/**
 * Shared modal for confirmations, forms, and detail views
 * (e.g. "Create Lab Order", "Add Diagnosis", "Confirm Cancel Order").
 *
 * Accessibility: MUI Dialog already handles focus trap, escape-to-close,
 * and aria-labelledby — don't re-implement these at the call site.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  actions,
  size = "sm",
  disableClose = false,
  loading = false,
}: ModalProps) {
  const { t } = useLocale();
  const handleClose = () => {
    if (disableClose || loading) return;
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth={size}
      fullWidth
      aria-labelledby="shared-modal-title"
    >
      <DialogTitle
        id="shared-modal-title"
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        {title}
        <IconButton
          aria-label={t("lab.critical.closeDialog")}
          onClick={onClose}
          disabled={disableClose || loading}
          size="small"
        >
          <CloseGlyph />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>{children}</DialogContent>

      {(actions || loading) && (
        <DialogActions sx={{ px: 3, py: 2 }}>
          {loading ? (
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", pr: 1 }}>
              <CircularProgress size={18} />
            </Stack>
          ) : (
            actions
          )}
        </DialogActions>
      )}
    </Dialog>
  );
}
