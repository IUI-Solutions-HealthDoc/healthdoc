"use client";

import { useCallback, useEffect, useState } from "react";

import { listUsers } from "../api";
import type { User, UserListFilters } from "../types";
import { translate } from "@/lib/i18n";

export function useUsers(initial: UserListFilters = {}) {
  const [filters, setFilters] = useState<UserListFilters>({
    query: "",
    is_active: null,
    page: 1,
    page_size: 50,
    ...initial,
  });
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listUsers(filters);
      setUsers(res.items);
      // BE omits total — fall back to page length when unknown
      setTotal(res.total ?? res.items.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : translate("admin.msg.failedToLoadUsers"));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    users,
    total,
    loading,
    error,
    filters,
    setQuery: (query: string) => setFilters((f) => ({ ...f, query, page: 1 })),
    setActiveFilter: (is_active: boolean | null) =>
      setFilters((f) => ({ ...f, is_active, page: 1 })),
    refresh,
  };
}
