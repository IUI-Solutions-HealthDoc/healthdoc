"use client";

import { useEffect, useState, type ReactNode } from "react";

import { getFacilityCapabilities } from "@/features/admin/api/facilityModules";
import { MODULE_CODE_LABELS } from "@/features/admin/constants";
import type { ModuleCode } from "@/features/admin/types";
import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

type GateState = "loading" | "enabled" | "disabled" | "error";

/**
 * Schema §Module toggle rule 6: UI hides, never 404s.
 * GET /facility/capabilities drives the screen; a disabled module (or 409
 * module_disabled) shows "not offered at this facility".
 */
export function ModuleCapabilityGate({
  module,
  children,
}: {
  module: ModuleCode;
  children: ReactNode;
}) {
  const { t } = useLocale();
  const [state, setState] = useState<GateState>("loading");

  useEffect(() => {
    let cancelled = false;
    getFacilityCapabilities()
      .then((caps) => {
        if (!cancelled) setState(caps.modules[module] ? "enabled" : "disabled");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.isModuleDisabled) {
          setState("disabled");
          return;
        }
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [module]);

  if (state === "loading") {
    return (
      <main style={{ padding: "2rem" }}>
        <p>{t("common.ui.loadingFacilityCapabilities")}</p>
      </main>
    );
  }

  if (state === "disabled") {
    return (
      <main style={{ padding: "2rem" }}>
        <h1>{MODULE_CODE_LABELS[module]}</h1>
        <p>{t("common.ui.notOfferedAtThisFacility")}</p>
      </main>
    );
  }

  if (state === "error") {
    return (
      <main style={{ padding: "2rem" }}>
        <h1>{MODULE_CODE_LABELS[module]}</h1>
        <p>{t("common.ui.couldNotLoadFacilityCapabilitiesRetry")}</p>
      </main>
    );
  }

  return <>{children}</>;
}
