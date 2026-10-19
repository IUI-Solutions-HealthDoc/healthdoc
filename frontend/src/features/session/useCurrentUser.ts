"use client";

import { useEffect, useState } from "react";

import { getMe, type CurrentUser } from "./api";
import { translate } from "@/lib/i18n";

/**
 * The caller's identity and facility, for display.
 *
 * Deliberately has no fallback. The previous behaviour — a hardcoded
 * `MOCK_FACILITY_ID` — meant a screen that could not identify its facility
 * showed a plausible wrong one instead of admitting it did not know. A facility
 * label is the thing a user checks to confirm they are looking at their own
 * hospital's data, so guessing is worse than blank.
 *
 * `null` while loading or on error; callers render nothing rather than a guess.
 */
export function useCurrentUser(): {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
} {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setUser(null);
          setError(e instanceof Error ? e.message : translate("common.msg.couldNotLoadYourAccount"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading, error };
}
