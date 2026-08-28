"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { toast } from "@/components/ui/toast";
import { activateUser, deactivateUser, updateUser } from "../api";
import type { User, UserUpdateInput } from "../types";
import { type FieldErrors, validateUserProfile } from "../validation";

export function useUserEditor(user: User | null, onSaved?: (next: User) => void) {
  const [draft, setDraft] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});

  useEffect(() => {
    setDraft(user ? structuredClone(user) : null);
    setErrors({});
  }, [user]);

  const isDirty = useMemo(() => {
    if (!user || !draft) return false;
    return JSON.stringify(user) !== JSON.stringify(draft);
  }, [user, draft]);

  const patchField = useCallback(
    <K extends keyof UserUpdateInput>(key: K, value: UserUpdateInput[K]) => {
      if (!draft) return;
      setDraft({ ...draft, [key]: value } as User);
      setErrors((current) => {
        if (!current[key]) return current;
        const next = { ...current };
        delete next[key];
        return next;
      });
    },
    [draft],
  );

  const save = useCallback(async () => {
    if (!draft) return;
    const validationErrors = validateUserProfile(draft);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      toast.error("Please correct the highlighted profile fields before saving.");
      return;
    }
    setBusy(true);
    try {
      const next = await updateUser(draft.id, {
        full_name: draft.full_name,
        email: draft.email,
        mobile: draft.mobile,
        designation: draft.designation,
        employee_id: draft.employee_id,
        registration_number: draft.registration_number,
        qualification: draft.qualification,
        department_id: draft.department_id,
      });
      setDraft(next);
      onSaved?.(next);
      toast.success("User updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }, [draft, onSaved]);

  const toggleActive = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    try {
      if (draft.is_active) {
        await deactivateUser(draft.id);
        const next = { ...draft, is_active: false };
        setDraft(next);
        onSaved?.(next);
        toast.success("User deactivated");
      } else {
        await activateUser(draft.id);
        const next = { ...draft, is_active: true };
        setDraft(next);
        onSaved?.(next);
        toast.success("User activated");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Status change failed");
    } finally {
      setBusy(false);
    }
  }, [draft, onSaved]);

  return { draft, busy, isDirty, errors, patchField, save, toggleActive };
}
