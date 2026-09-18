"use client";

import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";

import { ConsultationWorkspace } from "@/features/doctor";
import { getPatient, getQueueToken } from "@/features/doctor/api";
import { doctorPageSx } from "@/features/doctor/panelSx";
import type { EncounterContext } from "@/features/doctor/types";
import { api } from "@/lib/api";
import { useAuth } from "@/providers/auth-provider";

interface VisitRecord {
  id: string;
  visit_number: string;
  patient_id: string;
  facility_id: string;
  visit_type: string;
  status: string;
  visit_date: string;
}

/**
 * The queue token or visit_id is read from the URL in an effect rather than with
 * `useSearchParams`.
 *
 * `useSearchParams` suspends during prerender, and the Suspense boundary it
 * requires was leaving this route's subtree unhydrated. Reading `window.location`
 * after mount keeps the whole page a normal client tree.
 */
export default function Page() {
  const { user } = useAuth();
  const [context, setContext] = useState<EncounterContext | null>(null);
  const [message, setMessage] = useState<{ tone: "instruction" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.search);
    const tokenId = params.get("token");
    const visitId = params.get("visit_id");

    if (!tokenId && !visitId) {
      setMessage({
        tone: "instruction",
        text: "Open a patient from the live OPD queue or Emergency arrivals to start a consultation.",
      });
      setContext(null);
      return;
    }

    void (async () => {
      try {
        if (tokenId) {
          const token = await getQueueToken(tokenId);
          if (cancelled) return;
          if (!token) {
            setMessage({ tone: "error", text: "Queue token not found." });
            setContext(null);
            return;
          }
          setMessage(null);
          setContext({
            visit_id: token.visit_id,
            patient_id: token.patient_id,
            patient_name: token.full_name,
            uhid: token.uhid,
            age_years: token.age_years,
            sex: token.sex,
            provider_user_id: token.provider_user_id || user?.id || "",
            provider_name: token.provider_name || user?.name || "Assigned doctor",
            department: token.department ?? "OPD",
            token_display: token.token_display,
          });
        } else if (visitId) {
          const visit = await api<VisitRecord>(`/visits/${visitId}`);
          if (cancelled) return;
          if (!visit) {
            setMessage({ tone: "error", text: "Visit not found." });
            setContext(null);
            return;
          }
          const patient = await getPatient(visit.patient_id);
          if (cancelled) return;
          if (!patient) {
            setMessage({ tone: "error", text: "Patient record not found for this visit." });
            setContext(null);
            return;
          }
          const isEmergency = visit.visit_type === "emergency";
          const isIpd = visit.visit_type === "ipd";
          setMessage(null);
          setContext({
            visit_id: visit.id,
            patient_id: patient.id,
            patient_name: patient.full_name,
            uhid: patient.uhid || patient.thid || "No identifier",
            age_years: patient.age_years ?? 0,
            sex: patient.sex || "unknown",
            provider_user_id: user?.id || "",
            provider_name: user?.name || "Attending Doctor",
            department: isEmergency ? "Emergency" : isIpd ? "Inpatient" : "OPD",
            token_display: isEmergency ? `EMERGENCY · ${visit.visit_number}` : visit.visit_number,
          });
        }
      } catch (e) {
        if (cancelled) return;
        setMessage({
          tone: "error",
          text: e instanceof Error ? e.message : "Failed to load encounter context",
        });
        setContext(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user]);

  return (
    <Box sx={doctorPageSx}>
      {message ? (
        <Box
          role={message.tone === "error" ? "alert" : undefined}
          sx={{
            border: "1px solid",
            borderColor: message.tone === "error" ? "error.light" : "divider",
            borderRadius: 2,
            bgcolor: message.tone === "error" ? "rgba(211, 47, 47, 0.08)" : "background.paper",
            p: 3,
          }}
        >
          <Typography component="h1" sx={{ fontSize: "1.25rem", fontWeight: 700 }}>
            {message.tone === "error" ? "Consultation unavailable" : "Start a consultation"}
          </Typography>
          <Typography sx={{ mt: 1, color: "text.secondary" }}>{message.text}</Typography>
        </Box>
      ) : !context ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <ConsultationWorkspace context={context} />
      )}
    </Box>
  );
}
