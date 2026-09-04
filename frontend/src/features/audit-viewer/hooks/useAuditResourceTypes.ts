"use client";

import { useEffect, useState } from "react";

import { listAuditResourceTypes } from "../api";

/**
 * The resource types the Resource dropdown should offer.
 *
 * Fetched rather than hard-coded so the filter cannot drift from the data
 * again — the hand-kept list offered three types that matched nothing while
 * hiding most of what the table held.
 *
 * A failure returns an empty list rather than surfacing an error: the caller
 * falls back to COMMON_RESOURCE_TYPES, and a filter dropdown briefly showing
 * fewer options is not worth an error banner on an audit screen.
 */
export function useAuditResourceTypes(): string[] {
  const [types, setTypes] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    listAuditResourceTypes()
      .then((items) => {
        if (!cancelled) setTypes(items);
      })
      .catch(() => {
        if (!cancelled) setTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return types;
}
