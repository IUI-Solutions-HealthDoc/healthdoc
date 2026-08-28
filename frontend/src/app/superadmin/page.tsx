"use client";

import { useCallback, useEffect, useState } from "react";

import { getUserFacingError } from "@/lib/api";
import {
  listPlatformFacilities,
  type PlatformFacility,
} from "@/features/platform/api";

export default function Page() {
  const [facilities, setFacilities] = useState<PlatformFacility[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (search = "") => {
    setLoading(true);
    setError(null);
    try {
      const response = await listPlatformFacilities(search);
      setFacilities(response.items);
      setTotal(response.total);
    } catch (reason) {
      setError(getUserFacingError(reason, "Could not load platform facilities."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-primary">
          Platform administration
        </p>
        <h1 className="mt-2 text-3xl font-semibold">Facilities</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Platform metadata only. This workspace never requests patient, encounter, merge or
          other clinical records.
        </p>
      </div>

      <form
        className="surface-card flex flex-col gap-3 p-4 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void load(query);
        }}
      >
        <label className="flex-1 space-y-1 text-sm">
          <span className="text-muted-foreground">Search facility name, code or HFR ID</span>
          <input
            className="w-full rounded-md border border-border px-3 py-2"
            value={query}
            maxLength={100}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="self-end rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Search
        </button>
      </form>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <section className="surface-card overflow-hidden">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-lg font-medium">Registered facilities</h2>
          <p className="mt-1 text-sm text-muted-foreground">{total} total</p>
        </div>
        {loading ? (
          <p className="p-5 text-sm text-muted-foreground">Loading facilities…</p>
        ) : facilities.length === 0 ? (
          <p className="p-5 text-sm text-muted-foreground">No facilities match this search.</p>
        ) : (
          <ul className="divide-y divide-border">
            {facilities.map((facility) => (
              <li key={facility.id} className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto]">
                <div>
                  <p className="font-medium">{facility.name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {facility.code} · {facility.state_code}
                    {facility.district ? ` · ${facility.district}` : ""}
                    {facility.hfr_facility_id ? ` · HFR ${facility.hfr_facility_id}` : ""}
                  </p>
                </div>
                <span
                  className={`self-start rounded-full px-3 py-1 text-xs font-medium ${
                    facility.is_active
                      ? "bg-success-muted text-success"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {facility.is_active ? "Active" : "Inactive"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
