"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";
import {
  listDiagnoses,
  saveDiagnosis,
  searchIcd,
  searchTerminology,
  type TerminologyConcept,
} from "../api";
import type {
  ActiveEncounter,
  CreateDiagnosisInput,
  DraftDiagnosis,
  IcdConcept,
  IcdVersion,
} from "../types";

export function useDiagnoses(encounter: ActiveEncounter) {
  const { t } = useLocale();
  const [rows, setRows] = useState<DraftDiagnosis[]>([]);
  const [options, setOptions] = useState<IcdConcept[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const searchSequence = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void listDiagnoses(encounter.id)
      .then((diagnoses) => {
        if (cancelled) return;
        setRows(
          diagnoses.map((row) => ({
            tempId: row.id,
            persisted: true,
            icd_code: row.icd_code,
            icd_version: row.icd_version,
            icd_uri: row.icd_uri,
            post_coordinated_code: row.post_coordinated_code,
            diagnosis_text: row.diagnosis_text,
            diagnosis_type: row.diagnosis_type,
            is_primary: row.is_primary,
          })),
        );
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          toast.error(error instanceof Error ? error.message : t("doctor.toast.loadDiagnosesFailed"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [encounter.id, t]);

  const search = useCallback(
    async (query: string, system: "all" | "icd10" | "icd11" | "snomed" = "all") => {
      const sequence = ++searchSequence.current;
      try {
        const termResults = await searchTerminology(query, system);
        if (termResults.length > 0) {
          const mapped: IcdConcept[] = termResults.map((t: TerminologyConcept) => ({
            code: t.code,
            version: t.system as IcdVersion,
            title: t.display,
            icd_uri: t.system_uri,
          }));
          if (sequence === searchSequence.current) setOptions(mapped);
          return;
        }
      } catch {
        // Fallback to legacy icd search if terminology search endpoint errors
      }
      const results = await searchIcd(query);
      if (sequence === searchSequence.current) setOptions(results);
    },
    [],
  );

  const addConcept = useCallback((concept: IcdConcept) => {
    setRows((prev) => {
      if (prev.some((r) => r.icd_code === concept.code && r.icd_version === concept.version)) {
        return prev;
      }
      return [
        ...prev,
        {
          tempId: crypto.randomUUID(),
          icd_code: concept.code,
          icd_version: concept.version,
          icd_uri: concept.icd_uri,
          post_coordinated_code: undefined,
          diagnosis_text: concept.title,
          diagnosis_type: "provisional",
          is_primary: !prev.some((row) => row.is_primary),
        },
      ];
    });
  }, []);

  const updateRow = useCallback(
    (tempId: string, patch: Partial<DraftDiagnosis>) =>
      setRows((prev) =>
        prev.map((r) =>
          r.tempId === tempId && !r.persisted ? { ...r, ...patch } : r,
        ),
      ),
    [],
  );

  const setPrimary = useCallback(
    (tempId: string) =>
      setRows((prev) => {
        if (prev.some((row) => row.persisted && row.is_primary)) return prev;
        return prev.map((row) =>
          row.persisted ? row : { ...row, is_primary: row.tempId === tempId },
        );
      }),
    [],
  );

  const removeRow = useCallback(
    (tempId: string) =>
      setRows((prev) => {
        const next = prev.filter((r) => r.persisted || r.tempId !== tempId);
        const firstDraft = next.find((row) => !row.persisted);
        if (firstDraft && !next.some((r) => r.is_primary)) firstDraft.is_primary = true;
        return next;
      }),
    [],
  );

  const save = useCallback(async () => {
    const pending = rows.filter((row) => !row.persisted);
    if (pending.length === 0) {
      toast.error(t("doctor.toast.addDiagnosisRequired"));
      return;
    }
    setSaving(true);
    const savedIds: string[] = [];
    try {
      for (const row of pending) {
        const payload: CreateDiagnosisInput = {
          encounter_id: encounter.id,
          icd_code: row.icd_code,
          icd_version: row.icd_version,
          icd_uri: row.icd_uri,
          post_coordinated_code: row.post_coordinated_code,
          diagnosis_text: row.diagnosis_text,
          diagnosis_type: row.diagnosis_type,
          is_primary: row.is_primary,
        };
        await saveDiagnosis(payload, row.tempId);
        savedIds.push(row.tempId);
      }
      setRows((current) =>
        current.map((row) =>
          savedIds.includes(row.tempId) ? { ...row, persisted: true } : row,
        ),
      );
      toast.success(
        pending.length === 1
          ? t("doctor.toast.diagnosesSavedOne")
          : t("doctor.toast.diagnosesSavedMany", { count: pending.length }),
      );
    } catch (e) {
      if (savedIds.length > 0) {
        setRows((current) =>
          current.map((row) =>
            savedIds.includes(row.tempId) ? { ...row, persisted: true } : row,
          ),
        );
      }
      const prefix =
        savedIds.length > 0 ? t("doctor.toast.diagnosesPartialPrefix", { saved: savedIds.length }) : "";
      toast.error(`${prefix}${e instanceof Error ? e.message : t("doctor.toast.saveDiagnosesFailed")}`);
    } finally {
      setSaving(false);
    }
  }, [encounter.id, rows, t]);

  return {
    rows,
    options,
    loading,
    search,
    addConcept,
    updateRow,
    setPrimary,
    removeRow,
    saving,
    save,
  };
}
