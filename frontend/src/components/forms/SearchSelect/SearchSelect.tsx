"use client";

import { useMemo, useState } from "react";

import { SearchSelectProps } from "./SearchSelect.types";
import { useLocale, translate } from "@/lib/i18n";

export default function SearchSelect({
  label,
  name,
  placeholder = translate("common.msg.search"),
  options,
  value,
  onChange,
  error,
}: SearchSelectProps) {
  const { t } = useLocale();
  const [search, setSearch] = useState("");

  const filteredOptions = useMemo(() => {
    return options.filter((option) =>
      option.label.toLowerCase().includes(search.toLowerCase())
    );
  }, [options, search]);

  const fieldId = `field-${name ?? label.toLowerCase().replace(/\s+/g, "-")}`;
  const listboxId = `${fieldId}-listbox`;
  const errorId = `${fieldId}-error`;

  return (
    <div className="space-y-2">
      <label htmlFor={fieldId} className="text-sm font-medium">
        {label}
      </label>

      <input
        id={fieldId}
        type="text"
        role="combobox"
        aria-expanded="true"
        aria-controls={listboxId}
        aria-invalid={!!error}
        aria-describedby={error ? errorId : undefined}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={placeholder}
        className="
          w-full
          rounded-lg
          border
          border-border
          bg-background
          px-3
          py-2.5
          text-sm
          outline-none
          focus:border-primary
        "
      />

      <div
        id={listboxId}
        role="listbox"
        aria-label={label}
        className="max-h-52 overflow-y-auto rounded-lg border border-border"
      >
        {filteredOptions.length === 0 && (
          <p className="px-4 py-3 text-sm text-muted-foreground">{t("common.ui.noMatchesFound")}</p>
        )}

        {filteredOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            role="option"
            aria-selected={value === option.value}
            onClick={() => onChange(option.value)}
            className={`w-full border-b border-border px-4 py-3 text-left hover:bg-muted ${
              value === option.value
                ? "bg-primary text-primary-foreground"
                : ""
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {error && (
        <p id={errorId} className="text-xs text-danger">
          {error.message}
        </p>
      )}
    </div>
  );
}
