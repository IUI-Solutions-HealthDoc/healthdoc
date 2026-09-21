import { api } from "@/lib/api";
import type {
  BloodCrossmatch,
  BloodCrossmatchCreate,
  BloodDonor,
  BloodDonorCreate,
  BloodIssueRequest,
  BloodUnit,
  BloodUnitCreate,
} from "./types";

export function fetchBloodDonors(params: {
  blood_group?: string;
  is_eligible?: boolean;
} = {}): Promise<BloodDonor[]> {
  const q = new URLSearchParams();
  if (params.blood_group) q.set("blood_group", params.blood_group);
  if (params.is_eligible !== undefined) q.set("is_eligible", String(params.is_eligible));
  return api<BloodDonor[]>(`/blood-bank/donors?${q.toString()}`);
}

export function registerBloodDonor(payload: BloodDonorCreate): Promise<BloodDonor> {
  return api<BloodDonor>("/blood-bank/donors", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchBloodUnits(params: {
  status?: string;
  blood_group?: string;
  screening_status?: string;
} = {}): Promise<BloodUnit[]> {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.blood_group) q.set("blood_group", params.blood_group);
  if (params.screening_status) q.set("screening_status", params.screening_status);
  return api<BloodUnit[]>(`/blood-bank/units?${q.toString()}`);
}

export function createBloodUnit(payload: BloodUnitCreate): Promise<BloodUnit> {
  return api<BloodUnit>("/blood-bank/units", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function crossmatchBlood(payload: BloodCrossmatchCreate): Promise<BloodCrossmatch> {
  return api<BloodCrossmatch>("/blood-bank/crossmatch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function issueBloodUnit(payload: BloodIssueRequest): Promise<BloodCrossmatch> {
  return api<BloodCrossmatch>("/blood-bank/issue", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
