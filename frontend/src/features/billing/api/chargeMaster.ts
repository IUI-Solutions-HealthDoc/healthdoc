/**
 * Charge master — the effective-dated tariff catalogue (0033).
 * Retired from fixtures (P1.1).
 *
 * `resolveTariff` was REMOVED rather than wired. Pricing is resolved
 * server-side inside `build_invoice`, against the tariff that was effective on
 * the visit's business date. A browser-side resolver would price from today's
 * catalogue, so re-opening a month-old visit would show a different figure than
 * the invoice actually carries — and the invoice is right.
 *
 * The preview endpoint is the honest way to ask "what would this cost": it
 * returns each prospective line with `priced: true|false` and a
 * `pricing_note` when no tariff was found.
 */
import { api } from "@/lib/api";
import type { ChargeMaster, TariffCreateInput } from "../types";

export interface ChargeMasterListFilters {
  /** Server-side active flag, not whether a tariff is effective today. */
  active_only?: boolean;
  charge_code?: string;
  scheme_code?: string | "all";
}

/**
 * GET /billing/charge-master — the facility's tariff rows.
 *
 * The API client unwraps Envelope.data, which is an array, not { items }.
 * active_only and charge_code are server filters; scheme filtering applies
 * to the complete unpaginated result. Active is not the same as effective today.
 */
export async function listChargeMaster(
  filters: ChargeMasterListFilters = {},
): Promise<ChargeMaster[]> {
  const params = new URLSearchParams({ active_only: String(filters.active_only ?? true) });
  if (filters.charge_code) params.set("charge_code", filters.charge_code);
  const response = await api<ChargeMaster[]>(`/billing/charge-master?${params}`);
  if (!Array.isArray(response)) throw new Error("The tariff catalogue returned an invalid response. Reload and try again.");
  let rows = response;
  if (filters.scheme_code && filters.scheme_code !== "all") {
    rows = rows.filter((r) => r.scheme_code === filters.scheme_code);
  }
  return rows;
}

/**
 * One tariff row.
 *
 * Narrowed from the list — there is no by-id endpoint, and the catalogue is
 * small enough per facility that a second round trip would buy nothing.
 */
export async function getChargeMaster(tariffId: string): Promise<ChargeMaster | null> {
  const rows = await listChargeMaster({ active_only: false });
  return rows.find((row) => row.id === tariffId) ?? null;
}

// Keep the action key stable: the server replays the committed result for the
// same actor/key/body. The UI still requires read-back after an ambiguous error
// instead of automatically retrying a price change.
export function createTariff(body: TariffCreateInput, actionKey: string): Promise<ChargeMaster> {
  return api<ChargeMaster>("/billing/charge-master", {
    method: "POST", body: JSON.stringify(body), idempotencyKey: actionKey,
  });
}

export function deactivateTariff(id: string, actionKey: string): Promise<void> {
  return api<void>(`/billing/charge-master/${encodeURIComponent(id)}/deactivate`, {
    method: "POST", idempotencyKey: actionKey,
  });
}
