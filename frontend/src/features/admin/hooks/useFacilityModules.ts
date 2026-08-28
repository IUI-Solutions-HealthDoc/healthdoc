"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { getUserFacingError } from "@/lib/api";
import {
  getFacilityCapabilities,
  listFacilityModules,
  updateFacilityModule,
} from "../api";
import type { FacilityCapabilities, FacilityModule } from "../types";

export function useFacilityModules() {
  const [modules, setModules] = useState<FacilityModule[]>([]);
  const [capabilities, setCapabilities] = useState<FacilityCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Keyed on module_code, not row id: a module with no stored row has no id
   *  until the first time somebody disables it. */
  const [busyCode, setBusyCode] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [mods, caps] = await Promise.all([
        listFacilityModules(),
        getFacilityCapabilities(),
      ]);
      setModules(mods);
      setCapabilities(caps);
      setError(null);
    } catch (reason) {
      setModules([]);
      setCapabilities(null);
      setError(getUserFacingError(reason, "Could not load facility modules."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = useCallback(
    async (moduleCode: string, is_enabled: boolean, disabled_reason?: string | null) => {
      setBusyCode(moduleCode);
      try {
        // No "Disabled by admin" default. The server requires a real reason
        // when disabling, and a placeholder is exactly the non-answer the
        // requirement exists to prevent — switching a module off makes a whole
        // department's endpoints answer 409.
        await updateFacilityModule(moduleCode, {
          is_enabled,
          disabled_reason: is_enabled ? null : disabled_reason,
        });
        await refresh();
        toast.success(is_enabled ? "Module enabled" : "Module disabled");
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Update failed");
      } finally {
        setBusyCode(null);
      }
    },
    [refresh],
  );

  return { modules, capabilities, loading, error, busyCode, toggle, refresh };
}
