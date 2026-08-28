import type { Role } from "@/config/roles";
import { ROLES } from "@/config/roles";

/**
 * Where each role lands after signing in.
 *
 * Every route here must exist under src/app — the previous map sent
 * receptionists to "/dashboard", which is not a route in this application, so
 * a correct login ended on a 404.
 *
 * Typed as a total Record<Role, string>: adding a realm role without deciding
 * where that person starts is a compile error, not a silent redirect to
 * somebody else's workspace.
 */
const DEFAULT_ROUTES: Record<Role, string> = {
  [ROLES.RECEPTIONIST]: "/receptionist/registration",
  [ROLES.DOCTOR]: "/doctor/dashboard",
  [ROLES.NURSE]: "/nurse/ward-dashboard",
  [ROLES.LAB_TECH]: "/lab",
  [ROLES.RADIOLOGY_TECH]: "/radiology",
  [ROLES.PHARMACIST]: "/pharmacy/prescription-queue",
  [ROLES.EMERGENCY]: "/emergency",
  [ROLES.SUPERVISOR]: "/supervisor/merges",
  [ROLES.ADMIN]: "/admin",
  [ROLES.HOD]: "/hod",
  [ROLES.AUDITOR]: "/audit-viewer",
  [ROLES.PATIENT]: "/patient-portal",
  [ROLES.SUPERADMIN]: "/superadmin",
};

/**
 * Client navigation guard. This is UX containment, not authorization: the API
 * still verifies the JWT and roles on every request. Keeping this map beside
 * the landing routes makes it impossible for the sidebar and guard to invent
 * different role policies.
 */
const ROUTE_PREFIXES: Record<Role, readonly string[]> = {
  [ROLES.RECEPTIONIST]: ["/receptionist", "/billing", "/consent"],
  [ROLES.DOCTOR]: ["/doctor", "/consent", "/ipd", "/lab", "/radiology"],
  [ROLES.NURSE]: ["/nurse", "/ipd", "/consent"],
  [ROLES.LAB_TECH]: ["/lab", "/admin/maintenance"],
  [ROLES.RADIOLOGY_TECH]: ["/radiology", "/admin/maintenance"],
  [ROLES.PHARMACIST]: ["/pharmacy", "/inventory"],
  [ROLES.EMERGENCY]: ["/emergency"],
  // The existing /emergency page registers a new THID and its POST endpoint
  // intentionally excludes supervisors. Their maker-checker promotion APIs
  // need a separate records-authority screen (#221) at /supervisor/merges.
  [ROLES.SUPERVISOR]: ["/supervisor", "/reports"],
  // The backend accepts admin on some HOD reads for operational support, but
  // that does not make a department-operating dashboard part of the admin UI.
  [ROLES.ADMIN]: ["/admin", "/billing", "/reports", "/audit-viewer"],
  // /inventory is NOT decoration here. Indent approval is gated
  // `require_roles("hod")` — HOD ONLY — and the approve/reject buttons live on
  // Inventory -> Indents. Without this prefix the one action only a department
  // head can perform was unreachable by every department head.
  [ROLES.HOD]: ["/hod", "/queue-display", "/inventory"],
  [ROLES.AUDITOR]: ["/audit-viewer", "/reports", "/admin/data-protection"],
  [ROLES.PATIENT]: ["/patient-portal"],
  [ROLES.SUPERADMIN]: ["/superadmin"],
};

/**
 * Paths served without a session, listed once so the edge middleware and the
 * client layout cannot disagree about them.
 *
 * `/queue-display` is the OPD waiting-room wall screen. It has no login by
 * design — the backend's SSE endpoint is unauthenticated for the same reason,
 * and its payload carries only token, doctor name and room, never a patient
 * identifier. Requiring a session here would mean a shared credential taped to
 * a TV in a public corridor, which is worse than no credential at all.
 */
const PUBLIC_PREFIXES: readonly string[] = ["/login", "/queue-display"];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * `null` means the token carried no role we have a workspace for. Send them to
 * the root rather than into a workspace they cannot use — see
 * mapKeycloakRolesToAppRole for why guessing is worse than admitting it.
 */
export function getDefaultRouteForRole(role: Role | null): string {
  return role ? DEFAULT_ROUTES[role] : "/";
}

export function canRoleAccessPath(role: Role | null, pathname: string): boolean {
  if (!role) return false;
  if (pathname === "/") return true;
  if (isPublicPath(pathname)) return true;
  // Defensive: the middleware reads the role from a cookie, which is not
  // typed at runtime. An unrecognised value must deny, not throw on an
  // undefined prefix list.
  return (ROUTE_PREFIXES[role] ?? []).some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
