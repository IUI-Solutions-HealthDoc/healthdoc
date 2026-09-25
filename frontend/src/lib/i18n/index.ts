"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { en, type MessageKey } from "./messages/en";
import { hi } from "./messages/hi";

export type SupportedLocale = "en" | "hi";

export interface LocaleOption {
  code: SupportedLocale;
  label: string;
  nativeLabel: string;
}

export const SUPPORTED_LOCALES: LocaleOption[] = [
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "hi", label: "Hindi", nativeLabel: "हिंदी" },
];

const CATALOGUES: Record<SupportedLocale, Record<MessageKey, string>> = {
  en,
  hi,
};

const STORAGE_KEY = "healthdoc_locale";
let currentLocale: SupportedLocale = "en";
const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function getStoredLocale(): SupportedLocale {
  if (typeof window === "undefined") return "en";
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "en" || stored === "hi") return stored;
  return "en";
}

export function setLocale(newLocale: SupportedLocale) {
  if (newLocale === currentLocale) return;
  currentLocale = newLocale;
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEY, newLocale);
    document.documentElement.lang = newLocale;
  }
  emitChange();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): SupportedLocale {
  return currentLocale;
}

function getServerSnapshot(): SupportedLocale {
  return "en";
}

/**
 * Resolve a bilingual master-data field. English remains the source of truth;
 * Hindi is shown when the active locale is `hi` and a non-empty value exists.
 */
export function localizeField(
  enValue: string,
  hiValue: string | null | undefined,
  locale: SupportedLocale = currentLocale,
): string {
  if (locale === "hi" && hiValue && hiValue.trim()) return hiValue.trim();
  return enValue;
}

export function translate(
  key: MessageKey,
  locale: SupportedLocale = currentLocale,
  vars?: Record<string, string | number>,
): string {
  let text: string = CATALOGUES[locale][key] ?? CATALOGUES.en[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

export function useLocale() {
  const locale = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    const initial = getStoredLocale();
    if (initial !== currentLocale) {
      currentLocale = initial;
      emitChange();
    }
    document.documentElement.lang = initial;
  }, []);

  const t = useCallback(
    (key: MessageKey, vars?: Record<string, string | number>): string => {
      return translate(key, locale, vars);
    },
    [locale],
  );

  const lf = useCallback(
    (enValue: string, hiValue?: string | null): string => {
      return localizeField(enValue, hiValue, locale);
    },
    [locale],
  );

  return {
    locale,
    setLocale,
    t,
    localizeField: lf,
    locales: SUPPORTED_LOCALES,
  };
}

export type { MessageKey };
