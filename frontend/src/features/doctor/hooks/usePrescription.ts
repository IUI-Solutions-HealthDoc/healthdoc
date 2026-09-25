"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { useLocale } from "@/lib/i18n";
import { checkAllergies, createPrescription } from "../api";
import { ALLERGY_OVERRIDE_REASON_MIN, FREQUENCIES_WITHOUT_DURATION } from "../constants";
import type {
  ActiveEncounter,
  DraftPrescriptionItem,
  EncounterContext,
  Medicine,
  AllergyAlert,
} from "../types";

function itemFromMedicine(m: Medicine): DraftPrescriptionItem {
  return {
    tempId: crypto.randomUUID(),
    medicine_item_id: m.id,
    medicine_name: m.name,
    ingredient_code: m.ingredient_code,
    generic_name: m.generic_name,
    strength: m.strength,
    form: m.form,
    is_controlled_drug: m.is_controlled_drug,
    dosage: "",
    frequency: "OD",
    duration_days: 5,
    route: "oral",
    instructions: "",
  };
}

export function usePrescription(encounter: ActiveEncounter, context: EncounterContext) {
  const { t } = useLocale();
  const [items, setItems] = useState<DraftPrescriptionItem[]>([]);
  const [notes, setNotes] = useState("");
  const [alerts, setAlerts] = useState<AllergyAlert[]>([]);
  const [checking, setChecking] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [saving, setSaving] = useState(false);

  // Re-check allergies whenever the item set changes. One call per item, on
  // ingredient_code — matching a stock item would let a second brand of the same
  // ingredient through for a patient who reacts to the first.
  useEffect(() => {
    let live = true;
    if (items.length === 0) {
      setAlerts([]);
      return;
    }
    setChecking(true);
    void Promise.all(
      items.map((i) => checkAllergies(context.patient_id, i.medicine_name, i.ingredient_code)),
    )
      .then((results) => {
        if (live) setAlerts(results.filter((r): r is AllergyAlert => r !== null));
      })
      .finally(() => {
        if (live) setChecking(false);
      });
    return () => {
      live = false;
    };
  }, [items, context.patient_id]);

  const addMedicine = useCallback((m: Medicine) => {
    setItems((prev) =>
      prev.some((i) => i.medicine_item_id === m.id) ? prev : [...prev, itemFromMedicine(m)],
    );
  }, []);

  const updateItem = useCallback(
    (tempId: string, patch: Partial<DraftPrescriptionItem>) =>
      setItems((prev) =>
        prev.map((i) => {
          if (i.tempId !== tempId) return i;
          const next = { ...i, ...patch };
          // As-needed / single-dose frequencies carry no duration.
          if (patch.frequency && FREQUENCIES_WITHOUT_DURATION.includes(patch.frequency as never)) {
            next.duration_days = undefined;
          }
          return next;
        }),
      ),
    [],
  );

  const removeItem = useCallback(
    (tempId: string) => setItems((prev) => prev.filter((i) => i.tempId !== tempId)),
    [],
  );

  /** Anaphylaxis: cannot be prescribed at all, no override at any length. */
  const hasBlocking = alerts.some((a) => a.kind === "block");
  /** A non-anaphylaxis allergy: prescribable, but only with a written reason. */
  const needsOverride = alerts.some((a) => a.kind === "override_required");
  const overrideOk =
    !needsOverride || overrideReason.trim().length >= ALLERGY_OVERRIDE_REASON_MIN;

  const save = useCallback(async () => {
    if (items.length === 0) {
      toast.error(t("doctor.toast.addMedicineRequired"));
      return;
    }
    const incomplete = items.find((i) => i.dosage.trim() === "");
    if (incomplete) {
      toast.error(t("doctor.toast.enterDosageFor", { name: incomplete.medicine_name }));
      return;
    }
    setSaving(true);
    try {
      await createPrescription({
        encounter_id: encounter.id,
        notes: notes.trim() || undefined,
        items: items.map((i) => ({
          medicine_item_id: i.medicine_item_id,
          medicine_name: i.medicine_name,
        // Only attach the reason to items that actually needed an override.
        override_reason: alerts.some(
          (a) => a.kind === "override_required" && a.medicine_name === i.medicine_name,
        )
          ? overrideReason.trim()
          : undefined,
          dosage: i.dosage,
          frequency: i.frequency,
          duration_days: i.duration_days,
          route: i.route,
          instructions: i.instructions,
        })),
      });
      // Real write — POST /orders/prescriptions. No localOnly() suffix.
      toast.success(t("doctor.toast.prescriptionSaved"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("doctor.toast.savePrescriptionFailed"));
    } finally {
      setSaving(false);
    }
  }, [alerts, encounter, items, notes, overrideReason, t]);

  return {
    items,
    notes,
    setNotes,
    alerts,
    checking,
    hasBlocking,
    needsOverride,
    overrideReason,
    setOverrideReason,
    overrideOk,
    saving,
    addMedicine,
    updateItem,
    removeItem,
    save,
  };
}
