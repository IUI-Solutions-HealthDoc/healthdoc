"use client";

import { forwardRef, type ReactNode } from "react";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import Paper, { type PaperProps } from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import {
  ResponsiveContainer,
  type ResponsiveContainerProps,
} from "recharts";
import { meridian } from "@/styles/theme";
import { translate } from "@/lib/i18n";

export type ChartEmptyState =
  | boolean
  | {
      title?: string;
      description?: string;
    };

export type ChartWrapperProps = Omit<PaperProps, "children" | "title"> & {
  title?: string;
  description?: string;
  height?: number;
  loading?: boolean;
  empty?: ChartEmptyState;
  actions?: ReactNode;
  children?: ReactNode;
  containerProps?: Omit<ResponsiveContainerProps, "children" | "width" | "height">;
};

function normalizeEmpty(empty: ChartEmptyState | undefined) {
  if (!empty) return null;
  if (empty === true) {
    return {
      title: translate("common.msg.noDataAvailable"),
      description: translate("common.msg.thereIsNothingToDisplayFor"),
    };
  }
  return {
    title: empty.title ?? translate("common.msg.noDataAvailable"),
    description:
      empty.description ?? translate("common.msg.thereIsNothingToDisplayFor"),
  };
}

export const ChartWrapper = forwardRef<HTMLDivElement, ChartWrapperProps>(
  function ChartWrapper(
    {
      title,
      description,
      height = 280,
      loading = false,
      empty,
      actions,
      children,
      containerProps,
      sx,
      className,
      elevation = 0,
      ...paperProps
    },
    ref,
  ) {
    const emptyState = !loading ? normalizeEmpty(empty) : null;
    const showHeader = Boolean(title || description || actions);

    return (
      <Paper
        ref={ref}
        elevation={elevation}
        className={className}
        sx={{
          borderRadius: "16px",
          border: `1px solid ${meridian.border}`,
          background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
          boxShadow:
            "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
          overflow: "hidden",
          ...((sx as object) ?? {}),
        }}
        {...paperProps}
      >
        {showHeader ? (
          <>
            <Box
              sx={{
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                gap: 2,
                px: 3,
                pt: 2.75,
                pb: 2,
              }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                {title ? (
                  <Typography
                    component="h3"
                    sx={{
                      m: 0,
                      fontSize: "1.0625rem",
                      fontWeight: 700,
                      letterSpacing: "-0.02em",
                      color: meridian.textPrimary,
                      lineHeight: 1.3,
                    }}
                  >
                    {title}
                  </Typography>
                ) : null}
                {description ? (
                  <Typography
                    component="p"
                    sx={{
                      m: 0,
                      mt: title ? 0.6 : 0,
                      fontSize: "0.8125rem",
                      color: meridian.textSecondary,
                      lineHeight: 1.5,
                      maxWidth: 520,
                    }}
                  >
                    {description}
                  </Typography>
                ) : null}
              </Box>
              {actions ? (
                <Box
                  sx={{
                    flexShrink: 0,
                    display: "flex",
                    alignItems: "center",
                    gap: 1,
                    pt: 0.25,
                  }}
                >
                  {actions}
                </Box>
              ) : null}
            </Box>
            <Divider sx={{ borderColor: "rgb(0 31 84 / 0.08)" }} />
          </>
        ) : null}

        <Box
          sx={{
            px: 2,
            pb: 2.5,
            pt: showHeader ? 2 : 2.5,
            "& .recharts-cartesian-axis-tick text, & .recharts-text": {
              fill: `${meridian.textSecondary} !important`,
              stroke: "none !important",
              fontSize: "11px !important",
              fontWeight: "500 !important",
              fontFamily:
                'var(--font-ibm-plex-sans), "IBM Plex Sans", system-ui, sans-serif !important',
              paintOrder: "fill",
            },
            "& .recharts-cartesian-grid-horizontal line, & .recharts-cartesian-grid-vertical line":
              {
                stroke: "rgb(0 31 84 / 0.08)",
              },
            "& .recharts-legend-item-text": {
              color: `${meridian.textSecondary} !important`,
              fontSize: 12,
              fontWeight: 500,
            },
            "& .recharts-default-tooltip": {
              border: `1px solid ${meridian.border} !important`,
              borderRadius: "12px !important",
              background: `${meridian.surface} !important`,
              boxShadow: "0 12px 32px rgb(0 31 84 / 0.12) !important",
              padding: "10px 12px !important",
            },
            "& .recharts-tooltip-label": {
              color: `${meridian.textPrimary} !important`,
              fontWeight: 600,
              marginBottom: "4px !important",
            },
          }}
        >
          {loading ? (
            <Box
              role="status"
              aria-live="polite"
              aria-busy="true"
              sx={{
                height,
                display: "grid",
                placeItems: "center",
                color: meridian.textSecondary,
                borderRadius: "12px",
                background: `linear-gradient(180deg, ${meridian.muted} 0%, transparent 100%)`,
              }}
            >
              <CircularProgress size={36} thickness={3.5} />
            </Box>
          ) : emptyState ? (
            <Box
              role="status"
              sx={{
                height,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                textAlign: "center",
                px: 3,
                background: `linear-gradient(180deg, ${meridian.muted} 0%, #eef3f8 100%)`,
                borderRadius: "12px",
                border: `1px dashed rgb(0 31 84 / 0.14)`,
                mx: 0.5,
              }}
            >
              <Typography
                sx={{
                  fontWeight: 700,
                  fontSize: "0.9375rem",
                  color: meridian.textPrimary,
                  mb: 0.5,
                  letterSpacing: "-0.01em",
                }}
              >
                {emptyState.title}
              </Typography>
              <Typography
                sx={{
                  fontSize: "0.8125rem",
                  color: meridian.textSecondary,
                  maxWidth: 320,
                  lineHeight: 1.5,
                }}
              >
                {emptyState.description}
              </Typography>
            </Box>
          ) : (
            <Box sx={{ width: "100%", height }}>
              <ResponsiveContainer width="100%" height="100%" {...containerProps}>
                {children as ResponsiveContainerProps["children"]}
              </ResponsiveContainer>
            </Box>
          )}
        </Box>
      </Paper>
    );
  },
);

ChartWrapper.displayName = "ChartWrapper";
