"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { toast } from "@/components/ui/toast";
import { newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { draftFingerprint } from "@/lib/resilience.mjs";
import { useUnsavedChanges } from "@/lib/useUnsavedChanges";
import {
  completeEncounter,
  createEncounter,
  getEncounterForVisit,
  updateEncounter,
} from "../api";
import { StaleWriteError } from "../types";
import type {
  ActiveEncounter,
  EncounterContext,
  EncounterType,
  NoteStatus,
  UpdateEncounterInput,
} from "../types";
import type { SoapNote } from "../components/SoapNotePanel";

export type ConsultationStatus = "draft" | "saved" | "completed";

/** Owns the one persisted encounter for this visit and restores it on reload. */
export function useConsultation(context: EncounterContext) {
  const { t } = useLocale();
  const [encounter, setEncounter] = useState<ActiveEncounter | null>(null);
  const [startedAt] = useState(() => new Date().toISOString());
  const [createKey] = useState(() => newIdempotencyKey());
  const [loading, setLoading] = useState(true);
  const [encounterType, setEncounterType] = useState<EncounterType>("consultation");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [status, setStatus] = useState<ConsultationStatus>("draft");
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [soap, setSoap] = useState<SoapNote>({
    subjective: "",
    objective: "",
    assessment: "",
    plan: "",
  });
  const [noteStatus, setNoteStatus] = useState<NoteStatus>("pending");
  const [conflict, setConflict] = useState<UpdateEncounterInput | null>(null);
  const [lastSavedFingerprint, setLastSavedFingerprint] = useState<string | null>(null);
  const [autoSaveStatus, setAutoSaveStatus] = useState<"idle" | "pending" | "saving" | "saved" | "failed">("idle");
  const hydrated = useRef(false);

  const fingerprint = useMemo(
    () => draftFingerprint({ encounterType, chiefComplaint, soap }),
    [chiefComplaint, encounterType, soap],
  );
  const dirty = hydrated.current && fingerprint !== lastSavedFingerprint && status !== "completed";
  useUnsavedChanges(dirty || saving);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void getEncounterForVisit(context.visit_id, context.patient_id)
      .then((existing) => {
        if (cancelled) return;
        if (!existing) {
          setLastSavedFingerprint(
            draftFingerprint({
              encounterType: "consultation",
              chiefComplaint: "",
              soap: { subjective: "", objective: "", assessment: "", plan: "" },
            }),
          );
          return;
        }
        setEncounter(existing);
        setEncounterType(existing.encounter_type ?? "consultation");
        setChiefComplaint(existing.chief_complaint ?? "");
        setSoap({
          subjective: existing.subjective ?? "",
          objective: existing.objective ?? "",
          assessment: existing.assessment ?? "",
          plan: existing.plan ?? "",
        });
        setNoteStatus(existing.note_status);
        setStatus(existing.ended_at ? "completed" : "saved");
        setLastSavedFingerprint(
          draftFingerprint({
            encounterType: existing.encounter_type ?? "consultation",
            chiefComplaint: existing.chief_complaint ?? "",
            soap: {
              subjective: existing.subjective ?? "",
              objective: existing.objective ?? "",
              assessment: existing.assessment ?? "",
              plan: existing.plan ?? "",
            },
          }),
        );
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          toast.error(
            error instanceof Error ? error.message : t("doctor.toast.restoreConsultationFailed"),
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          hydrated.current = true;
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [context.patient_id, context.visit_id, t]);

  const patchSoap = useCallback(
    (patch: Partial<SoapNote>) => setSoap((previous) => ({ ...previous, ...patch })),
    [],
  );

  const canComplete = useMemo(
    () => status === "saved" && encounter !== null,
    [encounter, status],
  );
  const canWriteChildren = status === "saved" && encounter !== null;

  const saveEncounter = useCallback(async (quiet = false) => {
    if (chiefComplaint.trim() === "") {
      if (!quiet) toast.error(t("doctor.toast.chiefComplaintRequired"));
      return false;
    }
    setSaving(true);
    if (quiet) setAutoSaveStatus("saving");
    try {
      let current = encounter;
      if (!current) {
        current = await createEncounter(
          {
            visit_id: context.visit_id,
            provider_user_id: context.provider_user_id,
            encounter_type: encounterType,
            chief_complaint: chiefComplaint.trim(),
            started_at: startedAt,
          },
          context.patient_id,
          createKey,
        );
        // Preserve the real id even if the following SOAP PATCH fails. A retry
        // must update this row, never POST a duplicate encounter.
        setEncounter(current);
      }

      const saved = await updateEncounter(current, {
        ...soap,
        encounter_type: encounterType,
        chief_complaint: chiefComplaint.trim(),
        note_status: "stored",
      });
      setEncounter(saved);
      setConflict(null);
      setNoteStatus(saved.note_status);
      setStatus("saved");
      setLastSavedFingerprint(fingerprint);
      setAutoSaveStatus("saved");
      if (!quiet) toast.success(t("doctor.toast.encounterSaved"));
      return true;
    } catch (error) {
      if (error instanceof StaleWriteError) {
        setConflict(error.serverCopy);
        setNoteStatus("failed");
        toast.error(t("doctor.toast.staleEncounterConflict"));
        setAutoSaveStatus("failed");
        return false;
      }
      setAutoSaveStatus("failed");
      if (!quiet) toast.error(error instanceof Error ? error.message : t("doctor.toast.saveEncounterFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  }, [
    chiefComplaint,
    context.patient_id,
    context.provider_user_id,
    context.visit_id,
    createKey,
    encounter,
    encounterType,
    fingerprint,
    soap,
    startedAt,
    t,
  ]);

  useEffect(() => {
    if (!dirty || loading || saving || completing || conflict || chiefComplaint.trim() === "") {
      return;
    }
    setAutoSaveStatus("pending");
    const timer = window.setTimeout(() => {
      void saveEncounter(true);
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [chiefComplaint, completing, conflict, dirty, loading, saveEncounter, saving]);

  const complete = useCallback(async () => {
    if (!encounter) return;
    setCompleting(true);
    try {
      const completed = await completeEncounter(encounter, new Date().toISOString());
      setEncounter(completed);
      setStatus("completed");
      toast.success(t("doctor.toast.consultationCompleted"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("doctor.toast.completeConsultationFailed"));
    } finally {
      setCompleting(false);
    }
  }, [encounter, t]);

  return {
    encounter,
    startedAt: encounter?.started_at ?? startedAt,
    loading,
    encounterType,
    setEncounterType,
    chiefComplaint,
    setChiefComplaint,
    status,
    saving,
    completing,
    canComplete,
    canWriteChildren,
    saveEncounter,
    complete,
    soap,
    patchSoap,
    noteStatus,
    conflict,
    dirty,
    autoSaveStatus,
  };
}
