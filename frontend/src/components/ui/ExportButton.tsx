"use client";

import {
  forwardRef,
  useId,
  useState,
  type MouseEvent,
} from "react";
import Tooltip from "@mui/material/Tooltip";
import Button, { type ButtonProps } from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import DownloadIcon from "@mui/icons-material/Download";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import TableChartOutlinedIcon from "@mui/icons-material/TableChartOutlined";
import GridOnOutlinedIcon from "@mui/icons-material/GridOnOutlined";
import PictureAsPdfOutlinedIcon from "@mui/icons-material/PictureAsPdfOutlined";
import { meridian } from "@/styles/theme";

export type ExportFormat = "csv" | "xlsx" | "pdf";

/**
 * UI shell only: opens a format menu and calls onExport.
 * Does not generate files, call /export, or write data_access_log —
 * parents own audited export endpoints (access_channel='export').
 */
export type ExportButtonProps = Omit<
  ButtonProps,
  "onClick" | "children" | "endIcon" | "startIcon"
> & {
  onExport: (format: ExportFormat) => void | Promise<void>;
  formats?: ExportFormat[];
  label?: string;
  loading?: boolean;
  /** Said on hover and to screen readers while disabled: a dead button with
   *  no reason left the supervisor guessing (QA 12 Oct 2026). */
  disabledReason?: string;
};

const FORMAT_META: Record<
  ExportFormat,
  { label: string; hint: string; icon: typeof TableChartOutlinedIcon }
> = {
  csv: {
    label: "CSV",
    hint: "Spreadsheet-ready rows",
    icon: TableChartOutlinedIcon,
  },
  xlsx: {
    label: "Excel",
    hint: "Workbook (.xlsx)",
    icon: GridOnOutlinedIcon,
  },
  pdf: {
    label: "PDF",
    hint: "Printable report",
    icon: PictureAsPdfOutlinedIcon,
  },
};

const DEFAULT_FORMATS: ExportFormat[] = ["csv", "xlsx", "pdf"];

export const ExportButton = forwardRef<HTMLButtonElement, ExportButtonProps>(
  function ExportButton(
    {
      onExport,
      formats = DEFAULT_FORMATS,
      label = "Export",
      loading: loadingProp = false,
      variant = "outlined",
      size = "medium",
      disabled = false,
      disabledReason,
      sx,
      ...buttonProps
    },
    ref,
  ) {
    const menuId = useId();
    const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
    const [pending, setPending] = useState(false);
    const open = Boolean(anchorEl);
    const busy = loadingProp || pending;
    const availableFormats = formats.length > 0 ? formats : DEFAULT_FORMATS;

    const handleOpen = (event: MouseEvent<HTMLButtonElement>) => {
      setAnchorEl(event.currentTarget);
    };

    const handleClose = () => {
      setAnchorEl(null);
    };

    const handleSelect = async (format: ExportFormat) => {
      handleClose();
      try {
        setPending(true);
        await onExport(format);
      } finally {
        setPending(false);
      }
    };

    return (
      <>
        {disabled && disabledReason ? (
          <Tooltip title={disabledReason}>
            <span aria-label={disabledReason} style={{ display: "inline-flex" }}>
        <Button
          ref={ref}
          variant={variant}
          size={size}
          disabled={disabled || busy}
          aria-haspopup="menu"
          aria-expanded={open ? "true" : undefined}
          aria-controls={open ? menuId : undefined}
          onClick={handleOpen}
          startIcon={
            busy ? (
              <CircularProgress color="inherit" size={15} thickness={5} />
            ) : (
              <DownloadIcon sx={{ fontSize: 18 }} />
            )
          }
          endIcon={
            <KeyboardArrowDownIcon
              sx={{
                fontSize: 20,
                transition: "transform 0.2s ease",
                transform: open ? "rotate(180deg)" : "none",
              }}
            />
          }
          sx={{
            textTransform: "none",
            fontWeight: 600,
            letterSpacing: "0.01em",
            borderRadius: "10px",
            px: 1.75,
            borderColor: "rgb(0 31 84 / 0.18)",
            color: meridian.brandPrimary,
            backgroundColor: meridian.surface,
            boxShadow: "0 1px 2px rgb(0 31 84 / 0.04)",
            "&:hover": {
              borderColor: meridian.brandPrimary,
              backgroundColor: meridian.muted,
              boxShadow: "0 4px 12px rgb(0 31 84 / 0.08)",
            },
            ...((sx as object) ?? {}),
          }}
          {...buttonProps}
        >
          {label}
        </Button>
            </span>
          </Tooltip>
        ) : (
        <Button
          ref={ref}
          variant={variant}
          size={size}
          disabled={disabled || busy}
          aria-haspopup="menu"
          aria-expanded={open ? "true" : undefined}
          aria-controls={open ? menuId : undefined}
          onClick={handleOpen}
          startIcon={
            busy ? (
              <CircularProgress color="inherit" size={15} thickness={5} />
            ) : (
              <DownloadIcon sx={{ fontSize: 18 }} />
            )
          }
          endIcon={
            <KeyboardArrowDownIcon
              sx={{
                fontSize: 20,
                transition: "transform 0.2s ease",
                transform: open ? "rotate(180deg)" : "none",
              }}
            />
          }
          sx={{
            textTransform: "none",
            fontWeight: 600,
            letterSpacing: "0.01em",
            borderRadius: "10px",
            px: 1.75,
            borderColor: "rgb(0 31 84 / 0.18)",
            color: meridian.brandPrimary,
            backgroundColor: meridian.surface,
            boxShadow: "0 1px 2px rgb(0 31 84 / 0.04)",
            "&:hover": {
              borderColor: meridian.brandPrimary,
              backgroundColor: meridian.muted,
              boxShadow: "0 4px 12px rgb(0 31 84 / 0.08)",
            },
            ...((sx as object) ?? {}),
          }}
          {...buttonProps}
        >
          {label}
        </Button>
        )}

        <Menu
          id={menuId}
          anchorEl={anchorEl}
          open={open}
          onClose={handleClose}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          transitionDuration={160}
          slotProps={{
            paper: {
              sx: {
                mt: 1,
                minWidth: 220,
                borderRadius: "12px",
                border: `1px solid ${meridian.border}`,
                boxShadow: "0 16px 40px rgb(0 31 84 / 0.14)",
                overflow: "hidden",
                backgroundImage: "none",
              },
            },
            list: {
              "aria-label": `${label} formats`,
              dense: false,
              sx: { py: 0.75 },
            },
          }}
        >
          {availableFormats.map((format) => {
            const meta = FORMAT_META[format];
            const Icon = meta.icon;
            return (
              <MenuItem
                key={format}
                onClick={() => {
                  void handleSelect(format);
                }}
                disabled={busy}
                sx={{
                  mx: 0.75,
                  my: 0.25,
                  borderRadius: "8px",
                  py: 1.1,
                  gap: 0.5,
                  "&:hover": {
                    backgroundColor: meridian.muted,
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: meridian.brandPrimary }}>
                  <Icon fontSize="small" />
                </ListItemIcon>
                <ListItemText
                  primary={meta.label}
                  secondary={meta.hint}
                  slotProps={{
                    primary: {
                      sx: {
                        fontWeight: 600,
                        fontSize: "0.875rem",
                        color: meridian.textPrimary,
                      },
                    },
                    secondary: {
                      sx: {
                        fontSize: "0.75rem",
                        color: meridian.textSecondary,
                      },
                    },
                  }}
                />
              </MenuItem>
            );
          })}
        </Menu>
      </>
    );
  },
);

ExportButton.displayName = "ExportButton";
