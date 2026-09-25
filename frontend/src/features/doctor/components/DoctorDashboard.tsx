"use client";

import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Link from "next/link";

import { listEmergencyWorklist, type EmergencyWorklistItem } from "@/features/emergency/api";
import { meridian } from "@/styles/theme";
import { useLocale } from "@/lib/i18n";
import { doctorPageHeaderSx } from "../panelSx";
import { useDoctorQueue } from "../hooks/useDoctorQueue";
import { BreakGlassGate } from "./BreakGlassGate";
import { DoctorQueuePanel } from "./DoctorQueuePanel";
import { PatientSummarySidebar } from "./PatientSummarySidebar";

/**
 * Week 2 — doctor dashboard. Queue worklist + patient summary side-by-side
 * (fixed desktop two-column layout — no responsive breakpoints by design).
 */
export function DoctorDashboard() {
  const { t } = useLocale();
  const { patients, loading, error, selected, select } = useDoctorQueue();
  const [emergencyArrivals, setEmergencyArrivals] = useState<EmergencyWorklistItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    listEmergencyWorklist()
      .then((rows) => {
        if (!cancelled) setEmergencyArrivals(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Prefer in_service, else waiting/called/recalled, else first row.
  useEffect(() => {
    if (loading || selected || patients.length === 0) return;
    const preferred =
      patients.find((p) => p.status === "in_service") ??
      patients.find(
        (p) => p.status === "waiting" || p.status === "called" || p.status === "recalled",
      ) ??
      patients[0];
    select(preferred);
  }, [loading, patients, selected, select]);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <Box sx={doctorPageHeaderSx}>
        <Typography
          sx={{
            m: 0,
            mb: 0.5,
            fontSize: "0.6875rem",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: meridian.textSecondary,
          }}
        >
          OPD & Emergency · Doctor
        </Typography>
        <Typography
          component="h1"
          sx={{
            m: 0,
            fontSize: { xs: "1.375rem", md: "1.5rem" },
            fontWeight: 700,
            letterSpacing: "-0.03em",
            color: meridian.textPrimary,
            lineHeight: 1.2,
          }}
        >
          {t("doctor.dashboardTitle")}
        </Typography>
        <Typography
          sx={{
            m: 0,
            mt: 0.6,
            fontSize: "0.875rem",
            color: meridian.textSecondary,
            maxWidth: 560,
            lineHeight: 1.45,
          }}
        >
          {t("doctor.dashboardSubtitle")}
        </Typography>
      </Box>

      {emergencyArrivals.length > 0 && (
        <Box
          sx={{
            p: 2,
            borderRadius: "12px",
            bgcolor: "rgba(211, 47, 47, 0.08)",
            border: "1px solid",
            borderColor: "error.light",
          }}
        >
          <Typography sx={{ fontWeight: 700, fontSize: "0.9375rem", color: "error.main", mb: 1 }}>
            Emergency Arrivals Awaiting Care ({emergencyArrivals.length})
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5 }}>
            {emergencyArrivals.map((arr) => (
              <Box
                key={arr.visit_id}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 1.5,
                  p: 1.25,
                  bgcolor: "background.paper",
                  borderRadius: "8px",
                  border: "1px solid",
                  borderColor: "divider",
                }}
              >
                <Box>
                  <Typography sx={{ fontWeight: 600, fontSize: "0.8125rem" }}>
                    {arr.full_name} · {arr.thid ?? arr.uhid}
                  </Typography>
                  <Typography sx={{ fontSize: "0.6875rem", color: "text.secondary" }}>
                    {arr.age_years ?? "?"}y/{arr.sex[0]?.toUpperCase()} · Visit {arr.visit_number}
                  </Typography>
                </Box>
                <Button
                  component={Link}
                  href={`/doctor/consultation?visit_id=${arr.visit_id}`}
                  variant="contained"
                  color="error"
                  size="small"
                  sx={{ textTransform: "none", fontSize: "0.75rem", px: 1.5, py: 0.5 }}
                >
                  Consult
                </Button>
              </Box>
            ))}
          </Box>
        </Box>
      )}

      {error ? (
        <Alert severity="error" sx={{ borderRadius: "12px" }}>
          {error}
        </Alert>
      ) : null}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 340px",
          gap: 3,
          alignItems: "start",
        }}
      >
        <DoctorQueuePanel
          patients={patients}
          loading={loading}
          selectedId={selected?.id ?? null}
          onSelect={select}
        />
        <Box sx={{ position: "sticky", top: 24 }}>
          <BreakGlassGate patient={selected}>
            <PatientSummarySidebar token={selected} />
          </BreakGlassGate>
        </Box>
      </Box>
    </Box>
  );
}
