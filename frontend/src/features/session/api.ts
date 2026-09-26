import { api } from "@/lib/api";

/**
 * The caller's own identity and facility, from GET /users/me.
 *
 * This replaces `MOCK_FACILITY_ID`, which five feature modules re-exported as
 * `FACILITY_ID` because nothing on the wire told the browser which facility it
 * was in. The constant was not only fake — it was being *sent*, as
 * `facility_id`, in the create-user and account-request bodies.
 *
 * The backend now derives facility scope from the token and refuses a body
 * `facility_id` that disagrees (403), so those screens would have failed on
 * every submission once wired to the real API.
 *
 * Use this for display only. Never send `facility_id` from the browser.
 */
export interface CurrentUser {
  id: string;
  username: string;
  full_name: string;
  roles: string[];
  facility: {
    id: string;
    code: string;
    name: string;
    name_hi?: string | null;
    timezone: string;
  };
  /**
   * The caller's home department, or null.
   *
   * Null for facility-wide roles — admin and auditor belong to no one
   * department — so every consumer must handle it. Added for the HOD
   * dashboard, which is per-department; a picker would have been wrong there,
   * because the hod-dashboard endpoints are scoped to the caller's facility
   * rather than their department, and choosing one is not the user's to make.
   */
  department: {
    id: string;
    code: string;
    name: string;
    name_hi?: string | null;
  } | null;
}

export function getMe(): Promise<CurrentUser> {
  return api<CurrentUser>("/users/me");
}
