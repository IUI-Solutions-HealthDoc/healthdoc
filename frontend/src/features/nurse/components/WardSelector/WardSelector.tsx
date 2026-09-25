"use client";

import { useLocale } from "@/lib/i18n";
import { WardSelectorProps } from "./WardSelector.types";

export default function WardSelector({
  wards,
  selectedWard,
  onChange,
}: WardSelectorProps) {
  const { localizeField } = useLocale();
  const activeWards = wards.filter((ward) => ward.is_active);

  return (
    <section className="surface-card p-6">
      <label htmlFor="ward" className="mb-2 block text-sm font-semibold">
        Ward
      </label>

      <select
        id="ward"
        value={selectedWard}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-border bg-background px-4 py-3 outline-none focus:ring-2 focus:ring-ring"
      >
        {activeWards.map((ward) => (
          <option key={ward.id} value={ward.id}>
            {localizeField(ward.name, ward.name_hi)}
          </option>
        ))}
      </select>
    </section>
  );
}
