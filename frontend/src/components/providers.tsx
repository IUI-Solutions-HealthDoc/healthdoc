"use client";

import { AppRouterCacheProvider } from "@mui/material-nextjs/v15-appRouter";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import GlobalStyles from "@mui/material/GlobalStyles";
import { muiTheme } from "@/styles/theme";
import { Toaster } from "@/components/ui/Toaster";
import { AuthProvider } from "@/providers/auth-provider";
import { CriticalAlertListener } from "@/features/lab/CriticalAlertListener";
import { NumberWheelGuard } from "@/components/common/NumberWheelGuard";

const LAYER_ORDER = "@layer theme, base, mui, components, utilities;";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AppRouterCacheProvider options={{ enableCssLayer: true }}>
      {/* Must be first so Tailwind preflight cannot override MUI (padding/gap). */}
      <GlobalStyles styles={LAYER_ORDER} />
      <ThemeProvider theme={muiTheme}>
        <CssBaseline />
        <AuthProvider>
          <CriticalAlertListener />
          <NumberWheelGuard />
          {children}
          <Toaster />
        </AuthProvider>
      </ThemeProvider>
    </AppRouterCacheProvider>
  );
}
