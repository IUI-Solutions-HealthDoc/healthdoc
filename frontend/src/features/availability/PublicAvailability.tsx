"use client";

/**
 * Public bed and blood availability: no login. For families deciding where
 * to go, and for referring hospitals. Only facilities whose owner has opted in
 * appear; counts come from the 15-minute capture, so the page tells people to
 * call before travelling and marks a hospital that has stopped updating.
 *
 * Plain fetch, not the shared api() client: that client attaches a session
 * and redirects to login on 401, neither of which applies to a public page.
 */
import { useEffect, useState } from "react";

import { API_BASE_URL, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

interface FacilityAvailability {
  facility_id: string;
  name: string;
  district: string | null;
  facility_type: string | null;
  updated_at: string | null;
  stale: boolean;
  beds_free: number | null;
  beds_total: number | null;
  wards: { ward: string; free: number; beds: number }[];
  blood: Record<string, number>;
}

interface Availability {
  state_code: string;
  district: string | null;
  generated_at: string;
  facilities: FacilityAvailability[];
  note: string;
}

// Stored codes (blood_bank) to the labels people read.
const BLOOD_LABEL: Record<string, string> = {
  a_pos: "A+", a_neg: "A-", b_pos: "B+", b_neg: "B-", ab_pos: "AB+", ab_neg: "AB-", o_pos: "O+", o_neg: "O-",
};
const BLOOD_ORDER = Object.keys(BLOOD_LABEL);

export function PublicAvailability() {
  const { t } = useLocale();
  const [state, setState] = useState("BR");
  const [district, setDistrict] = useState("");
  const [query, setQuery] = useState({ state: "BR", district: "" });
  const [data, setData] = useState<Availability | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams({ state: query.state });
    if (query.district.trim()) params.set("district", query.district.trim());
    setLoading(true);
    fetch(`${API_BASE_URL}/public/availability?${params.toString()}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as Availability;
      })
      .then((loaded) => {
        if (!current) return;
        setData(loaded);
        setError(null);
      })
      .catch(() => current && setError(t("availability.errLoad")))
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [query, t]);

  return (
    <main className="mx-auto max-w-5xl space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("availability.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("availability.intro")}</p>
      </div>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (/^[A-Za-z]{2,5}$/.test(state)) setQuery({ state: state.toUpperCase(), district });
        }}
      >
        <label className="text-sm">
          <span className="block text-muted-foreground">{t("availability.state")}</span>
          <input value={state} onChange={(e) => setState(e.target.value.toUpperCase().trim())} maxLength={5}
            className="mt-1 w-24 rounded-md border border-border px-2 py-1.5" />
        </label>
        <label className="text-sm">
          <span className="block text-muted-foreground">{t("availability.district")}</span>
          <input value={district} onChange={(e) => setDistrict(e.target.value)} maxLength={100}
            className="mt-1 w-56 rounded-md border border-border px-2 py-1.5" />
        </label>
        <button type="submit" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white">
          {t("common.search")}
        </button>
      </form>

      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {loading && !data ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {data ? (
        <>
          <p className="text-sm text-amber-900">{data.note}</p>
          {data.facilities.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("availability.none")}</p>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2">
              {data.facilities.map((facility) => {
                const groups = BLOOD_ORDER.filter((code) => (facility.blood[code] ?? 0) > 0);
                return (
                  <li key={facility.facility_id} className="rounded border border-border p-4 text-sm">
                    <p className="font-semibold">{facility.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {[facility.district, facility.facility_type].filter(Boolean).join(" · ")}
                    </p>
                    {facility.stale ? (
                      <p className="mt-2 text-xs font-medium text-amber-800">{t("availability.stale")}</p>
                    ) : null}
                    {facility.beds_free !== null && facility.beds_total !== null ? (
                      <p className="mt-2">
                        <span className="text-2xl font-semibold tabular-nums">{facility.beds_free}</span>{" "}
                        {t("availability.bedsFree", { total: facility.beds_total })}
                      </p>
                    ) : (
                      <p className="mt-2 text-muted-foreground">{t("availability.noBedData")}</p>
                    )}
                    {facility.wards.length ? (
                      <ul className="mt-1 text-xs text-muted-foreground">
                        {facility.wards.map((ward) => (
                          <li key={ward.ward}>
                            {ward.ward}: {ward.free}/{ward.beds}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    <p className="mt-3 text-xs font-medium">{t("availability.blood")}</p>
                    {groups.length ? (
                      <ul className="mt-1 flex flex-wrap gap-2">
                        {groups.map((code) => (
                          <li key={code} className="rounded border border-border px-2 py-0.5 text-xs">
                            {BLOOD_LABEL[code]} · {facility.blood[code]}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-muted-foreground">{t("availability.noBlood")}</p>
                    )}
                    {facility.updated_at ? (
                      <p className="mt-3 text-xs text-muted-foreground">
                        {t("availability.updated")} {formatDateTime(facility.updated_at)}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      ) : null}
    </main>
  );
}
