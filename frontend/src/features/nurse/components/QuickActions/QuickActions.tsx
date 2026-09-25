"use client";

import { useLocale } from "@/lib/i18n";

import { QUICK_ACTIONS } from "./constants";
import { QuickActionsProps } from "./QuickActions.types";

export default function QuickActions({ onAction }: QuickActionsProps) {
  const { t } = useLocale();

  return (
    <section className="surface-card p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold">{t("nurse.quickActionsTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("nurse.quickActionsSubtitle")}</p>
      </div>

      <div className="grid gap-4 grid-cols-2 xl:grid-cols-3">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.id}
            onClick={() => onAction?.(action.id)}
            className="rounded-xl border border-border p-5 text-left transition hover:-translate-y-1 hover:shadow-md"
          >
            <div
              className={`inline-flex h-12 w-12 items-center justify-center rounded-full text-xl ${action.color}`}
            >
              {action.icon}
            </div>

            <h3 className="mt-4 font-semibold">{t(action.labelKey)}</h3>
          </button>
        ))}
      </div>
    </section>
  );
}
