import { createTheme } from "@mui/material/styles";
import { meridian } from "./meridian";

export const muiTheme = createTheme({
  modularCssLayers: true,
  palette: {
    mode: "light",
    primary: {
      main: meridian.brandPrimary,
      dark: meridian.brandDeep,
      contrastText: "#ffffff",
    },
    secondary: {
      main: meridian.textSecondary,
      contrastText: "#ffffff",
    },
    success: {
      main: meridian.success,
      contrastText: "#ffffff",
    },
    warning: {
      main: meridian.warning,
      contrastText: "#ffffff",
    },
    error: {
      main: meridian.danger,
      contrastText: "#ffffff",
    },
    info: {
      main: meridian.info,
      contrastText: "#ffffff",
    },
    text: {
      primary: meridian.textPrimary,
      secondary: meridian.textSecondary,
      disabled: meridian.textMuted,
    },
    background: {
      default: meridian.canvas,
      paper: meridian.surface,
    },
    divider: meridian.border,
  },
  typography: {
    fontFamily: 'var(--font-ibm-plex-sans), "IBM Plex Sans", system-ui, sans-serif',
    button: {
      textTransform: "none",
      fontWeight: 600,
    },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          boxShadow: "none",
          "&:hover": {
            boxShadow: "none",
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        root: {
          flexShrink: 0,
        },
        paper: {
          backgroundColor: meridian.surface,
          borderColor: meridian.border,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: meridian.surface,
          color: meridian.textPrimary,
          boxShadow: "0 1px 3px 0 rgb(0 31 84 / 0.06)",
          borderBottom: `1px solid ${meridian.border}`,
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
  },
});
