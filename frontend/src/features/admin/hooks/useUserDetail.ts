"use client";

import { useCallback, useEffect, useState } from "react";

import { getUser } from "../api";
import type { User } from "../types";
import { getUserFacingError } from "@/lib/api";

export function useUserDetail(userId: string | null) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!userId) {
      setUser(null);
      setError(null);
      return;
    }
    setLoading(true);
    try {
      setUser(await getUser(userId));
      setError(null);
    } catch (reason) {
      setUser(null);
      setError(getUserFacingError(reason, "Could not load this user."));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { user, setUser, loading, error, refresh };
}
