"use client";

import { useEffect, useSyncExternalStore } from "react";

export const AUTHORIZED_COUNTERS = [
  "Counter 1",
  "Counter 2",
  "Counter 3",
  "Registration Desk A",
  "Registration Desk B",
] as const;

export type AuthorizedCounter = (typeof AUTHORIZED_COUNTERS)[number];

const STORAGE_KEY = "healthdoc_desk_counter";
let currentCounter: AuthorizedCounter = "Counter 1";
const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function getStoredCounter(): AuthorizedCounter {
  if (typeof window === "undefined") return "Counter 1";
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && (AUTHORIZED_COUNTERS as readonly string[]).includes(stored)) {
    return stored as AuthorizedCounter;
  }
  return "Counter 1";
}

export function setDeskCounter(counter: string): boolean {
  // Reject unauthorized counter location
  if (!(AUTHORIZED_COUNTERS as readonly string[]).includes(counter)) {
    return false;
  }
  currentCounter = counter as AuthorizedCounter;
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEY, counter);
  }
  emitChange();
  return true;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): AuthorizedCounter {
  return currentCounter;
}

function getServerSnapshot(): AuthorizedCounter {
  return "Counter 1";
}

export function useDeskCounter() {
  const counter = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    const initial = getStoredCounter();
    if (initial !== currentCounter) {
      currentCounter = initial;
      emitChange();
    }
  }, []);

  return {
    counter,
    setDeskCounter,
    availableCounters: AUTHORIZED_COUNTERS,
  };
}
