"use client";

import { useEffect, useState } from "react";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Typography from "@mui/material/Typography";

import { useLocale } from "@/lib/i18n";

import { getReceptionistSummary } from "../api";
import type { ReceptionistSummary } from "../types";

export function ReceptionistTrackerPanel() {
  const { t } = useLocale();
  const [summary, setSummary] = useState<ReceptionistSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getReceptionistSummary();
      setSummary(data);
    } catch {
      setSummary(null);
      setError(t("reports.reception.errLoad"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  return (
    <Card
      variant="outlined"
      sx={{
        borderRadius: 2,
        boxShadow: "0 2px 10px rgba(0,0,0,0.04)",
        borderColor: "divider",
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          px: 3,
          py: 2,
          bgcolor: (t) => (t.palette.mode === "dark" ? "grey.900" : "grey.50"),
          borderBottom: 1,
          borderColor: "divider",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <PeopleAltOutlinedIcon color="primary" />
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {t("reports.reception.title")}
          </Typography>
          <Chip label={t("reports.reception.liveToday")} size="small" color="success" sx={{ height: 20, fontSize: "0.7rem", fontWeight: 700 }} />
        </Box>
        <IconButton size="small" onClick={loadData} disabled={loading}>
          <RefreshIcon fontSize="small" />
        </IconButton>
      </Box>

      <CardContent sx={{ p: 2.5 }}>
        {error && <p role="alert">{error}</p>}
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(5, 1fr)" },
            gap: 2,
          }}
        >
          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "action.hover", textAlign: "center" }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {t("reports.reception.totalRegistered")}
            </Typography>
            <Typography variant="h5" color="text.primary" sx={{ mt: 0.5, fontWeight: 800 }}>
              {summary?.total_registered ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#fff3e0", textAlign: "center", border: "1px solid #ffe0b2" }}>
            <Typography variant="caption" sx={{ color: "#e65100", fontWeight: 600 }}>
              {t("reports.reception.waiting")}
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#e65100", fontWeight: 800 }}>
              {summary?.waiting ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#e3f2fd", textAlign: "center", border: "1px solid #bbdefb" }}>
            <Typography variant="caption" sx={{ color: "#1565c0", fontWeight: 600 }}>
              {t("reports.reception.inConsultation")}
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#1565c0", fontWeight: 800 }}>
              {summary?.in_consultation ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#e8f5e9", textAlign: "center", border: "1px solid #c8e6c9" }}>
            <Typography variant="caption" sx={{ color: "#2e7d32", fontWeight: 600 }}>
              {t("reports.reception.completed")}
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#2e7d32", fontWeight: 800 }}>
              {summary?.completed ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "action.selected", textAlign: "center", border: "1px solid", borderColor: "divider" }}>
            <Typography variant="caption" color="primary" sx={{ fontWeight: 600 }}>
              {t("reports.reception.avgWait")}
            </Typography>
            <Typography variant="h5" color="primary" sx={{ mt: 0.5, fontWeight: 800 }}>
              {summary?.average_wait_minutes != null
                ? `${summary.average_wait_minutes}${t("reports.reception.minSuffix")}`
                : "—"}
            </Typography>
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
}
