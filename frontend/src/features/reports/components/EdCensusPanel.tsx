"use client";

import { useEffect, useState } from "react";
import EmergencyOutlinedIcon from "@mui/icons-material/EmergencyOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Typography from "@mui/material/Typography";

import { getEdCensus } from "../api";
import type { EdCensus } from "../types";

export function EdCensusPanel() {
  const [census, setCensus] = useState<EdCensus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getEdCensus();
      setCensus(data);
    } catch {
      setCensus(null);
      setError("Emergency data could not be loaded. Retry to see current figures.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const acuity = census?.triage_acuity_distribution ?? {};

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
          <EmergencyOutlinedIcon color="error" />
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            Emergency Department (ED) Live Census & Acuity
          </Typography>
          <Chip label="24/7 ACTIVE" size="small" color="error" sx={{ height: 20, fontSize: "0.7rem", fontWeight: 700 }} />
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
            gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(4, 1fr)" },
            gap: 2,
          }}
        >
          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "action.hover", textAlign: "center" }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              EMERGENCY TODAY
            </Typography>
            <Typography variant="h5" color="text.primary" sx={{ mt: 0.5, fontWeight: 800 }}>
              {census?.total_emergency_today ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#ffebee", textAlign: "center", border: "1px solid #ffcdd2" }}>
            <Typography variant="caption" sx={{ color: "#c62828", fontWeight: 600 }}>
              ACTIVE ED PATIENTS
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#c62828", fontWeight: 800 }}>
              {census?.active_patients ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#e3f2fd", textAlign: "center", border: "1px solid #bbdefb" }}>
            <Typography variant="caption" sx={{ color: "#1565c0", fontWeight: 600 }}>
              ADMITTED TO IPD
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#1565c0", fontWeight: 800 }}>
              {census?.admitted_to_ipd ?? "—"}
            </Typography>
          </Box>

          <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#e8f5e9", textAlign: "center", border: "1px solid #c8e6c9" }}>
            <Typography variant="caption" sx={{ color: "#2e7d32", fontWeight: 600 }}>
              LEFT WITHOUT BEING SEEN
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.5, color: "#2e7d32", fontWeight: 800 }}>
              {census?.lwbs_count ?? "—"}
            </Typography>
          </Box>
        </Box>

        {/* Triage Acuity Breakdown */}
        <Box sx={{ mt: 3, pt: 2, borderTop: 1, borderColor: "divider" }}>
          <Typography variant="caption" sx={{ fontWeight: 700, letterSpacing: 0.5 }} color="text.secondary">
            RECORDED TRIAGE ACUITY DISTRIBUTION
          </Typography>
          <Box sx={{ display: "flex", gap: 2 }}>
            {Object.entries(acuity).map(([level, count]) => <Box key={level}><Typography>{level.replaceAll("_", " ")}</Typography><Typography>{count}</Typography></Box>)}
            {Object.keys(acuity).length === 0 && <Typography>No recorded acuity data available.</Typography>}
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
}
