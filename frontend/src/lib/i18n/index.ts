"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

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

const TRANSLATIONS: Record<SupportedLocale, Record<string, string>> = {
  en: {
    "nav.registration": "Register patient",
    "nav.search": "Patient search",
    "nav.queue": "Queue",
    "nav.appointments": "Appointments",
    "nav.billing": "Billing",
    "nav.consent": "Consent",
    "nav.nurse": "Nurse Desk",
    "nav.doctor": "Consultations",
    "nav.admin": "Administration",
    "nav.reports": "Reports",
    "nav.logout": "Sign out",
    "counter.label": "Counter",
    "counter.select": "Select Counter",
    "card.print": "Print Card",
    "common.search": "Search",
    "common.clear": "Clear",
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.startVisit": "Start visit",
    "common.online": "Clinical System Online",
  },
  hi: {
    "nav.registration": "मरीज़ पंजीकरण",
    "nav.search": "मरीज़ खोजें",
    "nav.queue": "कतार प्रबंधन",
    "nav.appointments": "अपॉइंटमेंट",
    "nav.billing": "बिलिंग",
    "nav.consent": "सहमति",
    "nav.nurse": "नर्सिंग डेस्क",
    "nav.doctor": "परामर्श",
    "nav.admin": "प्रशासन",
    "nav.reports": "रिपोर्ट्स",
    "nav.logout": "साइन आउट",
    "counter.label": "काउंटर",
    "counter.select": "काउंटर चुनें",
    "card.print": "कार्ड प्रिंट करें",
    "common.search": "खोजें",
    "common.clear": "साफ़ करें",
    "common.save": "सहेजें",
    "common.cancel": "रद्द करें",
    "common.startVisit": "विज़िट शुरू करें",
    "common.online": "चिकित्सा प्रणाली ऑनलाइन",
  },
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
    (key: string, fallback?: string): string => {
      return TRANSLATIONS[locale]?.[key] ?? fallback ?? key;
    },
    [locale],
  );

  return {
    locale,
    setLocale,
    t,
    locales: SUPPORTED_LOCALES,
  };
}
